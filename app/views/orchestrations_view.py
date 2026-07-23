"""Event Orchestration simulator, replay and execution APIs."""

from flask import Blueprint, jsonify, request

from app.api.schemas.orchestrations import (
    OrchestrationReplaySchema,
    OrchestrationSimulationSchema,
)
from app.services.audit import write_audit
from app.services.orchestration import simulator
from app.services.orchestration.permissions import (
    REPLAY,
    SIMULATE,
    VIEW_EXECUTIONS,
    has_orchestration_permission,
)
from app.services.rbac import current_user
from app.services.validation import make_error_response, validate_body


orchestrations_bp = Blueprint("event_orchestrations_api", __name__)


@orchestrations_bp.errorhandler(simulator.OrchestrationSimulationError)
def handle_orchestration_simulation_error(error):
    if isinstance(error, simulator.OrchestrationSimulationNotFound):
        code = "orchestration_not_found"
        status = 404
    elif isinstance(error, simulator.OrchestrationSimulationConflict):
        code = "orchestration_conflict"
        status = 409
    else:
        code = "orchestration_simulation_invalid"
        status = 400
    return jsonify({"error": code, "message": str(error)}), status


def _require_permission(orchestration_id, permission):
    orchestration = simulator.get_orchestration(orchestration_id)
    user = current_user()
    if user is None or not has_orchestration_permission(
        user,
        orchestration.group_id,
        permission,
    ):
        return None, make_error_response(
            "forbidden",
            "You do not have permission to perform this orchestration action.",
            403,
        )
    return orchestration, None


@orchestrations_bp.route("/<int:orchestration_id>/simulate", methods=["POST"])
def simulate_orchestration(orchestration_id):
    orchestration, error = _require_permission(orchestration_id, SIMULATE)
    if error:
        return error

    payload, error = validate_body(OrchestrationSimulationSchema)
    if error:
        return error

    if payload.normalized_event is not None:
        event = simulator.prepare_normalized_event(payload.normalized_event)
        selected_normalizer = "normalized"
        normalized_event_count = 1
    else:
        selected_normalizer, event, normalized_event_count = (
            simulator.normalize_simulation_payload(
                source=payload.source,
                payload=payload.payload,
                headers=payload.headers,
                event_index=payload.event_index,
            )
        )

    result = simulator.simulate_event(
        orchestration.id,
        event,
        version_id=payload.version_id,
        compare_with_active=payload.compare_with_active,
        selected_normalizer=selected_normalizer,
        normalized_event_count=normalized_event_count,
    )

    write_audit(
        "event_orchestration.simulate",
        object_type="event_orchestration",
        object_id=orchestration.id,
        group_id=orchestration.group_id,
        data={
            "version_id": result.get("version_id"),
            "source": event.get("source"),
            "compare_with_active": payload.compare_with_active,
        },
    )
    return jsonify(result)


@orchestrations_bp.route("/<int:orchestration_id>/replay", methods=["POST"])
def replay_orchestration(orchestration_id):
    orchestration, error = _require_permission(orchestration_id, REPLAY)
    if error:
        return error

    payload, error = validate_body(OrchestrationReplaySchema)
    if error:
        return error

    result = simulator.replay_events(
        orchestration.id,
        alert_ids=payload.alert_ids,
        execution_ids=payload.execution_ids,
        version_id=payload.version_id,
        compare_with_active=payload.compare_with_active,
    )
    write_audit(
        "event_orchestration.replay",
        object_type="event_orchestration",
        object_id=orchestration.id,
        group_id=orchestration.group_id,
        data={
            "alert_ids": payload.alert_ids,
            "execution_ids": payload.execution_ids,
            "version_id": payload.version_id,
            "count": result.get("count"),
        },
    )
    return jsonify(result)


@orchestrations_bp.route("/<int:orchestration_id>/executions", methods=["GET"])
def list_orchestration_executions(orchestration_id):
    orchestration, error = _require_permission(
        orchestration_id,
        VIEW_EXECUTIONS,
    )
    if error:
        return error

    limit = request.args.get("limit", default=50, type=int)
    include_trace = request.args.get("include_trace") == "1"
    return jsonify(
        simulator.list_executions(
            orchestration.id,
            limit=limit,
            include_trace=include_trace,
        )
    )


@orchestrations_bp.route("/<int:orchestration_id>/shadow-metrics", methods=["GET"])
def get_orchestration_shadow_metrics(orchestration_id):
    orchestration, error = _require_permission(
        orchestration_id,
        VIEW_EXECUTIONS,
    )
    if error:
        return error

    limit = request.args.get("limit", default=None, type=int)
    return jsonify(
        simulator.shadow_metrics(
            orchestration.id,
            limit=limit,
        )
    )
