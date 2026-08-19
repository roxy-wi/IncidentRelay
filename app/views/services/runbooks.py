from flask import jsonify

from app.views.services.blueprint import services_bp
from app.api.schemas.services import ServiceRunbookCreateSchema, ServiceRunbookUpdateSchema
from app.modules.db import services_repo
from app.services.audit import write_audit
from app.services.rbac import require_team_read, current_user, require_team_write
from app.services.routing.matcher import service as matcher_preset_service
from app.services.serializers.services import serialize_service_runbook
from app.services.service_catalog.events import emit_service_catalog_event
from app.services.service_catalog.snapshots import service_runbook_snapshot
from app.services.validation import make_error_response, validate_body
from app.views.services.links import _readable_services_from_request


def _validate_runbook_matcher_preset(service, preset_id):
    try:
        preset = matcher_preset_service.validate_preset_assignment(
            preset_id,
            team_id=service.team_id,
        )
    except matcher_preset_service.MatcherPresetNotFoundError:
        return None, make_error_response(
            "matcher_preset_not_found",
            "Matcher preset was not found.",
            400,
        )
    except matcher_preset_service.MatcherPresetError:
        return None, make_error_response(
            "matcher_preset_invalid",
            "Matcher preset is invalid or unavailable.",
            400,
        )

    return preset, None


@services_bp.route("/<int:service_id>/runbooks", methods=["GET"])
def list_service_runbooks(service_id):
    """Return service runbooks."""
    service = services_repo.get_service(service_id)

    error = require_team_read(service.team_id)
    if error:
        return error

    return jsonify([
        serialize_service_runbook(runbook, current_user())
        for runbook in services_repo.list_service_runbooks(service_id)
    ])


@services_bp.route("/<int:service_id>/runbooks", methods=["POST"])
def create_service_runbook(service_id):
    """Create a service runbook."""
    service = services_repo.get_service(service_id)

    error = require_team_write(service.team_id)
    if error:
        return error

    payload, error = validate_body(ServiceRunbookCreateSchema)
    if error:
        return error

    preset, preset_error = _validate_runbook_matcher_preset(service, payload.matcher_preset_id)
    if preset_error:
        return preset_error

    data = payload.model_dump()
    data.pop("matcher_preset_id", None)
    data["matcher_preset"] = preset.id if preset else None

    runbook = services_repo.create_service_runbook(service_id, data)

    write_audit(
        "service_runbook.create",
        object_type="service_runbook",
        object_id=runbook.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data=payload.model_dump(),
    )

    runbook_snapshot = service_runbook_snapshot(runbook)
    emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service_runbook.created",
        title="Service runbook created",
        summary=runbook.title or runbook.url,
        source_ref=f"service_runbook:{runbook.id}",
        external_url=runbook.url,
        actor_user=current_user(),
        payload={"runbook": runbook_snapshot},
        readiness_trigger="service_runbook_created",
    )

    return jsonify(serialize_service_runbook(runbook, current_user())), 201


@services_bp.route("/runbooks/<int:runbook_id>", methods=["PUT"])
def update_service_runbook(runbook_id):
    """Update a service runbook."""
    runbook_before = services_repo.get_service_runbook(runbook_id)
    service = runbook_before.service

    error = require_team_write(runbook_before.service.team_id)
    if error:
        return error

    runbook_snapshot_before = service_runbook_snapshot(runbook_before)

    payload, error = validate_body(ServiceRunbookUpdateSchema)
    if error:
        return error

    preset, preset_error = _validate_runbook_matcher_preset(runbook_before.service, payload.matcher_preset_id)
    if preset_error:
        return preset_error

    data = payload.model_dump()
    data.pop("matcher_preset_id", None)
    data["matcher_preset"] = preset.id if preset else None

    runbook = services_repo.update_service_runbook(runbook_id, data)

    write_audit(
        "service_runbook.update",
        object_type="service_runbook",
        object_id=runbook.id,
        group_id=runbook.service.group_id,
        team_id=runbook.service.team_id,
        data=payload.model_dump(),
    )

    runbook_snapshot = service_runbook_snapshot(runbook)
    emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service_runbook.updated",
        title="Service runbook updated",
        summary=runbook.title or runbook.url,
        source_ref=f"service_runbook:{runbook.id}",
        external_url=runbook.url,
        actor_user=current_user(),
        before=runbook_snapshot_before,
        after=runbook_snapshot,
        readiness_trigger="service_runbook_updated",
    )

    return jsonify(serialize_service_runbook(runbook, current_user()))


@services_bp.route("/runbooks/<int:runbook_id>", methods=["DELETE"])
def delete_service_runbook(runbook_id):
    """Delete a service runbook."""
    runbook_before = services_repo.get_service_runbook(runbook_id)
    service = runbook_before.service

    error = require_team_write(runbook_before.service.team_id)
    if error:
        return error

    runbook_snapshot_before = service_runbook_snapshot(runbook_before)
    runbook = services_repo.soft_delete_service_runbook(runbook_id)

    write_audit(
        "service_runbook.delete",
        object_type="service_runbook",
        object_id=runbook.id,
        group_id=runbook.service.group_id,
        team_id=runbook.service.team_id,
        data={"deleted": True},
    )
    runbook_snapshot = service_runbook_snapshot(runbook)
    emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service_runbook.deleted",
        title="Service runbook deleted",
        summary=runbook_snapshot_before.get("title") or runbook_snapshot_before.get("url"),
        source_ref=f"service_runbook:{runbook.id}",
        external_url=runbook_snapshot_before.get("url"),
        actor_user=current_user(),
        before=runbook_snapshot_before,
        after=runbook_snapshot,
        readiness_trigger="service_runbook_deleted",
    )

    return jsonify({"deleted": True, "id": runbook.id})


@services_bp.route("/runbooks", methods=["GET"])
def list_all_service_runbooks():
    """Return runbooks for all readable services in current scope."""
    services, error = _readable_services_from_request()
    if error:
        return error

    service_ids = [service.id for service in services]

    return jsonify([
        serialize_service_runbook(runbook, current_user())
        for runbook in services_repo.list_service_runbooks(service_ids=service_ids)
    ])
