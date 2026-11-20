"""Group-admin API for configurable directory and on-call synchronization."""

from datetime import timedelta
from typing import Literal

from flask import Blueprint, g, jsonify, request
from peewee import DoesNotExist
from pydantic import Field, ValidationError

from app.modules.common import utc_now
from app.modules.crypto import decrypt_json, encrypt_json
from app.modules.db.models import DirectorySyncSource as Source, DirectorySyncCurrent, Group, Team
from app.modules.db.transactions import lock_row, write_transaction
from app.services.admin_tokens import lock_admin_api_token
from app.services.audit import write_audit
from app.services.change_intelligence.management import managed_groups
from app.services.sync.cmdb.config import CmdbConfig, is_cmdb, jira_assets_preset, parse_config
from app.services.sync.directory.client import ApiClient
from app.services.sync.directory.config import (
    StrictModel, SyncApiError, SyncConfig, SyncError, current_api_enabled, org_service_preset,
)
from app.services.sync.directory.fetch import window
from app.services.sync.directory.diagnostics import log_failure
from app.services.sync.directory.management import remove_source
from app.services.sync.directory.reconnect import archived_source, retained_sources
from app.services.sync.directory.service import authorized_actor, has_pending_preview
from app.services.orchestration.webhooks import _normalize_headers, WebhookValidationError
from app.services.rbac import current_api_token
from app.services.validation import make_error_response

directory_sync_bp = Blueprint("directory_sync_api", __name__)


class SourceInput(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    group_id: int = Field(ge=1)
    config: SyncConfig | CmdbConfig
    headers: dict[str, str] | None = None
    enabled: bool = False
    revision: int | None = None


class SourceDeleteInput(StrictModel):
    revision: int = Field(ge=1, strict=True)
    data_action: Literal["keep", "delete"]


@directory_sync_bp.before_request
def require_admin():
    user = getattr(request, "current_user", None)
    token = current_api_token()
    if not user or not user.active or user.deleted:
        return make_error_response("authentication_required", "Authentication is required", 401)
    if (token and (token.team_id or token.change_integration_id)) or not managed_groups(user).exists():
        return make_error_response("access_denied", "Group administrator role required", 403)
    return None


@directory_sync_bp.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    if response.status_code >= 400 and not getattr(g, "directory_sync_error_logged", False):
        # Also record failures returned directly by validation and access checks.
        # The request/configuration and response body are deliberately omitted.
        log_failure(SyncError(f"Synchronization request failed with HTTP {response.status_code}"),
                    source_id=(request.view_args or {}).get("source_id"),
                    operation=request.endpoint, http_status=response.status_code)
    return response


@directory_sync_bp.errorhandler(SyncError)
def sync_error(error):
    log_request_failure(error, 409)
    return make_error_response("sync_conflict", str(error), 409)


@directory_sync_bp.errorhandler(SyncApiError)
def sync_api_error(error):
    log_request_failure(error, error.status_code)
    return make_error_response("sync_api_error", str(error), error.status_code)


def log_request_failure(error, status):
    """Keep the safe exception detail once, rather than logging response bodies."""
    log_failure(error, source_id=(request.view_args or {}).get("source_id"),
                operation=request.endpoint, http_status=status)
    g.directory_sync_error_logged = True


@directory_sync_bp.errorhandler(DoesNotExist)
def not_found(_error):
    return make_error_response("not_found", "Synchronization source not found", 404)


@directory_sync_bp.errorhandler(PermissionError)
def access_denied(_error):
    return make_error_response("access_denied", "Group administrator role required", 403)


def require_group(group_id, *, for_update=True):
    scope = "directory-sync:read" if request.method in {"GET", "HEAD"} else "directory-sync:write"
    lock_admin_api_token(request.current_user.id, scope, group_id=group_id, for_update=for_update)
    if not authorized_actor(request.current_user.id, group_id):
        raise PermissionError()


def load_source(source_id, *, mutable=False, include_deleted=False, for_update=True):
    query = Source.select().where(Source.id == source_id)
    source = lock_row(query) if for_update else query.first()
    if source is None:
        raise DoesNotExist()
    require_group(source.group_id, for_update=for_update)
    if source.deleted and not include_deleted:
        raise DoesNotExist()
    if mutable and (source.pending_mode or (source.lease and source.lease_until > utc_now())
                    or (source.current_lease and source.current_lease_until > utc_now())):
        raise SyncError("Synchronization is running or queued; wait for it to finish")
    return source


def serialize(source):
    approved = source.approved_revision == source.revision
    preview_ready = has_pending_preview(source, utc_now())
    schedule_state = ("disabled" if not source.enabled else "pending_approval" if not approved
                      else "preview" if preview_ready else "enabled")
    current_scheduled = (
        approved and source.last_success_at and current_api_enabled(source.config)
        and (source.enabled or (
            source.next_current_at <= source.last_success_at
            and (not source.last_current_at or source.last_current_at < source.last_success_at)
        ))
    )
    return {"id": source.id, "name": source.name, "group_id": source.group_id,
            "source_type": "jira_assets" if is_cmdb(source.config) else "directory",
            "group_name": source.group.name,
            "config": source.config, "enabled": source.enabled, "revision": source.revision,
            "approved": approved, "schedule_state": schedule_state,
            "has_headers": bool(source.headers_encrypted), "last_error": source.last_error,
            "current_error": source.current_error, "last_result": source.last_result,
            "last_success_at": source.last_success_at.isoformat() + "Z" if source.last_success_at else None,
            "last_current_at": source.last_current_at.isoformat() + "Z" if source.last_current_at else None,
            "next_run_at": source.next_run_at.isoformat() + "Z" if schedule_state == "enabled" else None,
            "next_current_at": source.next_current_at.isoformat() + "Z" if current_scheduled else None,
            "current_running": bool(source.current_lease and source.current_lease_until > utc_now()),
            "pending_mode": source.pending_mode, "running": bool(source.lease and source.lease_until > utc_now()),
            "preview_token": source.preview_token if preview_ready else None, "preview_result": source.preview_result,
            "preview_until": source.preview_until.isoformat() + "Z" if source.preview_until else None}


@directory_sync_bp.get("")
def list_sources():
    groups = managed_groups(request.current_user).select(Group.id)
    return jsonify([serialize(source) for source in Source.select().where(
        Source.group.in_(groups), Source.deleted == False,
    ).order_by(Source.id)])


@directory_sync_bp.get("/options")
def options():
    groups = list(managed_groups(request.current_user))
    teams = Team.select().where(Team.group.in_([group.id for group in groups]), Team.deleted == False)
    return jsonify(groups=[{"id": group.id, "name": group.name} for group in groups],
                   teams=[{"id": team.id, "name": team.name, "group_id": team.group_id, "active": team.active} for team in teams],
                   retained_sources=[{"id": source.id, "name": source.name, "group_id": source.group_id,
                                      "base_url": source.config["base_url"]}
                                     for source in retained_sources([group.id for group in groups])],
                   preset=org_service_preset(), cmdb_preset=jira_assets_preset())


@directory_sync_bp.get("/<int:source_id>")
def get_source(source_id):
    # Polling must remain readable while preview/apply holds SQLite's writer lock.
    return jsonify(serialize(load_source(source_id, for_update=False)))


@directory_sync_bp.delete("/<int:source_id>")
def delete_source(source_id):
    try:
        payload = SourceDeleteInput.model_validate(request.get_json(silent=True))
    except ValidationError:
        return make_error_response("validation_error", "Specify revision and data_action: keep or delete", 400)
    with write_transaction():
        source = load_source(source_id, mutable=True, include_deleted=True)
        if source.deleted:
            return jsonify(id=source.id, deleted=True)
        if source.revision != payload.revision:
            raise SyncError("Configuration changed; reload it before deleting")
        remove_source(source, delete_imported=payload.data_action == "delete")
        write_audit("directory_sync.delete", object_type="directory_sync", object_id=source.id,
                    group_id=source.group_id, data={"data_action": payload.data_action})
        return jsonify(id=source.id, deleted=True)


def update_refresh_schedule(source, previous, config, *, import_changed):
    """Apply interval changes without starting an import or retaining stale duty."""
    if isinstance(config, CmdbConfig):
        if previous.interval_seconds != config.interval_seconds:
            source.next_run_at = utc_now() + timedelta(seconds=config.interval_seconds)
        return
    current_changed = (
        previous.current_enabled != config.current_enabled
        or previous.current_fields != config.current_fields
        or previous.current_fetch != config.current_fetch
        or previous.operations.get("current") != config.operations.get("current")
        or previous.current_max_age_seconds != config.current_max_age_seconds
    )
    if import_changed or current_changed:
        DirectorySyncCurrent.delete().where(DirectorySyncCurrent.source == source.id).execute()
    if current_changed:
        source.current_error = None
    if import_changed:
        return
    if previous.interval_seconds != config.interval_seconds:
        if source.last_error:
            source.next_run_at = utc_now() + timedelta(seconds=config.interval_seconds)
        elif source.last_success_at:
            source.next_run_at = source.last_success_at + timedelta(seconds=config.interval_seconds)
    if current_changed:
        source.next_current_at = utc_now()
    elif previous.current_interval_seconds != config.current_interval_seconds and source.enabled:
        # Restart the interval on save, including after a failed first check.
        # Paused sources retain their one immediate check after a manual import.
        source.next_current_at = utc_now() + timedelta(seconds=config.current_interval_seconds)


@directory_sync_bp.post("")
@directory_sync_bp.put("/<int:source_id>")
def save_source(source_id=None):
    try:
        payload = SourceInput.model_validate(request.get_json(silent=True))
        headers = _normalize_headers(payload.headers) if payload.headers is not None else None
    except (ValidationError, WebhookValidationError) as error:
        # Validation messages must never echo header values.
        details = [{"field": ".".join(map(str, item["loc"])), "message": item["msg"]}
                   for item in error.errors(include_input=False, include_context=False)] if isinstance(error, ValidationError) else []
        return jsonify(error="validation_error", message="Invalid synchronization configuration", details=details), 400
    with write_transaction():
        require_group(payload.group_id)
        if isinstance(payload.config, SyncConfig) and payload.config.retained_source_id is not None:
            archived_source(payload.config.retained_source_id, payload.group_id)
        if source_id:
            source = load_source(source_id, mutable=True)
            if source.group_id != payload.group_id:
                raise SyncError("Destination group cannot change after creation")
            if payload.revision != source.revision:
                raise SyncError("Configuration changed; reload it before saving")
            previous_config = parse_config(source.config)
            if type(previous_config) is not type(payload.config):
                raise SyncError("Source type cannot change after creation")
            if isinstance(payload.config, CmdbConfig):
                validate_cmdb_teams(payload.config, payload.group_id, previous=previous_config)
            if (isinstance(payload.config, CmdbConfig) and source.last_success_at
                    and previous_config.base_url != payload.config.base_url):
                raise SyncError("Jira base URL cannot change after importing objects; create a separate source")
            if (isinstance(payload.config, SyncConfig) and source.last_success_at
                    and previous_config.retained_source_id != payload.config.retained_source_id):
                raise SyncError("The retained source cannot change after the first successful import")
            headers_changed = headers is not None and headers != decrypt_json(source.headers_encrypted, default={})
            import_changed = (
                previous_config.import_settings() != payload.config.import_settings()
                or headers_changed
            )
            approved = source.approved_revision == source.revision
            source.name = payload.name.strip()
            source.config = payload.config.model_dump()
            # Keep the requested schedule state. Approval fences both schedulers
            # until the changed import has been previewed and applied.
            source.enabled = payload.enabled
            source.revision += 1
            source.approved_revision = source.revision if approved and not import_changed else None
            update_refresh_schedule(source, previous_config, payload.config, import_changed=import_changed)
            source.created_by = request.current_user.id
            preview = None
            if (not import_changed and source.preview_token and source.preview_encrypted
                    and source.preview_until and source.preview_until > utc_now()):
                saved_preview = decrypt_json(source.preview_encrypted)
                if saved_preview["revision"] == payload.revision:
                    preview = saved_preview
            if preview is None:
                source.preview_encrypted = None
                source.preview_token = None
                previous_result = source.preview_result or {}
                source.preview_result = None
                if isinstance(payload.config, CmdbConfig):
                    source.preview_result = previous_result
                    if import_changed:
                        query_changed = (
                            previous_config.services.query != payload.config.services.query
                            or previous_config.business_services.query != payload.config.business_services.query
                            or previous_config.base_url != payload.config.base_url
                            or previous_config.api_path != payload.config.api_path
                        )
                        source.preview_result = {
                            "attributes": {} if query_changed else previous_result.get("attributes", {}),
                            "team_catalog": [] if query_changed else previous_result.get("team_catalog", []),
                            "changes": [], "issues": [], "inspection": True,
                        }
                source.preview_until = None
            else:
                preview["revision"] = source.revision
                source.preview_encrypted = encrypt_json(preview)
            if headers is not None:
                source.headers_encrypted = encrypt_json(headers)
            source.save()
        else:
            if isinstance(payload.config, CmdbConfig):
                validate_cmdb_teams(payload.config, payload.group_id)
            source = Source.create(group=payload.group_id, name=payload.name.strip(),
                                   config=payload.config.model_dump(), headers_encrypted=encrypt_json(headers or {}),
                                   enabled=payload.enabled, created_by=request.current_user.id)
        write_audit("directory_sync.save", object_type="directory_sync", object_id=source.id,
                    group_id=source.group_id, data={"revision": source.revision, "enabled": source.enabled})
        return jsonify(serialize(source)), 200 if source_id else 201


def validate_cmdb_teams(config, group_id, *, previous=None):
    """Reject invalid new mappings without preventing an unhealthy source's pause."""
    old = previous.team_matches if previous else {}
    ids = {local_id for key, local_id in config.team_matches.items() if old.get(key) != local_id}
    valid_ids = {team.id for team in Team.select(Team.id).where(
        Team.id.in_(ids), Team.group == group_id, Team.active == True, Team.deleted == False,
    )}
    if ids != valid_ids:
        raise SyncError("Map CMDB teams only to active existing teams in the destination group")


@directory_sync_bp.post("/<int:source_id>/sample")
def sample(source_id):
    with write_transaction():
        source = load_source(source_id, mutable=True)
    if is_cmdb(source.config):
        raise SyncError("Use the queued inspect action for Jira Assets sources")
    client = ApiClient(SyncConfig.model_validate(source.config), decrypt_json(source.headers_encrypted, default={}))
    pagination = client.config.operations["teams"].pagination
    params = {pagination.size_parameter: 1} if pagination.mode != "none" else {}
    client.request("teams", window(client.config), params)
    return jsonify(samples=client.samples)


@directory_sync_bp.post("/<int:source_id>/preview", defaults={"action": "preview"})
@directory_sync_bp.post("/<int:source_id>/apply", defaults={"action": "apply"})
@directory_sync_bp.post("/<int:source_id>/run", defaults={"action": "run"})
@directory_sync_bp.post("/<int:source_id>/inspect", defaults={"action": "inspect"})
def enqueue(source_id, action):
    if action not in {"preview", "apply", "run", "inspect"}:
        raise DoesNotExist()
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return make_error_response("validation_error", "Expected a JSON object", 400)
    with write_transaction():
        source = load_source(source_id, mutable=True)
        if action == "inspect" and not is_cmdb(source.config):
            raise SyncError("Inspect is available for Jira Assets sources")
        if payload.get("revision") != source.revision:
            raise SyncError("Configuration changed; reload it")
        if action == "run" and source.approved_revision != source.revision:
            raise SyncError("Apply the first synchronization through preview")
        if action == "apply" and (not source.preview_token or source.preview_token != payload.get("preview_token")
                                  or not source.preview_until or source.preview_until <= utc_now()):
            raise SyncError("Preview expired; fetch a new preview")
        source.pending_mode = action
        if action in {"preview", "inspect"}:
            source.preview_token = None
            source.preview_encrypted = None
            source.preview_result = None
        source.pending_preview_token = payload.get("preview_token") if action == "apply" else None
        source.last_error = None
        source.save(only=[Source.pending_mode, Source.pending_preview_token, Source.last_error,
                          Source.preview_token, Source.preview_encrypted, Source.preview_result])
        write_audit("directory_sync.queue", object_type="directory_sync", object_id=source.id,
                    group_id=source.group_id, data={"action": action})
        return jsonify(serialize(source)), 202
