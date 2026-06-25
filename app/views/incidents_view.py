from flask import Blueprint, jsonify, request

from app.modules.db.models import Alert
from app.modules.db import alerts_repo
from app.modules.db import incidents_repo
from app.services.audit import write_audit
from app.services.incidents.stakeholders import (
    create_incident_stakeholder,
    remove_incident_stakeholder,
)
from app.services.incidents.priorities import reset_incident_priority, set_incident_priority
from app.services.incidents.responders import create_incident_responder, set_incident_responder_status
from app.services.rbac import (
    get_allowed_team_ids,
    require_team_read,
    require_team_respond,
)
from app.services.serializers import (
    serialize_alert_event,
    serialize_incident,
    serialize_incident_alert,
    serialize_incident_priority,
    serialize_incident_responder,
    serialize_incident_stakeholder,
)
from app.services.validation import (
    make_error_response,
    safe_exception_response,
    validate_body,
)
from app.api.schemas.incidents import (
    IncidentResponderCreateSchema,
    IncidentResponderUpdateSchema,
)


incidents_bp = Blueprint("incidents_api", __name__)


def _request_user():
    return getattr(request, "current_user", None)


def _request_user_id():
    user = _request_user()
    return getattr(user, "id", None)


def _get_query_values(name, cast=None):
    values = request.args.getlist(name)

    if not values:
        value = request.args.get(name)
        values = [value] if value else []

    result = []

    for value in values:
        if value is None or value == "":
            continue

        try:
            result.append(cast(value) if cast else value)
        except (TypeError, ValueError):
            continue

    return result


def _get_incident_or_error(incident_id, *, respond=False):
    group = alerts_repo.get_alert_group(incident_id)

    if not group:
        return None, make_error_response(
            "not_found",
            "Incident not found",
            404,
        )

    if group.team_id:
        error = (
            require_team_respond(group.team_id)
            if respond
            else require_team_read(group.team_id)
        )

        if error:
            return None, error

    return group, None


@incidents_bp.route("", methods=["GET"])
def list_incidents():
    team_id = request.args.get("team_id", type=int)

    if team_id:
        error = require_team_read(team_id)
        if error:
            return error

        team_ids = None
    else:
        team_ids = get_allowed_team_ids()

    page = alerts_repo.paginate_alert_groups(
        team_id=team_id,
        team_ids=team_ids,
        status=_get_query_values("status"),
        source=_get_query_values("source"),
        severity=_get_query_values("severity"),
        priority=_get_query_values("priority"),
        service_id=_get_query_values("service_id", int),
        service_slug=request.args.get("service_slug"),
        service_status=request.args.get("service_status"),
        service_criticality=request.args.get("service_criticality"),
        search=request.args.get("search"),
        page=request.args.get("page", 1, type=int),
        page_size=request.args.get("page_size", 25, type=int),
        sort=request.args.get("sort", "activity"),
        order=request.args.get("order", "desc"),
        include_merged=request.args.get("include_merged") == "1",
    )

    user = _request_user()

    return jsonify({
        "items": [
            serialize_incident(group, current_user=user)
            for group in page["items"]
        ],
        "pagination": page["pagination"],
        "summary": page["summary"],
        "sort": page["sort"],
    })


@incidents_bp.route("/<int:incident_id>", methods=["GET"])
def get_incident(incident_id):
    group, error = _get_incident_or_error(incident_id)

    if error:
        return error

    events = alerts_repo.list_group_events(group.id)

    payload = serialize_incident(
        group,
        current_user=_request_user(),
        include_details=True,
    )

    payload["alerts"] = [
        serialize_incident_alert(alert)
        for alert in group.alerts.order_by(Alert.first_seen_at.asc(), Alert.id.asc())
    ]

    payload["events"] = [
        serialize_alert_event(event)
        for event in events
    ]

    payload["responders"] = [
        serialize_incident_responder(responder)
        for responder in incidents_repo.list_incident_responders(group.id)
    ]

    payload["stakeholders"] = [
        serialize_incident_stakeholder(stakeholder)
        for stakeholder in incidents_repo.list_incident_stakeholders(group.id)
    ]

    return jsonify(payload)


@incidents_bp.route("/priorities", methods=["GET"])
def list_incident_priorities():
    include_disabled = request.args.get("include_disabled") == "1"

    return jsonify([
        serialize_incident_priority(priority)
        for priority in incidents_repo.list_priorities(
            include_disabled=include_disabled,
        )
    ])


@incidents_bp.route("/<int:incident_id>/priority", methods=["PUT"])
def update_incident_priority(incident_id):
    group, error = _get_incident_or_error(incident_id, respond=True)

    if error:
        return error

    payload = request.get_json(silent=True) or {}

    try:
        group = set_incident_priority(
            group_id=group.id,
            priority=payload.get("priority"),
            user_id=_request_user_id(),
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="validation_error",
            message="Invalid incident priority request.",
            status_code=400,
        )
    except LookupError as exc:
        return safe_exception_response(
            exc,
            error="not_found",
            message="Incident priority target not found.",
            status_code=404,
        )

    write_audit(
        "incident.priority.update",
        object_type="incident",
        object_id=group.id,
        team_id=group.team_id,
        user_id=_request_user_id(),
        data={
            "priority": payload.get("priority"),
        },
    )

    return jsonify(
        serialize_incident(
            group,
            current_user=_request_user(),
            include_details=True,
        )
    )


@incidents_bp.route("/<int:incident_id>/priority", methods=["DELETE"])
def reset_incident_priority_override(incident_id):
    group, error = _get_incident_or_error(incident_id, respond=True)

    if error:
        return error

    try:
        group = reset_incident_priority(group_id=group.id)
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="validation_error",
            message="Incident priority could not be returned to automatic mode.",
            status_code=400,
        )
    except LookupError as exc:
        return safe_exception_response(
            exc,
            error="not_found",
            message="Incident priority target not found.",
            status_code=404,
        )

    write_audit(
        "incident.priority.reset",
        object_type="incident",
        object_id=group.id,
        team_id=group.team_id,
        user_id=_request_user_id(),
        data={
            "priority": group.priority_slug,
            "set_manually": False,
        },
    )

    return jsonify(serialize_incident(group, current_user=_request_user(), include_details=True))


@incidents_bp.route("/<int:incident_id>/responders", methods=["GET"])
def list_incident_responders(incident_id):
    group, error = _get_incident_or_error(incident_id)

    if error:
        return error

    responders = incidents_repo.list_incident_responders(group.id)

    return jsonify([
        serialize_incident_responder(responder)
        for responder in responders
    ])


@incidents_bp.route("/<int:incident_id>/responders", methods=["POST"])
def add_incident_responder(incident_id):
    group, error = _get_incident_or_error(incident_id, respond=True)

    if error:
        return error

    payload, error = validate_body(IncidentResponderCreateSchema)
    if error:
        return error

    try:
        responder = create_incident_responder(
            group_id=group.id,
            payload=payload.model_dump(),
            user_id=_request_user_id(),
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="validation_error",
            message="Invalid incident responder request.",
            status_code=400,
        )
    except LookupError as exc:
        return safe_exception_response(
            exc,
            error="not_found",
            message="Incident responder target not found.",
            status_code=404,
        )

    write_audit(
        "incident.responder.add",
        object_type="incident",
        object_id=group.id,
        team_id=group.team_id,
        user_id=_request_user_id(),
        data={
            "responder_id": responder.id,
            "target_type": responder.target_type,
            "target_user_id": responder.target_user_id,
            "target_team_id": responder.target_team_id,
            "target_rotation_id": responder.target_rotation_id,
            "target_escalation_policy_id": (
                responder.target_escalation_policy_id
            ),
            "status": responder.status,
        },
    )

    return jsonify(serialize_incident_responder(responder)), 201


@incidents_bp.route(
    "/<int:incident_id>/responders/<int:responder_id>",
    methods=["PUT"],
)
def update_incident_responder(incident_id, responder_id):
    group = alerts_repo.get_alert_group(incident_id)
    if not group:
        return make_error_response(
            "not_found",
            "Incident not found",
            404,
        )

    payload, error = validate_body(IncidentResponderUpdateSchema)
    if error:
        return error

    try:
        responder = set_incident_responder_status(
            group_id=group.id,
            responder_id=responder_id,
            status=payload.status,
            response_message=payload.response_message,
            user_id=_request_user_id(),
            user=_request_user(),
        )
    except PermissionError as exc:
        return safe_exception_response(
            exc,
            error="access_denied",
            message="You do not have permission to update this responder.",
            status_code=403,
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="validation_error",
            message="Invalid incident responder update request.",
            status_code=400,
        )
    except LookupError as exc:
        return safe_exception_response(
            exc,
            error="not_found",
            message="Incident responder not found.",
            status_code=404,
        )

    write_audit(
        "incident.responder.update",
        object_type="incident",
        object_id=group.id,
        team_id=group.team_id,
        user_id=_request_user_id(),
        data={
            "responder_id": responder.id,
            "status": responder.status,
        },
    )

    return jsonify(serialize_incident_responder(responder))


@incidents_bp.route("/<int:incident_id>/stakeholders", methods=["GET"])
def list_incident_stakeholders(incident_id):
    group, error = _get_incident_or_error(incident_id)

    if error:
        return error

    return jsonify([
        serialize_incident_stakeholder(stakeholder)
        for stakeholder in incidents_repo.list_incident_stakeholders(group.id)
    ])


@incidents_bp.route("/<int:incident_id>/stakeholders", methods=["POST"])
def add_incident_stakeholder(incident_id):
    group, error = _get_incident_or_error(incident_id, respond=True)

    if error:
        return error

    payload = request.get_json(silent=True) or {}

    try:
        stakeholder = create_incident_stakeholder(
            group_id=group.id,
            payload=payload,
            user_id=_request_user_id(),
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="validation_error",
            message="Invalid incident stakeholder request.",
            status_code=400,
        )
    except LookupError as exc:
        return safe_exception_response(
            exc,
            error="not_found",
            message="Incident stakeholder target not found.",
            status_code=404,
        )

    write_audit(
        "incident.stakeholder.add",
        object_type="incident",
        object_id=group.id,
        team_id=group.team_id,
        user_id=_request_user_id(),
        data={
            "stakeholder_id": stakeholder.id,
        },
    )

    return jsonify(serialize_incident_stakeholder(stakeholder)), 201


@incidents_bp.route(
    "/<int:incident_id>/stakeholders/<int:stakeholder_id>",
    methods=["DELETE"],
)
def delete_incident_stakeholder(incident_id, stakeholder_id):
    group, error = _get_incident_or_error(incident_id, respond=True)

    if error:
        return error

    try:
        stakeholder = remove_incident_stakeholder(
            group_id=group.id,
            stakeholder_id=stakeholder_id,
            user_id=_request_user_id(),
        )
    except LookupError as exc:
        return safe_exception_response(
            exc,
            error="not_found",
            message="Incident stakeholder not found.",
            status_code=404,
        )

    write_audit(
        "incident.stakeholder.remove",
        object_type="incident",
        object_id=group.id,
        team_id=group.team_id,
        user_id=_request_user_id(),
        data={
            "stakeholder_id": stakeholder.id,
        },
    )

    return jsonify({
        "deleted": True,
        "id": stakeholder.id,
    })
