from flask import Blueprint, jsonify, request

from app.modules.db import alerts_repo, notifications_repo
from app.services.alerts.actions import acknowledge_alert, resolve_alert
from app.services.audit import write_audit
from app.services.rbac import get_allowed_team_ids, require_team_read, require_team_respond
from app.services.serializers import (
    serialize_alert_event,
    serialize_alert_comment,
    serialize_alert_group,
    serialize_incident_responder,
    serialize_incident_stakeholder,
)
from app.services.alerts.alert_comments import (
    create_group_comment,
    create_child_alert_comment,
    update_group_comment,
    delete_group_comment,
)
from app.services.incidents import (
    create_incident_responder,
    create_incident_stakeholder,
    set_incident_priority,
    set_incident_responder_status,
)

alerts_bp = Blueprint("alerts_api", __name__)


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


def _request_user():
    return getattr(request, "current_user", None)


@alerts_bp.route("", methods=["GET"])
def list_alerts():
    """Return alert groups with backend pagination, filters and sorting."""

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

    return jsonify({
        "items": [
            serialize_alert_group(
                group,
                current_user=getattr(request, "current_user", None),
            )
            for group in page["items"]
        ],
        "pagination": page["pagination"],
        "summary": page["summary"],
        "sort": page["sort"],
    })


@alerts_bp.route("/<int:alert_id>", methods=["GET"])
def get_alert(alert_id):
    """Return a single alert group with child alerts, events and delivery records."""

    group = alerts_repo.get_alert_group(alert_id)

    if group.team_id:
        error = require_team_read(group.team_id)
        if error:
            return error

    alerts = alerts_repo.list_alerts_for_group(group.id)
    events = alerts_repo.list_group_events(group.id)
    notifications = notifications_repo.list_notifications_for_group(group.id)

    return jsonify(
        serialize_alert_group(
            group,
            include_payload=True,
            include_details=True,
            alerts=alerts,
            events=events,
            notifications=notifications,
            current_user=getattr(request, "current_user", None),
        )
    )


@alerts_bp.route("/<int:alert_id>/ack", methods=["POST"])
def ack_alert(alert_id):
    """Acknowledge an alert group."""

    group_before = alerts_repo.get_alert_group(alert_id)

    if group_before.team_id:
        error = require_team_respond(group_before.team_id)
        if error:
            return error

    data = request.json or {}
    user_id = data.get("user_id") or getattr(
        getattr(request, "current_user", None),
        "id",
        None,
    )

    group = acknowledge_alert(alert_id, user_id=user_id)

    write_audit(
        "alert_group.ack",
        object_type="alert_group",
        object_id=group.id,
        team_id=group.team.id if group.team else None,
        user_id=user_id,
        data=data,
    )

    return jsonify(
        serialize_alert_group(
            group,
            current_user=getattr(request, "current_user", None),
        )
    )


@alerts_bp.route("/<int:alert_id>/resolve", methods=["POST"])
def resolve_alert_view(alert_id):
    """Resolve an alert group."""

    group_before = alerts_repo.get_alert_group(alert_id)

    if group_before.team_id:
        error = require_team_respond(group_before.team_id)
        if error:
            return error

    data = request.json or {}
    user_id = data.get("user_id") or getattr(
        getattr(request, "current_user", None),
        "id",
        None,
    )

    group = resolve_alert(alert_id, user_id=user_id)

    write_audit(
        "alert_group.resolve",
        object_type="alert_group",
        object_id=group.id,
        team_id=group.team.id if group.team else None,
        user_id=user_id,
        data=data,
    )

    return jsonify(
        serialize_alert_group(
            group,
            current_user=getattr(request, "current_user", None),
        )
    )


@alerts_bp.route("/<int:alert_id>/events", methods=["GET"])
def list_alert_events(alert_id):
    """Return alert group events."""

    group = alerts_repo.get_alert_group(alert_id)

    if group.team_id:
        error = require_team_read(group.team_id)
        if error:
            return error

    return jsonify([
        serialize_alert_event(event)
        for event in alerts_repo.list_group_events(group.id)
    ])


@alerts_bp.route("/merge", methods=["POST"])
def merge_alert_groups_view():
    """Merge selected alert groups into one group."""

    data = request.json or {}

    target_group_id = data.get("target_group_id")
    source_group_ids = data.get("source_group_ids") or []
    reason = data.get("reason")

    if not target_group_id:
        return jsonify({
            "error": "validation_error",
            "message": "target_group_id is required",
        }), 400

    if not source_group_ids:
        return jsonify({
            "error": "validation_error",
            "message": "source_group_ids is required",
        }), 400

    target = alerts_repo.get_alert_group(target_group_id)

    if target.team_id:
        error = require_team_respond(target.team_id)
        if error:
            return error

    for source_id in source_group_ids:
        source = alerts_repo.get_alert_group(source_id)

        if source.team_id:
            error = require_team_respond(source.team_id)
            if error:
                return error

    user = getattr(request, "current_user", None)
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
    group = alerts_repo.get_alert_group(alert_id)
    if not group:
        return jsonify({"error": "not_found", "message": "Alert group not found"}), 404

    if group.team_id:
        error = require_team_read(group.team_id)
        if error:
            return error

    comments = alerts_repo.list_group_comments(group.id)

    return jsonify([serialize_alert_comment(comment) for comment in comments])


@alerts_bp.route("/<int:alert_id>/comments", methods=["POST"])
def add_alert_group_comment(alert_id):
    group = alerts_repo.get_alert_group(alert_id)
    if not group:
        return jsonify({"error": "not_found", "message": "Alert group not found"}), 404

    if group.team_id:
        error = require_team_respond(group.team_id)
        if error:
            return error

    payload = request.get_json(silent=True) or {}
    user = getattr(request, "current_user", None)

    try:
        comment = create_group_comment(
            group_id=group.id,
            body=payload.get("body"),
            user_id=getattr(user, "id", None),
        )
    except ValueError as exc:
        return jsonify({
            "error": "validation_error",
            "message": str(exc),
        }), 400
    except LookupError as exc:
        return jsonify({
            "error": "not_found",
            "message": str(exc),
        }), 404

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
    group = alerts_repo.get_alert_group(group_id)
    if not group:
        return jsonify({"error": "not_found", "message": "Alert group not found"}), 404

    if group.team_id:
        error = require_team_read(group.team_id)
        if error:
            return error

    alert = alerts_repo.get_alert(child_alert_id)
    if not alert or alert.group_id != group.id:
        return jsonify({"error": "not_found", "message": "Alert not found in this group"}), 404

    comments = alerts_repo.list_alert_comments(alert.id)

    return jsonify([serialize_alert_comment(comment) for comment in comments])


@alerts_bp.route("/<int:group_id>/alerts/<int:child_alert_id>/comments", methods=["POST"])
def add_child_alert_comment(group_id, child_alert_id):
    group = alerts_repo.get_alert_group(group_id)
    if not group:
        return jsonify({"error": "not_found", "message": "Alert group not found"}), 404

    if group.team_id:
        error = require_team_respond(group.team_id)
        if error:
            return error

    payload = request.get_json(silent=True) or {}
    user = getattr(request, "current_user", None)

    try:
        comment = create_child_alert_comment(
            group_id=group.id,
            alert_id=child_alert_id,
            body=payload.get("body"),
            user_id=getattr(user, "id", None),
        )
    except ValueError as exc:
        return jsonify({
            "error": "validation_error",
            "message": str(exc),
        }), 400
    except LookupError as exc:
        return jsonify({
            "error": "not_found",
            "message": str(exc),
        }), 404

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
    group = alerts_repo.get_alert_group(alert_id)
    if not group:
        return jsonify({
            "error": "not_found",
            "message": "Alert group not found",
        }), 404

    if group.team_id:
        error = require_team_respond(group.team_id)
        if error:
            return error

    payload = request.get_json(silent=True) or {}
    user = getattr(request, "current_user", None)
    user_id = getattr(user, "id", None)

    try:
        comment = update_group_comment(
            group_id=group.id,
            comment_id=comment_id,
            body=payload.get("body"),
            user_id=user_id,
        )
    except ValueError as exc:
        return jsonify({
            "error": "validation_error",
            "message": str(exc),
        }), 400
    except LookupError as exc:
        return jsonify({
            "error": "not_found",
            "message": str(exc),
        }), 404

    write_audit(
        "alert_group.comment.update",
        object_type="alert_group",
        object_id=group.id,
        team_id=group.team.id if group.team else None,
        user_id=user_id,
        data={
            "comment_id": comment.id,
        },
    )

    return jsonify(serialize_alert_comment(comment))


@alerts_bp.route("/<int:alert_id>/comments/<int:comment_id>", methods=["DELETE"])
def delete_alert_group_comment(alert_id, comment_id):
    group = alerts_repo.get_alert_group(alert_id)
    if not group:
        return jsonify({
            "error": "not_found",
            "message": "Alert group not found",
        }), 404

    if group.team_id:
        error = require_team_respond(group.team_id)
        if error:
            return error

    user = getattr(request, "current_user", None)
    user_id = getattr(user, "id", None)

    try:
        comment = delete_group_comment(
            group_id=group.id,
            comment_id=comment_id,
            user_id=user_id,
        )
    except LookupError as exc:
        return jsonify({
            "error": "not_found",
            "message": str(exc),
        }), 404

    write_audit(
        "alert_group.comment.delete",
        object_type="alert_group",
        object_id=group.id,
        team_id=group.team.id if group.team else None,
        user_id=user_id,
        data={
            "comment_id": comment.id,
        },
    )

    return jsonify({
        "deleted": True,
        "id": comment.id,
    })


@alerts_bp.route("/<int:alert_id>/priority", methods=["PUT"])
def update_incident_priority(alert_id):
    group = alerts_repo.get_alert_group(alert_id)

    if not group:
        return jsonify({"error": "not_found", "message": "Alert group not found"}), 404

    if group.team_id:
        error = require_team_respond(group.team_id)
        if error:
            return error

    payload = request.get_json(silent=True) or {}
    user = getattr(request, "current_user", None)

    try:
        group = set_incident_priority(
            group_id=group.id,
            priority=payload.get("priority"),
            user_id=getattr(user, "id", None),
        )
    except ValueError as exc:
        return jsonify({"error": "validation_error", "message": str(exc)}), 400

    return jsonify(serialize_alert_group(group, current_user=user))


@alerts_bp.route("/<int:alert_id>/responders", methods=["GET"])
def list_incident_responders(alert_id):
    group = alerts_repo.get_alert_group(alert_id)

    if not group:
        return jsonify({"error": "not_found", "message": "Alert group not found"}), 404

    if group.team_id:
        error = require_team_read(group.team_id)
        if error:
            return error

    return jsonify([
        serialize_incident_responder(responder)
        for responder in alerts_repo.list_incident_responders(group.id)
    ])


@alerts_bp.route("/<int:alert_id>/responders", methods=["POST"])
def add_incident_responder(alert_id):
    group = alerts_repo.get_alert_group(alert_id)

    if not group:
        return jsonify({"error": "not_found", "message": "Alert group not found"}), 404

    if group.team_id:
        error = require_team_respond(group.team_id)
        if error:
            return error

    payload = request.get_json(silent=True) or {}
    user = getattr(request, "current_user", None)

    try:
        responder = create_incident_responder(
            group_id=group.id,
            payload=payload,
            user_id=getattr(user, "id", None),
        )
    except ValueError as exc:
        return jsonify({"error": "validation_error", "message": str(exc)}), 400

    return jsonify(serialize_incident_responder(responder)), 201


@alerts_bp.route("/<int:alert_id>/responders/<int:responder_id>", methods=["PUT"])
def update_incident_responder(alert_id, responder_id):
    group = alerts_repo.get_alert_group(alert_id)

    if not group:
        return jsonify({"error": "not_found", "message": "Alert group not found"}), 404

    if group.team_id:
        error = require_team_respond(group.team_id)
        if error:
            return error

    payload = request.get_json(silent=True) or {}
    user = getattr(request, "current_user", None)

    try:
        responder = set_incident_responder_status(
            group_id=group.id,
            responder_id=responder_id,
            status=payload.get("status"),
            user_id=getattr(user, "id", None),
        )
    except ValueError as exc:
        return jsonify({"error": "validation_error", "message": str(exc)}), 400
    except LookupError as exc:
        return jsonify({"error": "not_found", "message": str(exc)}), 404

    return jsonify(serialize_incident_responder(responder))


@alerts_bp.route("/<int:alert_id>/stakeholders", methods=["GET"])
def list_incident_stakeholders(alert_id):
    group = alerts_repo.get_alert_group(alert_id)

    if not group:
        return jsonify({"error": "not_found", "message": "Alert group not found"}), 404

    if group.team_id:
        error = require_team_read(group.team_id)
        if error:
            return error

    return jsonify([
        serialize_incident_stakeholder(stakeholder)
        for stakeholder in alerts_repo.list_incident_stakeholders(group.id)
    ])


@alerts_bp.route("/<int:alert_id>/stakeholders", methods=["POST"])
def add_incident_stakeholder(alert_id):
    group = alerts_repo.get_alert_group(alert_id)

    if not group:
        return jsonify({"error": "not_found", "message": "Alert group not found"}), 404

    if group.team_id:
        error = require_team_respond(group.team_id)
        if error:
            return error

    payload = request.get_json(silent=True) or {}
    user = getattr(request, "current_user", None)

    try:
        stakeholder = create_incident_stakeholder(
            group_id=group.id,
            payload=payload,
            user_id=getattr(user, "id", None),
        )
    except ValueError as exc:
        return jsonify({"error": "validation_error", "message": str(exc)}), 400

    return jsonify(serialize_incident_stakeholder(stakeholder)), 201
