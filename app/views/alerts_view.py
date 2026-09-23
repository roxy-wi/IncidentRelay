from peewee import DoesNotExist
from flask import Blueprint, jsonify, request

from app.api.schemas.alerts import (
    AlertActivityQuerySchema,
    AlertDetailQuerySchema,
    AlertEventListQuerySchema,
    AlertGroupCreateSchema,
    AlertListQuerySchema,
    AlertShelveSchema,
)
from app.modules.db import alerts_repo, incidents_repo, notifications_repo
from app.services.alerts.actions import acknowledge_alert, resolve_alert
from app.services.alerts.assignment import set_alert_group_assignee
from app.services.alerts.shelving import shelve_alert_group, unshelve_alert_group
from app.services.audit import write_audit
from app.services.rbac import (
    can_access_team_or_group_resource,
    can_respond_team,
    get_allowed_team_ids,
    is_admin_user,
    require_team_read,
    require_team_respond,
)
from app.services.serializers.alerts import (
    serialize_alert_activity_event,
    serialize_alert_event,
    serialize_alert_comment,
    serialize_alert_group,
    serialize_incident_priority,
    serialize_incident_responder,
    serialize_alert_explain_trace,
)
from app.services.serializers.incidents import serialize_incident, serialize_incident_stakeholder
from app.services.alerts.alert_comments import (
    create_group_comment,
    create_child_alert_comment,
    update_group_comment,
    delete_group_comment,
)
from app.services.incidents.stakeholders import (
    create_incident_stakeholder,
    remove_incident_stakeholder,
)
from app.services.incidents.manual import create_manual_alert_group
from app.services.incidents.core import (
    IncidentConflictError,
    IncidentValidationError,
    create_incident_from_alert_group,
)
from app.api.schemas.incidents import (
    IncidentFromAlertGroupSchema,
    IncidentResponderCreateSchema,
    IncidentResponderUpdateSchema,
)
from app.services.incidents.priorities import reset_incident_priority, set_incident_priority
from app.services.incidents.responders import (
    create_incident_responder,
    set_incident_responder_status,
)
from app.services.validation import (
    make_error_response,
    safe_exception_response,
    validate_body,
    validate_query,
)

alerts_bp = Blueprint("alerts_api", __name__)


ALERT_GROUP_ACTIVITY_EVENT_TYPES = frozenset({
    "created",
    "manual_created",
    "acknowledged",
    "resolved",
    "reopened",
    "alert_group_shelved",
    "alert_group_unshelved",
    "alert_group_shelve_expired",
    "assignee_changed",
    "priority_changed",
    "priority_auto_updated",
    "priority_auto_recalculated",
    "silenced",
    "unsilenced",
    "maintenance_applied",
    "maintenance_released",
    "escalated",
    "escalation_stopped",
    "merged",
    "merge_target_updated",
    "commented",
    "comment_updated",
    "comment_deleted",
    "correlation_detected",
    "correlation_deactivated",
    "routing_error",
})


def _request_user():
    return getattr(request, "current_user", None)


def _request_user_id():
    return getattr(_request_user(), "id", None)


def _can_create_manual_alert_group(user, team_id):
    if not user:
        return False
    if is_admin_user(user):
        return True
    return can_respond_team(user, team_id) or can_access_team_or_group_resource(
        user, team_id, write_required=True
    )


def _not_found(message="Alert group not found."):
    return make_error_response(
        error="not_found",
        message=message,
        status_code=404,
    )


def _get_alert_group_or_404(group_id):
    try:
        group = alerts_repo.get_alert_group(group_id)
    except (DoesNotExist, TypeError, ValueError):
        return None, _not_found()

    if not group:
        return None, _not_found()

    return group, None


def _require_alert_group_read(group_id):
    group, error = _get_alert_group_or_404(group_id)
    if error:
        return None, error

    if group.team_id:
        error = require_team_read(group.team_id)
        if error:
            return None, error

    return group, None


def _require_alert_group_respond(group_id):
    group, error = _get_alert_group_or_404(group_id)
    if error:
        return None, error

    if group.team_id:
        error = require_team_respond(group.team_id)
        if error:
            return None, error

    return group, None


@alerts_bp.route("", methods=["GET"])
def list_alerts():
    """Return alert groups with backend pagination, filters and sorting."""
    payload, error = validate_query(AlertListQuerySchema)
    if error:
        return error

    if payload.team_id:
        error = require_team_read(payload.team_id)
        if error:
            return error
        team_ids = None
    else:
        team_ids = get_allowed_team_ids()

    current_user = _request_user()
    assigned_to_user_id = (
        getattr(current_user, "id", None)
        if payload.assigned_to_me
        else None
    )

    page = alerts_repo.paginate_alert_groups(
        team_id=payload.team_id,
        team_ids=team_ids,
        status=payload.status,
        source=payload.source,
        severity=payload.severity,
        priority=payload.priority,
        service_id=payload.service_id,
        service_slug=payload.service_slug,
        service_status=payload.service_status,
        service_criticality=payload.service_criticality,
        search=payload.search,
        assigned_to_user_id=assigned_to_user_id,
        shelved=payload.shelved,
        page=payload.page,
        page_size=payload.page_size,
        sort=payload.sort,
        order=payload.order,
        include_merged=payload.include_merged,
    )

    return jsonify({
        "items": [
            serialize_alert_group(
                group,
                current_user=current_user,
            )
            for group in page["items"]
        ],
        "pagination": page["pagination"],
        "summary": page["summary"],
        "sort": page["sort"],
    })


@alerts_bp.route("", methods=["POST"])
def create_alert_group():
    """Create one explicit manual AlertGroup and one child Alert atomically."""
    payload, error = validate_body(AlertGroupCreateSchema)
    if error:
        return error
    if not _can_create_manual_alert_group(_request_user(), payload.team_id):
        return make_error_response(
            "forbidden",
            "AlertGroup create permission is required for this team",
            403,
        )
    try:
        group = create_manual_alert_group(payload.model_dump(), user_id=_request_user_id())
    except LookupError as exc:
        return safe_exception_response(exc, error="not_found", message="Manual AlertGroup target not found.", status_code=404)
    except ValueError as exc:
        return safe_exception_response(exc, error="validation_error", message="Invalid manual AlertGroup request.", status_code=400)

    write_audit(
        "alert_group.manual.create",
        object_type="alert_group",
        object_id=group.id,
        team_id=group.team_id,
        user_id=_request_user_id(),
        data={"team_id": group.team_id, "service_id": group.service_id, "title": group.title},
    )
    return jsonify(serialize_alert_group(group, current_user=_request_user(), include_details=True)), 201


@alerts_bp.route("/activity", methods=["GET"])
def list_alert_group_activity():
    """Return recent meaningful activity across visible AlertGroups."""

    query, error = validate_query(AlertActivityQuerySchema)
    if error:
        return error

    if query.team_id:
        error = require_team_read(query.team_id)
        if error:
            return error
        team_ids = [query.team_id]
    else:
        team_ids = get_allowed_team_ids()

    activity = alerts_repo.list_recent_alert_group_activity(
        team_ids=team_ids,
        limit=query.limit,
        event_types=ALERT_GROUP_ACTIVITY_EVENT_TYPES,
    )

    return jsonify({
        "items": [
            serialize_alert_activity_event(
                item["event"],
                item["group"],
                item["user"],
            )
            for item in activity
        ]
    })


@alerts_bp.route("/priorities", methods=["GET"])
def list_alert_group_priorities():
    include_disabled = request.args.get("include_disabled") == "1"
    return jsonify([
        serialize_incident_priority(priority)
        for priority in incidents_repo.list_priorities(include_disabled=include_disabled)
    ])


@alerts_bp.route("/<int:alert_id>", methods=["GET"])
def get_alert(alert_id):
    """Return a single alert group with child alerts, events and delivery records."""
    group, error = _require_alert_group_read(alert_id)
    if error:
        return error

    query, error = validate_query(AlertDetailQuerySchema)
    if error:
        return error

    alerts = alerts_repo.list_alerts_for_group(group.id)
    notifications = notifications_repo.list_notifications_for_group(group.id)
    events_page = None

    if query.events_page is not None or query.events_page_size is not None:
        events_page = alerts_repo.paginate_group_events(
            group.id,
            page=query.events_page or 1,
            page_size=query.events_page_size or 50,
        )
        events = events_page["items"]
    else:
        events = alerts_repo.list_group_events(group.id)

    payload = serialize_alert_group(
        group,
        include_payload=True,
        include_details=True,
        alerts=alerts,
        events=events,
        notifications=notifications,
        current_user=_request_user(),
    )
    payload["stakeholders"] = [
        serialize_incident_stakeholder(item)
        for item in incidents_repo.list_incident_stakeholders(group.id)
    ]
    if events_page is not None:
        payload["events_pagination"] = events_page["pagination"]
    return jsonify(payload)


@alerts_bp.route("/<int:alert_id>/acknowledge", methods=["POST"])
def ack_alert(alert_id):
    """Acknowledge an alert group."""
    group_before, error = _require_alert_group_respond(alert_id)
    if error:
        return error

    data = request.get_json(silent=True) or {}
    user_id = getattr(_request_user(), "id", None)
    audit_data = {key: value for key, value in data.items() if key != "user_id"}

    group = acknowledge_alert(alert_id, user_id=user_id)
    write_audit(
        "alert_group.ack",
        object_type="alert_group",
        object_id=group.id,
        team_id=group_before.team.id if group_before.team else None,
        user_id=user_id,
        data=audit_data,
    )

    return jsonify(
        serialize_alert_group(
            group,
            current_user=_request_user(),
        )
    )


@alerts_bp.route("/<int:alert_id>/resolve", methods=["POST"])
def resolve_alert_view(alert_id):
    """Resolve an alert group."""
    group_before, error = _require_alert_group_respond(alert_id)
    if error:
        return error

    data = request.get_json(silent=True) or {}
    user_id = getattr(_request_user(), "id", None)
    audit_data = {key: value for key, value in data.items() if key != "user_id"}

    group = resolve_alert(alert_id, user_id=user_id)
    write_audit(
        "alert_group.resolve",
        object_type="alert_group",
        object_id=group.id,
        team_id=group_before.team.id if group_before.team else None,
        user_id=user_id,
        data=audit_data,
    )

    return jsonify(
        serialize_alert_group(
            group,
            current_user=_request_user(),
        )
    )


@alerts_bp.route("/<int:alert_id>/assignee", methods=["PUT"])
def update_alert_group_assignee(alert_id):
    group, error = _require_alert_group_respond(alert_id)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        group = set_alert_group_assignee(
            group,
            data.get("assignee_id"),
            actor_user_id=_request_user_id(),
        )
    except ValueError as exc:
        return safe_exception_response(exc, error="validation_error", message="Invalid AlertGroup assignee.", status_code=400)
    return jsonify(serialize_alert_group(group, current_user=_request_user()))


@alerts_bp.route("/<int:alert_id>/assignee/me", methods=["PUT"])
def assign_alert_group_to_me(alert_id):
    group, error = _require_alert_group_respond(alert_id)
    if error:
        return error
    if not _request_user_id():
        return make_error_response("forbidden", "Authenticated user is required", 403)
    try:
        group = set_alert_group_assignee(
            group,
            _request_user_id(),
            actor_user_id=_request_user_id(),
        )
    except ValueError as exc:
        return safe_exception_response(exc, error="validation_error", message="Invalid AlertGroup assignee.", status_code=400)
    return jsonify(serialize_alert_group(group, current_user=_request_user()))


@alerts_bp.route("/<int:alert_id>/create-incident", methods=["POST"])
def create_incident_from_alert_group_view(alert_id):
    group, error = _require_alert_group_respond(alert_id)
    if error:
        return error
    payload, error = validate_body(IncidentFromAlertGroupSchema)
    if error:
        return error
    try:
        incident = create_incident_from_alert_group(
            group.id,
            user_id=_request_user_id(),
            title=payload.title,
            description=payload.description,
            priority_slug=payload.priority,
            assignee_id=payload.assignee_id,
        )
    except IncidentConflictError as exc:
        return make_error_response("conflict", str(exc), 409)
    except IncidentValidationError as exc:
        return make_error_response("validation_error", str(exc), 400)
    return jsonify(serialize_incident(incident, current_user=_request_user(), include_details=True)), 201


@alerts_bp.route("/<int:alert_id>/shelve", methods=["POST"])
def shelve_alert_view(alert_id):
    """Temporarily shelve one AlertGroup without changing technical status."""
    group_before, error = _require_alert_group_respond(alert_id)
    if error:
        return error

    payload, error = validate_body(AlertShelveSchema)
    if error:
        return error

    user_id = getattr(_request_user(), "id", None)
    try:
        group, _shelf = shelve_alert_group(
            alert_id,
            user_id=user_id,
            duration_seconds=payload.duration_seconds,
            reason=payload.reason,
            source="ui",
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="validation_error",
            message="Alert group could not be shelved.",
            status_code=400,
        )

    return jsonify(serialize_alert_group(group, current_user=_request_user()))


@alerts_bp.route("/<int:alert_id>/unshelve", methods=["POST"])
def unshelve_alert_view(alert_id):
    """End the current AlertGroup shelf and restart current-state delivery."""
    _group_before, error = _require_alert_group_respond(alert_id)
    if error:
        return error

    user_id = getattr(_request_user(), "id", None)
    group, _shelf = unshelve_alert_group(
        alert_id,
        user_id=user_id,
        source="ui",
    )
    return jsonify(serialize_alert_group(group, current_user=_request_user()))


@alerts_bp.route("/<int:alert_id>/events", methods=["GET"])
def list_alert_events(alert_id):
    """Return alert group events."""
    group, error = _require_alert_group_read(alert_id)
    if error:
        return error

    # Preserve the pre-2.2 array response for API clients that do not request
    # pagination explicitly. The web UI uses paginated mode.
    if "page" not in request.args and "page_size" not in request.args:
        return jsonify([
            serialize_alert_event(event)
            for event in alerts_repo.list_group_events(group.id)
        ])

    query, error = validate_query(AlertEventListQuerySchema)
    if error:
        return error

    page = alerts_repo.paginate_group_events(
        group.id,
        page=query.page,
        page_size=query.page_size,
    )
    return jsonify({
        "items": [serialize_alert_event(event) for event in page["items"]],
        "pagination": page["pagination"],
    })


@alerts_bp.route("/<int:target_group_id>/merge", methods=["POST"])
def merge_alert_groups_view(target_group_id):
    """Merge selected alert groups into one group."""
    data = request.get_json(silent=True) or {}
    source_group_ids = data.get("source_group_ids") or []
    reason = data.get("reason")

    if not source_group_ids:
        return make_error_response(
            error="validation_error",
            message="source_group_ids is required.",
            status_code=400,
        )

    target, error = _require_alert_group_respond(target_group_id)
    if error:
        return error

    for source_id in source_group_ids:
        source, error = _require_alert_group_respond(source_id)
        if error:
            return error

        if target.team_id != source.team_id:
            return make_error_response(
                error="validation_error",
                message="Alert groups from different teams cannot be merged.",
                status_code=400,
            )

    user = _request_user()
    user_id = getattr(user, "id", None)

    group = alerts_repo.merge_alert_groups(
        target_group_id=target_group_id,
        source_group_ids=source_group_ids,
        user_id=user_id,
        reason=reason,
    )

    write_audit(
        "alert_group.merge",
        object_type="alert_group",
        object_id=group.id,
        team_id=group.team.id if group.team else None,
        user_id=user_id,
        data={
            "target_group_id": target_group_id,
            "source_group_ids": source_group_ids,
            "reason": reason,
        },
    )

    return jsonify(
        serialize_alert_group(
            group,
            current_user=user,
        )
    )


@alerts_bp.route("/<int:alert_id>/comments", methods=["GET"])
def list_alert_group_comments(alert_id):
    group, error = _require_alert_group_read(alert_id)
    if error:
        return error

    comments = alerts_repo.list_group_comments(group.id)
    return jsonify([serialize_alert_comment(comment) for comment in comments])


@alerts_bp.route("/<int:alert_id>/comments", methods=["POST"])
def add_alert_group_comment(alert_id):
    group, error = _require_alert_group_respond(alert_id)
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    user = _request_user()

    try:
        comment = create_group_comment(
            group_id=group.id,
            body=payload.get("body"),
            user_id=getattr(user, "id", None),
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="validation_error",
            message="Invalid alert group comment request.",
            status_code=400,
        )
    except LookupError as exc:
        return safe_exception_response(
            exc,
            error="not_found",
            message="Alert group comment target not found.",
            status_code=404,
        )

    write_audit(
        "alert_group.comment",
        object_type="alert_group",
        object_id=group.id,
        team_id=group.team.id if group.team else None,
        user_id=getattr(user, "id", None),
        data={"comment_id": comment.id},
    )

    return jsonify(serialize_alert_comment(comment)), 201


@alerts_bp.route("/<int:group_id>/alerts/<int:child_alert_id>/comments", methods=["GET"])
def list_child_alert_comments(group_id, child_alert_id):
    group, error = _require_alert_group_read(group_id)
    if error:
        return error

    alert = alerts_repo.get_alert(child_alert_id)
    if not alert or alert.group_id != group.id:
        return make_error_response(
            error="not_found",
            message="Alert not found in this group.",
            status_code=404,
        )

    comments = alerts_repo.list_alert_comments(alert.id)
    return jsonify([serialize_alert_comment(comment) for comment in comments])


@alerts_bp.route("/<int:group_id>/alerts/<int:child_alert_id>/comments", methods=["POST"])
def add_child_alert_comment(group_id, child_alert_id):
    group, error = _require_alert_group_respond(group_id)
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    user = _request_user()

    try:
        comment = create_child_alert_comment(
            group_id=group.id,
            alert_id=child_alert_id,
            body=payload.get("body"),
            user_id=getattr(user, "id", None),
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="validation_error",
            message="Invalid child alert comment request.",
            status_code=400,
        )
    except LookupError as exc:
        return safe_exception_response(
            exc,
            error="not_found",
            message="Child alert comment target not found.",
            status_code=404,
        )

    write_audit(
        "alert.comment",
        object_type="alert",
        object_id=child_alert_id,
        team_id=group.team.id if group.team else None,
        user_id=getattr(user, "id", None),
        data={
            "comment_id": comment.id,
            "group_id": group.id,
        },
    )

    return jsonify(serialize_alert_comment(comment)), 201


@alerts_bp.route("/<int:alert_id>/comments/<int:comment_id>", methods=["PUT"])
def update_alert_group_comment(alert_id, comment_id):
    group, error = _require_alert_group_respond(alert_id)
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    user = _request_user()
    user_id = getattr(user, "id", None)

    try:
        comment = update_group_comment(
            group_id=group.id,
            comment_id=comment_id,
            body=payload.get("body"),
            user_id=user_id,
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="validation_error",
            message="Invalid alert group comment update request.",
            status_code=400,
        )
    except LookupError as exc:
        return safe_exception_response(
            exc,
            error="not_found",
            message="Alert group comment not found.",
            status_code=404,
        )

    write_audit(
        "alert_group.comment.update",
        object_type="alert_group",
        object_id=group.id,
        team_id=group.team.id if group.team else None,
        user_id=user_id,
        data={"comment_id": comment.id},
    )

    return jsonify(serialize_alert_comment(comment))


@alerts_bp.route("/<int:alert_id>/comments/<int:comment_id>", methods=["DELETE"])
def delete_alert_group_comment(alert_id, comment_id):
    group, error = _require_alert_group_respond(alert_id)
    if error:
        return error

    user = _request_user()
    user_id = getattr(user, "id", None)

    try:
        comment = delete_group_comment(
            group_id=group.id,
            comment_id=comment_id,
            user_id=user_id,
        )
    except LookupError as exc:
        return safe_exception_response(
            exc,
            error="not_found",
            message="Alert group comment not found.",
            status_code=404,
        )

    write_audit(
        "alert_group.comment.delete",
        object_type="alert_group",
        object_id=group.id,
        team_id=group.team.id if group.team else None,
        user_id=user_id,
        data={"comment_id": comment.id},
    )

    return jsonify({
        "deleted": True,
        "id": comment.id,
    })


@alerts_bp.route("/<int:alert_id>/priority", methods=["PUT"])
def update_incident_priority(alert_id):
    group, error = _require_alert_group_respond(alert_id)
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    user = _request_user()

    try:
        group = set_incident_priority(
            group_id=group.id,
            priority=payload.get("priority"),
            user_id=getattr(user, "id", None),
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="validation_error",
            message="Invalid incident priority request.",
            status_code=400,
        )

    return jsonify(serialize_alert_group(group, current_user=user))


@alerts_bp.route("/<int:alert_id>/priority", methods=["DELETE"])
def reset_alert_group_priority(alert_id):
    group, error = _require_alert_group_respond(alert_id)
    if error:
        return error
    try:
        group = reset_incident_priority(group_id=group.id)
    except (ValueError, LookupError) as exc:
        return safe_exception_response(
            exc,
            error="validation_error",
            message="AlertGroup priority could not be returned to automatic mode.",
            status_code=400,
        )
    return jsonify(serialize_alert_group(group, current_user=_request_user()))


@alerts_bp.route("/<int:alert_id>/responders", methods=["GET"])
def list_incident_responders(alert_id):
    group, error = _require_alert_group_read(alert_id)
    if error:
        return error

    return jsonify([
        serialize_incident_responder(responder)
        for responder in alerts_repo.list_incident_responders(group.id)
    ])


@alerts_bp.route("/<int:alert_id>/responders", methods=["POST"])
def add_incident_responder(alert_id):
    group, error = _require_alert_group_respond(alert_id)
    if error:
        return error

    payload, error = validate_body(IncidentResponderCreateSchema)
    if error:
        return error

    user = _request_user()
    user_id = getattr(user, "id", None)

    try:
        responder = create_incident_responder(
            group_id=group.id,
            payload=payload.model_dump(),
            user_id=user_id,
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
            message="AlertGroup responder target not found.",
            status_code=404,
        )

    write_audit(
        "alert_group.responder.add",
        object_type="alert_group",
        object_id=group.id,
        team_id=group.team_id,
        user_id=user_id,
        data={
            "responder_id": responder.id,
            "target_type": responder.target_type,
            "target_user_id": responder.target_user_id,
            "target_team_id": responder.target_team_id,
            "target_rotation_id": responder.target_rotation_id,
            "target_escalation_policy_id": responder.target_escalation_policy_id,
            "status": responder.status,
        },
    )

    return jsonify(serialize_incident_responder(responder)), 201


@alerts_bp.route("/<int:alert_id>/responders/<int:responder_id>", methods=["PUT"])
def update_incident_responder(alert_id, responder_id):
    # A requested user may accept/decline their own request even when they are
    # only a team viewer, so read access is sufficient here. The responder
    # service performs the action-specific authorization check.
    group, error = _require_alert_group_read(alert_id)
    if error:
        return error

    payload, error = validate_body(IncidentResponderUpdateSchema)
    if error:
        return error

    user = _request_user()
    user_id = getattr(user, "id", None)

    try:
        responder = set_incident_responder_status(
            group_id=group.id,
            responder_id=responder_id,
            status=payload.status,
            response_message=payload.response_message,
            user_id=user_id,
            user=user,
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
            message="AlertGroup responder not found.",
            status_code=404,
        )

    write_audit(
        "alert_group.responder.update",
        object_type="alert_group",
        object_id=group.id,
        team_id=group.team_id,
        user_id=user_id,
        data={
            "responder_id": responder.id,
            "status": responder.status,
        },
    )

    return jsonify(serialize_incident_responder(responder))


@alerts_bp.route("/<int:alert_id>/stakeholders", methods=["GET"])
def list_incident_stakeholders(alert_id):
    group, error = _require_alert_group_read(alert_id)
    if error:
        return error

    return jsonify([
        serialize_incident_stakeholder(stakeholder)
        for stakeholder in alerts_repo.list_incident_stakeholders(group.id)
    ])


@alerts_bp.route("/<int:alert_id>/stakeholders", methods=["POST"])
def add_incident_stakeholder(alert_id):
    group, error = _require_alert_group_respond(alert_id)
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    user = _request_user()
    user_id = getattr(user, "id", None)

    try:
        stakeholder = create_incident_stakeholder(
            group_id=group.id,
            payload=payload,
            user_id=user_id,
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
            message="AlertGroup stakeholder target not found.",
            status_code=404,
        )

    write_audit(
        "alert_group.stakeholder.add",
        object_type="alert_group",
        object_id=group.id,
        team_id=group.team_id,
        user_id=user_id,
        data={"stakeholder_id": stakeholder.id},
    )

    return jsonify(serialize_incident_stakeholder(stakeholder)), 201


@alerts_bp.route(
    "/<int:alert_id>/stakeholders/<int:stakeholder_id>",
    methods=["DELETE"],
)
def delete_incident_stakeholder(alert_id, stakeholder_id):
    group, error = _require_alert_group_respond(alert_id)
    if error:
        return error

    user_id = _request_user_id()
    try:
        stakeholder = remove_incident_stakeholder(
            group_id=group.id,
            stakeholder_id=stakeholder_id,
            user_id=user_id,
        )
    except LookupError as exc:
        return safe_exception_response(
            exc,
            error="not_found",
            message="AlertGroup stakeholder not found.",
            status_code=404,
        )

    write_audit(
        "alert_group.stakeholder.remove",
        object_type="alert_group",
        object_id=group.id,
        team_id=group.team_id,
        user_id=user_id,
        data={"stakeholder_id": stakeholder.id},
    )

    return jsonify({"deleted": True, "id": stakeholder.id})


@alerts_bp.route("/<int:alert_id>/explain", methods=["GET"])
def list_alert_group_explain_traces(alert_id):
    group, error = _require_alert_group_read(alert_id)
    if error:
        return error

    traces = alerts_repo.list_alert_explain_traces_for_group(group.id)
    return jsonify([
        serialize_alert_explain_trace(trace)
        for trace in traces
    ])


@alerts_bp.route("/explain/<trace_id>", methods=["GET"])
def get_alert_explain_trace(trace_id):
    trace = alerts_repo.get_alert_explain_trace(trace_id)
    if not trace:
        return make_error_response(
            error="not_found",
            message="Alert explain trace not found.",
            status_code=404,
        )

    if trace.group_id:
        group, error = _require_alert_group_read(trace.group_id)
        if error:
            return error
    else:
        current_user = _request_user()
        if not getattr(current_user, "is_admin", False):
            return make_error_response(
                error="forbidden",
                message="Only administrators can read orphan explain traces.",
                status_code=403,
            )

    steps = alerts_repo.list_alert_explain_steps(trace)
    return jsonify(
        serialize_alert_explain_trace(
            trace,
            steps=steps,
        )
    )
