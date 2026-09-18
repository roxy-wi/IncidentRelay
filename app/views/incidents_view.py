from flask import Blueprint, jsonify, request

from app.api.schemas.incidents import (
    IncidentAssignmentSchema,
    IncidentCreateSchema,
    IncidentLinkSchema,
    IncidentTransitionSchema,
    IncidentUpdateSchema,
)
from app.modules.db import incident_core_repo, incidents_repo
from app.services.incidents.core import (
    IncidentConflictError,
    IncidentValidationError,
    assign_incident,
    create_incident,
    link_alert_group,
    transition_incident,
    unlink_alert_group,
    update_incident,
)
from app.services.rbac import (
    can_access_team_or_group_resource,
    can_respond_team,
    get_allowed_team_ids,
    is_admin_user,
    require_team_read,
    require_team_respond,
)
from app.services.serializers.alerts import serialize_incident_priority
from app.services.serializers.incidents import (
    serialize_incident,
    serialize_incident_event,
    serialize_incident_link,
)
from app.services.validation import make_error_response, validate_body


incidents_bp = Blueprint("incidents_api", __name__)


def _request_user():
    return getattr(request, "current_user", None)


def _request_user_id():
    return getattr(_request_user(), "id", None)


def _can_create_incident(user, team_id):
    if not user:
        return False
    if is_admin_user(user):
        return True
    return can_respond_team(user, team_id) or can_access_team_or_group_resource(
        user,
        team_id,
        write_required=True,
    )


def _get_incident_or_error(incident_id, *, respond=False):
    incident = incident_core_repo.get_incident(incident_id)
    if not incident:
        return None, make_error_response("not_found", "Incident not found", 404)
    if incident.team_id:
        error = require_team_respond(incident.team_id) if respond else require_team_read(incident.team_id)
        if error:
            return None, error
    elif not is_admin_user(_request_user()):
        return None, make_error_response("forbidden", "Incident is outside your team scope", 403)
    return incident, None


def _service_error(exc):
    if isinstance(exc, IncidentConflictError):
        return make_error_response("conflict", str(exc), 409)
    return make_error_response("validation_error", str(exc), 400)


@incidents_bp.route("", methods=["GET"])
def list_incidents():
    team_id = request.args.get("team_id", type=int)
    statuses = [value for value in request.args.getlist("status") if value]
    if not statuses and request.args.get("status"):
        statuses = [request.args.get("status")]

    if team_id:
        error = require_team_read(team_id)
        if error:
            return error
        team_ids = [team_id]
    else:
        team_ids = get_allowed_team_ids()

    incidents = incident_core_repo.list_incidents(team_ids=team_ids, statuses=statuses)
    search = (request.args.get("search") or "").strip().lower()
    if search:
        incidents = [item for item in incidents if search in (item.title or "").lower()]

    page = max(request.args.get("page", 1, type=int), 1)
    page_size = min(max(request.args.get("page_size", 25, type=int), 1), 100)
    total = len(incidents)
    start = (page - 1) * page_size
    items = incidents[start:start + page_size]

    return jsonify({
        "items": [serialize_incident(item, current_user=_request_user()) for item in items],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size if total else 0,
        },
    })


@incidents_bp.route("", methods=["POST"])
def create_incident_view():
    payload, error = validate_body(IncidentCreateSchema)
    if error:
        return error
    if not _can_create_incident(_request_user(), payload.team_id):
        return make_error_response("forbidden", "Incident create permission is required for this team", 403)
    try:
        incident = create_incident(
            team_id=payload.team_id,
            service_id=payload.service_id,
            title=payload.title,
            description=payload.description,
            priority_slug=payload.priority,
            assignee_id=payload.assignee_id,
            user_id=_request_user_id(),
        )
    except (IncidentValidationError, IncidentConflictError) as exc:
        return _service_error(exc)
    return jsonify(serialize_incident(incident, current_user=_request_user(), include_details=True)), 201


@incidents_bp.route("/priorities", methods=["GET"])
def list_incident_priorities():
    include_disabled = request.args.get("include_disabled") == "1"
    return jsonify([
        serialize_incident_priority(priority)
        for priority in incidents_repo.list_priorities(include_disabled=include_disabled)
    ])


@incidents_bp.route("/<int:incident_id>", methods=["GET"])
def get_incident(incident_id):
    incident, error = _get_incident_or_error(incident_id)
    if error:
        return error
    payload = serialize_incident(incident, current_user=_request_user(), include_details=True)
    payload["alert_groups"] = [serialize_incident_link(link) for link in incident_core_repo.list_active_links(incident.id)]
    payload["events"] = [serialize_incident_event(event) for event in incident_core_repo.list_events(incident.id)]
    return jsonify(payload)


@incidents_bp.route("/<int:incident_id>", methods=["PATCH"])
def update_incident_view(incident_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    payload, error = validate_body(IncidentUpdateSchema)
    if error:
        return error
    try:
        incident = update_incident(
            incident.id,
            expected_version=payload.row_version,
            user_id=_request_user_id(),
            title=payload.title,
            description=payload.description,
            service_id=payload.service_id,
            priority_slug=payload.priority,
        )
    except (IncidentValidationError, IncidentConflictError) as exc:
        return _service_error(exc)
    return jsonify(serialize_incident(incident, current_user=_request_user(), include_details=True))


@incidents_bp.route("/<int:incident_id>/status", methods=["POST"])
def transition_incident_view(incident_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    payload, error = validate_body(IncidentTransitionSchema)
    if error:
        return error
    try:
        incident = transition_incident(
            incident.id,
            payload.status,
            expected_version=payload.row_version,
            user_id=_request_user_id(),
        )
    except (IncidentValidationError, IncidentConflictError) as exc:
        return _service_error(exc)
    return jsonify(serialize_incident(incident, current_user=_request_user(), include_details=True))


@incidents_bp.route("/<int:incident_id>/close", methods=["POST"])
def close_incident_view(incident_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    row_version = payload.get("row_version")
    if not isinstance(row_version, int) or row_version < 1:
        return make_error_response("validation_error", "row_version is required", 400)
    try:
        incident = transition_incident(incident.id, "closed", expected_version=row_version, user_id=_request_user_id())
    except (IncidentValidationError, IncidentConflictError) as exc:
        return _service_error(exc)
    return jsonify(serialize_incident(incident, current_user=_request_user(), include_details=True))


@incidents_bp.route("/<int:incident_id>/reopen", methods=["POST"])
def reopen_incident_view(incident_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    row_version = payload.get("row_version")
    if not isinstance(row_version, int) or row_version < 1:
        return make_error_response("validation_error", "row_version is required", 400)
    try:
        incident = transition_incident(incident.id, "investigating", expected_version=row_version, user_id=_request_user_id())
    except (IncidentValidationError, IncidentConflictError) as exc:
        return _service_error(exc)
    return jsonify(serialize_incident(incident, current_user=_request_user(), include_details=True))


@incidents_bp.route("/<int:incident_id>/assignee", methods=["PUT"])
def assign_incident_view(incident_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    payload, error = validate_body(IncidentAssignmentSchema)
    if error:
        return error
    try:
        incident = assign_incident(
            incident.id,
            assignee_id=payload.assignee_id,
            expected_version=payload.row_version,
            user_id=_request_user_id(),
        )
    except (IncidentValidationError, IncidentConflictError) as exc:
        return _service_error(exc)
    return jsonify(serialize_incident(incident, current_user=_request_user(), include_details=True))


@incidents_bp.route("/<int:incident_id>/assignee/me", methods=["PUT"])
def assign_incident_to_me_view(incident_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    payload = request.get_json(silent=True) or {}
    row_version = payload.get("row_version")
    if not isinstance(row_version, int) or row_version < 1:
        return make_error_response("validation_error", "row_version is required", 400)
    if not _request_user_id():
        return make_error_response("forbidden", "Authenticated user is required", 403)
    try:
        incident = assign_incident(
            incident.id,
            assignee_id=_request_user_id(),
            expected_version=row_version,
            user_id=_request_user_id(),
        )
    except (IncidentValidationError, IncidentConflictError) as exc:
        return _service_error(exc)
    return jsonify(serialize_incident(incident, current_user=_request_user(), include_details=True))


@incidents_bp.route("/<int:incident_id>/alert-groups", methods=["GET"])
def list_incident_alert_groups(incident_id):
    incident, error = _get_incident_or_error(incident_id)
    if error:
        return error
    return jsonify([serialize_incident_link(link) for link in incident_core_repo.list_active_links(incident.id)])


@incidents_bp.route("/<int:incident_id>/alert-groups", methods=["POST"])
def link_incident_alert_group(incident_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    payload, error = validate_body(IncidentLinkSchema)
    if error:
        return error
    try:
        link = link_alert_group(
            incident.id,
            payload.alert_group_id,
            relation_type=payload.relation_type,
            user_id=_request_user_id(),
        )
    except (IncidentValidationError, IncidentConflictError) as exc:
        return _service_error(exc)
    return jsonify(serialize_incident_link(link)), 201


@incidents_bp.route("/<int:incident_id>/alert-groups/<int:group_id>", methods=["DELETE"])
def unlink_incident_alert_group(incident_id, group_id):
    incident, error = _get_incident_or_error(incident_id, respond=True)
    if error:
        return error
    try:
        link = unlink_alert_group(incident.id, group_id, user_id=_request_user_id())
    except (IncidentValidationError, IncidentConflictError) as exc:
        return _service_error(exc)
    if not link:
        return make_error_response("not_found", "Active Incident/AlertGroup link not found", 404)
    return jsonify({"unlinked": True, "link": serialize_incident_link(link)})


@incidents_bp.route("/<int:incident_id>/events", methods=["GET"])
def list_incident_events(incident_id):
    incident, error = _get_incident_or_error(incident_id)
    if error:
        return error
    return jsonify([serialize_incident_event(event) for event in incident_core_repo.list_events(incident.id)])
