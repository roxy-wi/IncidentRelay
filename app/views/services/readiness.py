from flask import jsonify
from peewee import DoesNotExist

from app.views.services.blueprint import services_bp
from app.modules.db import services_repo
from app.services.audit import write_audit
from app.services.rbac import require_team_read, require_team_write, current_user
from app.services.serializers import serialize_service_readiness
from app.services.service_catalog import readiness as service_readiness
from app.services.service_catalog.events import reconcile_service_catalog_readiness
from app.services.validation import make_error_response


def _service_readiness_payload(service):
    state, evaluations, results_by_evaluation = (
        service_readiness.load_service_readiness_batch(service.id)
    )

    payload = serialize_service_readiness(
        state,
        evaluations=evaluations,
        results_by_evaluation=results_by_evaluation,
    )
    payload["service_id"] = service.id

    return payload


@services_bp.route("/<int:service_id>/readiness", methods=["GET"])
def get_service_readiness(service_id):
    """Return the current readiness batch for a service."""

    try:
        service = services_repo.get_service(service_id)
    except DoesNotExist:
        return make_error_response(
            "service_not_found",
            "Service was not found",
            404,
            service_id=service_id,
        )

    error = require_team_read(service.team_id)

    if error:
        return error

    return jsonify(_service_readiness_payload(service))


@services_bp.route("/<int:service_id>/readiness/evaluate", methods=["POST"])
def evaluate_service_readiness(service_id):
    """Evaluate all applicable standards for a service."""

    try:
        service = services_repo.get_service(service_id)
    except DoesNotExist:
        return make_error_response(
            "service_not_found",
            "Service was not found",
            404,
            service_id=service_id,
        )

    error = require_team_write(service.team_id)

    if error:
        return error

    result = reconcile_service_catalog_readiness(
        service,
        trigger="manual",
        actor_user=current_user(),
    )
    state = result["state"]

    write_audit(
        "service_readiness.evaluate",
        object_type="service",
        object_id=service.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data={
            "batch_uid": str(state.batch_uid),
            "status": state.status,
            "score": state.score,
            "standards_count": state.standards_count,
            "checks_count": state.checks_count,
            "failed_count": state.failed_count,
        },
    )

    return jsonify(_service_readiness_payload(service))
