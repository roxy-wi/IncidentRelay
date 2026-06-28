from flask import jsonify, request
from peewee import DoesNotExist

from app.api.schemas.services import ServiceSloCreateSchema, ServiceSloUpdateSchema
from app.modules.db import services_repo
from app.services.audit import write_audit
from app.services.rbac import current_user, require_team_read, require_team_write
from app.services.serializers import serialize_service_slo
from app.services.service_catalog.events import emit_service_catalog_event
from app.services.service_catalog.objectives import (
    evaluate_service_objectives,
    normalize_objective_window_days,
)
from app.services.service_catalog.snapshots import service_slo_snapshot
from app.services.validation import make_error_response, validate_body
from app.views.services.blueprint import services_bp
from app.views.services.links import _readable_services_from_request


def _get_service_or_404(service_id):
    try:
        return services_repo.get_service(service_id), None
    except DoesNotExist:
        return None, make_error_response(
            "service_not_found",
            "Service was not found",
            404,
            service_id=service_id,
        )


def _get_service_slo_or_404(slo_id):
    try:
        return services_repo.get_service_slo(slo_id), None
    except DoesNotExist:
        return None, make_error_response(
            "service_objective_not_found",
            "Service objective was not found",
            404,
            objective_id=slo_id,
        )


def _serialize_slos(slos, *, days):
    evaluations = evaluate_service_objectives(slos, days=days)

    return [
        serialize_service_slo(
            slo,
            current_user(),
            evaluation=evaluations.get(slo.id),
        )
        for slo in slos
    ]


@services_bp.route("/<int:service_id>/objectives", methods=["GET"])
@services_bp.route("/<int:service_id>/slos", methods=["GET"])
def list_service_objectives(service_id):
    """Return service objectives / SLO targets."""
    service, error = _get_service_or_404(service_id)

    if error:
        return error

    error = require_team_read(service.team_id)

    if error:
        return error

    include_disabled = request.args.get("include_disabled", "1") != "0"
    days = normalize_objective_window_days(request.args.get("days", 30, type=int))
    slos = services_repo.list_service_slos(
        service_id=service.id,
        include_disabled=include_disabled,
    )

    return jsonify(_serialize_slos(slos, days=days))


@services_bp.route("/<int:service_id>/objectives", methods=["POST"])
@services_bp.route("/<int:service_id>/slos", methods=["POST"])
def create_service_objective(service_id):
    """Create a service objective / SLO target."""
    service, error = _get_service_or_404(service_id)

    if error:
        return error

    error = require_team_write(service.team_id)

    if error:
        return error

    payload, error = validate_body(ServiceSloCreateSchema)

    if error:
        return error

    slo = services_repo.create_service_slo(service.id, payload.model_dump())

    write_audit(
        "service_objective.create",
        object_type="service_objective",
        object_id=slo.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data=payload.model_dump(),
    )

    slo_snapshot = service_slo_snapshot(slo)
    emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service_objective.created",
        title="Service objective created",
        summary=slo.name,
        source_ref=f"service_slo:{slo.id}",
        actor_user=current_user(),
        payload={"objective": slo_snapshot},
        readiness_trigger="service_objective_created",
    )

    days = normalize_objective_window_days(request.args.get("days", 30, type=int))
    evaluation = evaluate_service_objectives([slo], days=days).get(slo.id)

    return jsonify(serialize_service_slo(slo, current_user(), evaluation=evaluation)), 201


@services_bp.route("/objectives/<int:slo_id>", methods=["PUT"])
@services_bp.route("/slos/<int:slo_id>", methods=["PUT"])
def update_service_objective(slo_id):
    """Update a service objective / SLO target."""
    slo_before, error = _get_service_slo_or_404(slo_id)

    if error:
        return error

    service = slo_before.service
    error = require_team_write(service.team_id)

    if error:
        return error

    slo_snapshot_before = service_slo_snapshot(slo_before)

    payload, error = validate_body(ServiceSloUpdateSchema)

    if error:
        return error

    slo = services_repo.update_service_slo(slo_id, payload.model_dump())

    write_audit(
        "service_objective.update",
        object_type="service_objective",
        object_id=slo.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data=payload.model_dump(),
    )

    slo_snapshot = service_slo_snapshot(slo)
    emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service_objective.updated",
        title="Service objective updated",
        summary=slo.name,
        source_ref=f"service_slo:{slo.id}",
        actor_user=current_user(),
        before=slo_snapshot_before,
        after=slo_snapshot,
        readiness_trigger="service_objective_updated",
    )

    days = normalize_objective_window_days(request.args.get("days", 30, type=int))
    evaluation = evaluate_service_objectives([slo], days=days).get(slo.id)

    return jsonify(serialize_service_slo(slo, current_user(), evaluation=evaluation))


@services_bp.route("/objectives/<int:slo_id>", methods=["DELETE"])
@services_bp.route("/slos/<int:slo_id>", methods=["DELETE"])
def delete_service_objective(slo_id):
    """Delete a service objective / SLO target."""
    slo_before, error = _get_service_slo_or_404(slo_id)

    if error:
        return error

    service = slo_before.service
    error = require_team_write(service.team_id)

    if error:
        return error

    slo_snapshot_before = service_slo_snapshot(slo_before)
    slo = services_repo.soft_delete_service_slo(slo_id)
    slo_snapshot = service_slo_snapshot(slo)

    write_audit(
        "service_objective.delete",
        object_type="service_objective",
        object_id=slo.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data={"deleted": True},
    )

    emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service_objective.deleted",
        title="Service objective deleted",
        summary=slo_snapshot_before.get("name"),
        source_ref=f"service_slo:{slo.id}",
        actor_user=current_user(),
        before=slo_snapshot_before,
        after=slo_snapshot,
        readiness_trigger="service_objective_deleted",
    )

    return jsonify({"deleted": True, "id": slo.id})


@services_bp.route("/objectives", methods=["GET"])
@services_bp.route("/slos", methods=["GET"])
def list_all_service_objectives():
    """Return objectives for all readable services in current scope."""
    services, error = _readable_services_from_request()

    if error:
        return error

    service_ids = [service.id for service in services]
    include_disabled = request.args.get("include_disabled", "1") != "0"
    days = normalize_objective_window_days(request.args.get("days", 30, type=int))
    slos = services_repo.list_service_slos(
        service_ids=service_ids,
        include_disabled=include_disabled,
    )

    return jsonify(_serialize_slos(slos, days=days))
