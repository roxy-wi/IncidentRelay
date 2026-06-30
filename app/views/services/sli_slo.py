from flask import jsonify, request
from peewee import DoesNotExist

from app.api.schemas.services import (
    ServiceSliCreateSchema,
    ServiceSliUpdateSchema,
    ServiceSloCreateSchema,
    ServiceSloUpdateSchema,
)
from app.modules.db import services_repo
from app.services.audit import write_audit
from app.services.rbac import current_user, require_team_read, require_team_write
from app.services.serializers import serialize_service_sli, serialize_service_slo
from app.services.service_catalog.events import emit_service_catalog_event
from app.services.service_catalog.sli_slo import (
    default_slo_comparison_for_sli_type,
    evaluate_service_slos,
    normalize_slo_window_days,
    validate_slo_for_sli,
)
from app.services.service_catalog.snapshots import service_sli_snapshot, service_slo_snapshot
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


def _get_sli_or_404(sli_id):
    try:
        return services_repo.get_service_sli(sli_id), None
    except DoesNotExist:
        return None, make_error_response(
            "service_sli_not_found",
            "Service SLI was not found",
            404,
            sli_id=sli_id,
        )


def _get_slo_or_404(slo_id):
    try:
        return services_repo.get_service_slo(slo_id), None
    except DoesNotExist:
        return None, make_error_response(
            "service_slo_not_found",
            "Service SLO was not found",
            404,
            slo_id=slo_id,
        )


def _serialize_slos(slos, *, days=None):
    evaluations = evaluate_service_slos(slos, persist=False)

    return [
        serialize_service_slo(
            slo,
            current_user(),
            evaluation=evaluations.get(slo.id),
        )
        for slo in slos
    ]


@services_bp.route("/<int:service_id>/slis", methods=["GET"])
def list_service_slis(service_id):
    service, error = _get_service_or_404(service_id)

    if error:
        return error

    error = require_team_read(service.team_id)

    if error:
        return error

    include_disabled = request.args.get("include_disabled", "1") != "0"
    slis = services_repo.list_service_slis(
        service_id=service.id,
        include_disabled=include_disabled,
    )

    return jsonify([serialize_service_sli(sli, current_user()) for sli in slis])


@services_bp.route("/<int:service_id>/slis", methods=["POST"])
def create_service_sli(service_id):
    service, error = _get_service_or_404(service_id)

    if error:
        return error

    error = require_team_write(service.team_id)

    if error:
        return error

    payload, error = validate_body(ServiceSliCreateSchema)

    if error:
        return error

    sli = services_repo.create_service_sli(service.id, payload.model_dump())
    snapshot = service_sli_snapshot(sli)

    write_audit(
        "service_sli.create",
        object_type="service_sli",
        object_id=sli.id,
        data=snapshot,
    )
    emit_service_catalog_event(
        service,
        category="sli_slo",
        event_type="service_sli.created",
        title="Service SLI created",
        summary=sli.name,
        source_ref=f"service_sli:{sli.id}",
        actor_user=current_user(),
        payload={"sli": snapshot},
        readiness_trigger="service_sli_created",
    )

    return jsonify(serialize_service_sli(sli, current_user())), 201


@services_bp.route("/slis/<int:sli_id>", methods=["PUT"])
def update_service_sli(sli_id):
    sli, error = _get_sli_or_404(sli_id)

    if error:
        return error

    service = sli.service
    error = require_team_write(service.team_id)

    if error:
        return error

    payload, error = validate_body(ServiceSliUpdateSchema)

    if error:
        return error

    before = service_sli_snapshot(sli)
    sli = services_repo.update_service_sli(sli.id, payload.model_dump())
    after = service_sli_snapshot(sli)

    write_audit(
        "service_sli.update",
        object_type="service_sli",
        object_id=sli.id,
        data={"before": before, "after": after},
    )
    emit_service_catalog_event(
        service,
        category="sli_slo",
        event_type="service_sli.updated",
        title="Service SLI updated",
        summary=sli.name,
        source_ref=f"service_sli:{sli.id}",
        actor_user=current_user(),
        before=before,
        after=after,
        readiness_trigger="service_sli_updated",
    )

    return jsonify(serialize_service_sli(sli, current_user()))


@services_bp.route("/slis/<int:sli_id>", methods=["DELETE"])
def delete_service_sli(sli_id):
    sli, error = _get_sli_or_404(sli_id)

    if error:
        return error

    service = sli.service
    error = require_team_write(service.team_id)

    if error:
        return error

    before = service_sli_snapshot(sli)
    sli = services_repo.soft_delete_service_sli(sli.id)
    after = service_sli_snapshot(sli)

    write_audit(
        "service_sli.delete",
        object_type="service_sli",
        object_id=sli.id,
        data={"before": before, "after": after},
    )
    emit_service_catalog_event(
        service,
        category="sli_slo",
        event_type="service_sli.deleted",
        title="Service SLI deleted",
        summary=sli.name,
        source_ref=f"service_sli:{sli.id}",
        actor_user=current_user(),
        before=before,
        after=after,
        readiness_trigger="service_sli_deleted",
    )

    return jsonify(serialize_service_sli(sli, current_user()))


@services_bp.route("/<int:service_id>/slos", methods=["GET"])
def list_service_slos(service_id):
    service, error = _get_service_or_404(service_id)

    if error:
        return error

    error = require_team_read(service.team_id)

    if error:
        return error

    include_disabled = request.args.get("include_disabled", "1") != "0"
    normalize_slo_window_days(request.args.get("days", 30, type=int))
    slos = services_repo.list_service_slos(
        service_id=service.id,
        include_disabled=include_disabled,
    )

    return jsonify(_serialize_slos(slos))


@services_bp.route("/<int:service_id>/slos", methods=["POST"])
def create_service_slo(service_id):
    service, error = _get_service_or_404(service_id)

    if error:
        return error

    error = require_team_write(service.team_id)

    if error:
        return error

    payload, error = validate_body(ServiceSloCreateSchema)

    if error:
        return error

    sli, error = _get_sli_or_404(payload.sli_id)

    if error:
        return error

    if sli.service_id != service.id:
        return make_error_response("service_sli_mismatch", "SLI belongs to another service", 400)

    data = payload.model_dump()
    data["comparison"] = data.get("comparison") or default_slo_comparison_for_sli_type(sli.sli_type)
    validation_error = validate_slo_for_sli(sli, data)

    if validation_error:
        return make_error_response("service_slo_invalid", validation_error, 400)

    slo = services_repo.create_service_slo(service.id, data)
    snapshot = service_slo_snapshot(slo)

    write_audit(
        "service_slo.create",
        object_type="service_slo",
        object_id=slo.id,
        data=snapshot,
    )
    emit_service_catalog_event(
        service,
        category="sli_slo",
        event_type="service_slo.created",
        title="Service SLO created",
        summary=slo.name,
        source_ref=f"service_slo:{slo.id}",
        actor_user=current_user(),
        payload={"slo": snapshot},
        readiness_trigger="service_slo_created",
    )

    evaluation = evaluate_service_slos([slo]).get(slo.id)
    return jsonify(serialize_service_slo(slo, current_user(), evaluation=evaluation)), 201


@services_bp.route("/slos/<int:slo_id>", methods=["PUT"])
def update_service_slo(slo_id):
    slo, error = _get_slo_or_404(slo_id)

    if error:
        return error

    service = slo.service
    error = require_team_write(service.team_id)

    if error:
        return error

    payload, error = validate_body(ServiceSloUpdateSchema)

    if error:
        return error

    sli, error = _get_sli_or_404(payload.sli_id)

    if error:
        return error

    if sli.service_id != service.id:
        return make_error_response("service_sli_mismatch", "SLI belongs to another service", 400)

    data = payload.model_dump()
    data["comparison"] = data.get("comparison") or default_slo_comparison_for_sli_type(sli.sli_type)
    validation_error = validate_slo_for_sli(sli, data)

    if validation_error:
        return make_error_response("service_slo_invalid", validation_error, 400)

    before = service_slo_snapshot(slo)
    slo = services_repo.update_service_slo(slo.id, data)
    after = service_slo_snapshot(slo)

    write_audit(
        "service_slo.update",
        object_type="service_slo",
        object_id=slo.id,
        data={"before": before, "after": after},
    )
    emit_service_catalog_event(
        service,
        category="sli_slo",
        event_type="service_slo.updated",
        title="Service SLO updated",
        summary=slo.name,
        source_ref=f"service_slo:{slo.id}",
        actor_user=current_user(),
        before=before,
        after=after,
        readiness_trigger="service_slo_updated",
    )

    evaluation = evaluate_service_slos([slo]).get(slo.id)
    return jsonify(serialize_service_slo(slo, current_user(), evaluation=evaluation))


@services_bp.route("/slos/<int:slo_id>", methods=["DELETE"])
def delete_service_slo(slo_id):
    slo, error = _get_slo_or_404(slo_id)

    if error:
        return error

    service = slo.service
    error = require_team_write(service.team_id)

    if error:
        return error

    before = service_slo_snapshot(slo)
    slo = services_repo.soft_delete_service_slo(slo.id)
    after = service_slo_snapshot(slo)

    write_audit(
        "service_slo.delete",
        object_type="service_slo",
        object_id=slo.id,
        data={"before": before, "after": after},
    )
    emit_service_catalog_event(
        service,
        category="sli_slo",
        event_type="service_slo.deleted",
        title="Service SLO deleted",
        summary=slo.name,
        source_ref=f"service_slo:{slo.id}",
        actor_user=current_user(),
        before=before,
        after=after,
        readiness_trigger="service_slo_deleted",
    )

    return jsonify(serialize_service_slo(slo, current_user()))


def _serialize_sli_slo_analytics_item(slo, evaluation):
    sli = slo.sli
    service = slo.service
    team = service.team if service and service.team_id else None

    return {
        "service_id": service.id,
        "service_name": service.name,
        "service_slug": service.slug,
        "service_status": service.status,
        "service_criticality": service.criticality,
        "team_id": team.id if team else None,
        "team_name": team.name if team else None,
        "team_slug": team.slug if team else None,
        "sli_id": sli.id,
        "sli_name": sli.name,
        "sli_slug": sli.slug,
        "sli_type": sli.sli_type,
        "sli_source": sli.source,
        "sli_severity": sli.severity,
        "sli_priority": sli.priority,
        "slo_id": slo.id,
        "slo_name": slo.name,
        "slo_description": slo.description,
        "comparison": slo.comparison,
        "target_percent_basis_points": slo.target_percent_basis_points,
        "threshold_seconds": slo.threshold_seconds,
        "threshold_count": slo.threshold_count,
        "window_days": slo.window_days,
        "exclude_maintenance": slo.exclude_maintenance,
        "include_open_alerts": slo.include_open_alerts,
        "enabled": slo.enabled,
        "status": evaluation.get("status") if evaluation else "no_data",
        "evaluation": evaluation or {},
    }


def _slo_analytics_summary(items):
    summary = {
        "total": len(items),
        "met": 0,
        "at_risk": 0,
        "breached": 0,
        "no_data": 0,
        "disabled": 0,
        "services": len({item["service_id"] for item in items}),
    }

    for item in items:
        if not item.get("enabled"):
            summary["disabled"] += 1
            continue

        status = item.get("status") or "no_data"

        if status not in summary:
            status = "no_data"

        summary[status] += 1

    return summary


@services_bp.route("/sli-slo/analytics", methods=["GET"])
def get_service_sli_slo_analytics():
    services, error = _readable_services_from_request()

    if error:
        return error

    service_ids = [service.id for service in services]
    include_disabled = request.args.get("include_disabled", "0") != "0"
    days = normalize_slo_window_days(request.args.get("days", 30, type=int))

    slos = services_repo.list_service_slos(
        service_ids=service_ids,
        include_disabled=include_disabled,
    )
    evaluations = evaluate_service_slos(slos, persist=False)
    items = [
        _serialize_sli_slo_analytics_item(slo, evaluations.get(slo.id))
        for slo in slos
    ]

    items.sort(key=lambda item: (
        {
            "breached": 0,
            "at_risk": 1,
            "no_data": 2,
            "met": 3,
        }.get(item.get("status"), 2),
        item.get("service_name") or "",
        item.get("slo_name") or "",
    ))

    return jsonify({
        "window": {"days": days},
        "summary": _slo_analytics_summary(items),
        "items": items,
    })


@services_bp.route("/sli-slo", methods=["GET"])
def list_all_service_sli_slo():
    services, error = _readable_services_from_request()

    if error:
        return error

    service_ids = [service.id for service in services]
    include_disabled = request.args.get("include_disabled", "1") != "0"

    slis = services_repo.list_service_slis(
        service_ids=service_ids,
        include_disabled=include_disabled,
    )
    slos = services_repo.list_service_slos(
        service_ids=service_ids,
        include_disabled=include_disabled,
    )

    return jsonify({
        "slis": [serialize_service_sli(sli, current_user()) for sli in slis],
        "slos": _serialize_slos(slos),
    })
