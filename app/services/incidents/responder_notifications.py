import logging

from app.modules.db import incidents_repo
from app.modules.db.models import Group, Team, TeamUser, User, UserGroup
from app.services import escalation_policies as escalation_policy_service
from app.services.oncall import get_current_oncall_user
from app.services.incidents.responder_display import user_display_name

logger = logging.getLogger("oncall.incidents.responders")

RESPONDER_NOTIFICATION_EVENT = "responder_requested"


def _unique_active_users(users):
    result = []
    seen = set()

    for user in users:
        if not user:
            continue

        if not getattr(user, "active", False):
            continue

        if getattr(user, "deleted", False):
            continue

        if user.id in seen:
            continue

        seen.add(user.id)
        result.append(user)

    return result


def team_help_recipients(responder):
    """Select current recipients, including when rechecking queued deliveries."""
    users = (
        User.select().join(TeamUser).join(Team)
        .where(
            Team.id == responder.target_team_id,
            Team.active == True,
            Team.deleted == False,
            TeamUser.active == True,  # noqa: E712
            TeamUser.role.in_(("responder", "manager")),
            User.active == True,  # noqa: E712
            User.deleted == False,  # noqa: E712
        )
        .order_by(TeamUser.id.asc())
    )

    group_id = responder.incident.team.group_id if responder.incident.team_id else None
    if group_id:
        memberships = UserGroup.select(UserGroup.user).join(Group).where(
            UserGroup.group == group_id, UserGroup.active == True,
            Group.active == True, Group.deleted == False,
        )
        users = users.where(Team.group == group_id, User.id.in_(memberships))
    return users


def _rotation_current_user(responder):
    rotation = (
        responder.target_rotation
        if responder.target_rotation_id
        else None
    )

    if not rotation:
        return None

    return get_current_oncall_user(rotation)


def _escalation_policy_first_user(responder):
    policy = (
        responder.target_escalation_policy
        if responder.target_escalation_policy_id
        else None
    )

    if not policy:
        return None

    rule = escalation_policy_service.get_first_enabled_rule(policy)
    if not rule:
        return None

    return escalation_policy_service.resolve_rule_user(rule)


def resolve_responder_recipients(responder):
    """Resolve responder request target to concrete users."""
    if responder.target_type == "user":
        return _unique_active_users([
            responder.target_user if responder.target_user_id else None
        ])

    if responder.target_type == "team":
        return list(team_help_recipients(responder))

    if responder.target_type == "rotation":
        return _unique_active_users([
            _rotation_current_user(responder)
        ])

    if responder.target_type == "escalation_policy":
        return _unique_active_users([
            _escalation_policy_first_user(responder)
        ])

    return []


def _responder_notification_context(responder):
    requested_by = (
        responder.requested_by
        if responder.requested_by_id
        else None
    )

    return {
        "responder_id": responder.id,
        "target_type": responder.target_type,
        "message": responder.message,
        "requested_by_id": requested_by.id if requested_by else None,
        "requested_by_name": user_display_name(requested_by),
    }


def notify_incident_responder_requested(responder):
    """Dispatch the persisted request event; failed targets remain scheduled."""
    from app.services.notifications.incidents import (
        dispatch_event, responder_notification_event,
    )

    try:
        row = responder_notification_event(responder.id)
        sent = dispatch_event(row.event_id) if row else 0
        current = incidents_repo.get_incident_responder(responder.id)
        return {
            "status": current.notification_status,
            "sent": sent,
            "error": current.notification_error,
        }
    except Exception as exc:
        logger.error(
            "Responder dispatch deferred: responder_id=%s error_type=%s",
            responder.id, type(exc).__name__,
        )
        return {"status": "pending", "sent": 0, "error": "dispatch_deferred"}
