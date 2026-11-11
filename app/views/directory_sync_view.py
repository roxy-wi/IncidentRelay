"""Group-admin API for configurable directory and on-call synchronization."""

from flask import Blueprint, jsonify, request
from peewee import DoesNotExist
from pydantic import Field, ValidationError

from app.modules.common import utc_now
from app.modules.crypto import decrypt_json, encrypt_json
from app.modules.db.models import DirectorySyncSource as Source, DirectorySyncCurrent, Group, Team
from app.modules.db.transactions import lock_row, write_transaction
from app.services.admin_tokens import lock_admin_api_token
from app.services.audit import write_audit
from app.services.change_intelligence.management import managed_groups
from app.services.directory_sync.client import ApiClient
from app.services.directory_sync.config import StrictModel, SyncConfig, SyncError, org_service_preset
from app.services.directory_sync.fetch import window
from app.services.directory_sync.service import authorized_actor
from app.services.orchestration.webhooks import _normalize_headers, WebhookValidationError
from app.services.rbac import current_api_token
from app.services.validation import make_error_response

directory_sync_bp = Blueprint("directory_sync_api", __name__)


class SourceInput(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    group_id: int = Field(ge=1)
    config: SyncConfig
    headers: dict[str, str] | None = None
    enabled: bool = False
    revision: int | None = None


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
    return response


@directory_sync_bp.errorhandler(SyncError)
def sync_error(error):
    return make_error_response("sync_conflict", str(error), 409)


@directory_sync_bp.errorhandler(DoesNotExist)
def not_found(_error):
    return make_error_response("not_found", "Synchronization source not found", 404)


@directory_sync_bp.errorhandler(PermissionError)
def access_denied(_error):
    return make_error_response("access_denied", "Group administrator role required", 403)


def require_group(group_id):
    scope = "directory-sync:read" if request.method in {"GET", "HEAD"} else "directory-sync:write"
    lock_admin_api_token(request.current_user.id, scope, group_id=group_id)
    if not authorized_actor(request.current_user.id, group_id):
        raise PermissionError()


def load_source(source_id, *, mutable=False):
    source = lock_row(Source.select().where(Source.id == source_id))
    if source is None:
        raise DoesNotExist()
    require_group(source.group_id)
    if mutable and (source.pending_mode or (source.lease and source.lease_until > utc_now())
                    or (source.current_lease and source.current_lease_until > utc_now())):
        raise SyncError("Synchronization is running or queued; wait for it to finish")
    return source


def serialize(source):
    return {"id": source.id, "name": source.name, "group_id": source.group_id,
            "group_name": source.group.name,
            "config": source.config, "enabled": source.enabled, "revision": source.revision,
            "approved": source.approved_revision == source.revision,
            "has_headers": bool(source.headers_encrypted), "last_error": source.last_error,
            "current_error": source.current_error, "last_result": source.last_result,
            "last_success_at": source.last_success_at.isoformat() + "Z" if source.last_success_at else None,
            "last_current_at": source.last_current_at.isoformat() + "Z" if source.last_current_at else None,
            "pending_mode": source.pending_mode, "running": bool(source.lease and source.lease_until > utc_now()),
            "preview_token": source.preview_token, "preview_result": source.preview_result,
            "preview_until": source.preview_until.isoformat() + "Z" if source.preview_until else None}


@directory_sync_bp.get("")
def list_sources():
    groups = managed_groups(request.current_user).select(Group.id)
    return jsonify([serialize(source) for source in Source.select().where(Source.group.in_(groups)).order_by(Source.id)])


@directory_sync_bp.get("/options")
def options():
    groups = list(managed_groups(request.current_user))
    teams = Team.select().where(Team.group.in_([group.id for group in groups]), Team.deleted == False)
    return jsonify(groups=[{"id": group.id, "name": group.name} for group in groups],
                   teams=[{"id": team.id, "name": team.name, "group_id": team.group_id} for team in teams],
                   preset=org_service_preset())


@directory_sync_bp.get("/<int:source_id>")
def get_source(source_id):
    with write_transaction():
        return jsonify(serialize(load_source(source_id)))


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
        if source_id:
            source = load_source(source_id, mutable=True)
            if source.group_id != payload.group_id:
                raise SyncError("Destination group cannot change after creation")
            if payload.revision != source.revision:
                raise SyncError("Configuration changed; reload it before saving")
            config_changed = source.config != payload.config.model_dump() or headers is not None
            if payload.enabled and (source.approved_revision != source.revision or config_changed):
                raise SyncError("Apply a preview of this configuration before enabling periodic sync")
            source.name = payload.name.strip()
            source.config = payload.config.model_dump()
            source.enabled = payload.enabled
            source.revision += 1
            source.approved_revision = None if config_changed else source.revision if source.approved_revision else None
            if config_changed:
                DirectorySyncCurrent.delete().where(DirectorySyncCurrent.source == source.id).execute()
            source.created_by = request.current_user.id
            source.preview_encrypted = None
            source.preview_token = None
            source.preview_result = None
            if headers is not None:
                source.headers_encrypted = encrypt_json(headers)
            source.save()
        else:
            if payload.enabled:
                raise SyncError("Create a disabled source, then fetch and apply a preview")
            source = Source.create(group=payload.group_id, name=payload.name.strip(),
                                   config=payload.config.model_dump(), headers_encrypted=encrypt_json(headers or {}),
                                   created_by=request.current_user.id)
        write_audit("directory_sync.save", object_type="directory_sync", object_id=source.id,
                    group_id=source.group_id, data={"revision": source.revision, "enabled": source.enabled})
        return jsonify(serialize(source)), 200 if source_id else 201


@directory_sync_bp.post("/<int:source_id>/sample")
def sample(source_id):
    with write_transaction():
        source = load_source(source_id, mutable=True)
    client = ApiClient(SyncConfig.model_validate(source.config), decrypt_json(source.headers_encrypted, default={}))
    pagination = client.config.operations["teams"].pagination
    params = {pagination.size_parameter: 1} if pagination.mode != "none" else {}
    client.request("teams", window(client.config), params)
    return jsonify(samples=client.samples)


@directory_sync_bp.post("/<int:source_id>/preview", defaults={"action": "preview"})
@directory_sync_bp.post("/<int:source_id>/apply", defaults={"action": "apply"})
@directory_sync_bp.post("/<int:source_id>/run", defaults={"action": "run"})
def enqueue(source_id, action):
    if action not in {"preview", "apply", "run"}:
        raise DoesNotExist()
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return make_error_response("validation_error", "Expected a JSON object", 400)
    with write_transaction():
        source = load_source(source_id, mutable=True)
        if payload.get("revision") != source.revision:
            raise SyncError("Configuration changed; reload it")
        if action == "run" and source.approved_revision != source.revision:
            raise SyncError("Apply the first synchronization through preview")
        if action == "apply" and (not source.preview_token or source.preview_token != payload.get("preview_token")
                                  or not source.preview_until or source.preview_until <= utc_now()):
            raise SyncError("Preview expired; fetch a new preview")
        source.pending_mode = action
        if action == "preview":
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
