import logging

from app.modules.db import alerts_repo, incidents_repo
from app.modules.db.models import TeamUser, User
from app.notifiers.browser_push import service as browser_push
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


def _team_responder_users(team_id):
    if not team_id:
        return []

    rows = (
        TeamUser
        .select(TeamUser, User)
        .join(User)
        .where(
            TeamUser.team == team_id,
            TeamUser.active == True,  # noqa: E712
            TeamUser.role.in_(("responder", "manager")),
            User.active == True,  # noqa: E712
            User.deleted == False,  # noqa: E712
        )
        .order_by(TeamUser.id.asc())
    )

    return [row.user for row in rows]


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
        return _unique_active_users(
            _team_responder_users(responder.target_team_id)
        )

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


def _mark_notification_failed(responder, error):
    incidents_repo.update_incident_responder_notification(
        responder.id,
        status="failed",
        error=error,
    )
    alerts_repo.create_alert_event(
        group_id=responder.group_id,
        event_type="responder_notification_failed",
        message=f"Responder notification failed: {error}",
        user_id=None,
    )

    return {
        "status": "failed",
        "sent": 0,
        "error": error,
    }


def notify_incident_responder_requested(responder):
    """Send browser push notification for a responder request."""
    recipients = resolve_responder_recipients(responder)

    if not recipients:
        return _mark_notification_failed(
            responder,
            "no active responder recipients",
        )

    sent_devices = 0
    errors = []
    context = _responder_notification_context(responder)

    for user in recipients:
        try:
            sent = browser_push.send_stakeholder_push_to_user(
                user,
                responder.group,
                event_type=RESPONDER_NOTIFICATION_EVENT,
                context=context,
            )
        except Exception as exc:
            logger.exception(
                "responder browser push failed",
                extra={
                    "extra": {
                        "event_type": "responder_notification_failed",
                        "responder_id": responder.id,
                        "user_id": user.id,
                        "error": str(exc),
                    }
                },
            )
            errors.append(f"{user_display_name(user)}: {exc}")
            continue

        if sent:
            sent_devices += sent
        else:
            errors.append(
                f"{user_display_name(user)}: no active push subscriptions"
            )

    if sent_devices > 0:
        error = "; ".join(errors) if errors else None

        incidents_repo.update_incident_responder_notification(
            responder.id,
            status="sent",
            error=error,
        )
        alerts_repo.create_alert_event(
            group_id=responder.group_id,
            event_type="responder_notification_sent",
            message=(
                "Responder notification sent to "
                f"{sent_devices} browser push device(s)"
            ),
            user_id=None,
        )
        return {
            "status": "sent",
            "sent": sent_devices,
            "error": error,
        }

    error = "; ".join(errors) or "no browser push notifications were sent"
    return _mark_notification_failed(responder, error)
