import logging

from app.modules.db import alerts_repo, incidents_repo
from app.modules.db.models import TeamUser, User
from app.services import escalation_policies as escalation_policy_service
from app.services.alerts.priority import (
    alert_priority_label,
    format_alert_title_with_priority,
)
from app.services.incidents.participant_notifications import (
    KIND_RESPONDER,
    ParticipantRecipient,
    enqueue_participant_notifications,
    is_notifiable_user,
    user_contact_email,
)
from app.notifiers.slack.mrkdwn import escape_mrkdwn
from app.services.links import build_alert_web_url
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


def build_responder_notification_email(responder):
    """Build subject and body telling a user they were added as a responder."""
    group = responder.group
    context = _responder_notification_context(responder)
    alert_url = build_alert_web_url(group) or "-"
    team = group.team.slug if group.team else "-"
    service = getattr(group.service, "name", None) if group.service else None

    subject = (
        "[IncidentRelay] You were added as a responder: "
        f"{format_alert_title_with_priority(group)}"
    )

    lines = [
        (
            f"{context['requested_by_name']} added you as a responder "
            "to this incident."
        ),
        "",
        f"Incident: {format_alert_title_with_priority(group)}",
        f"Status: {group.status or '-'}",
        f"Severity: {group.severity or '-'}",
        f"Priority: {alert_priority_label(group)}",
        f"Team: {team}",
        f"Service: {service or '-'}",
    ]

    if context["message"]:
        lines.extend(["", "Message:", context["message"]])

    lines.extend([
        "",
        f"URL: {alert_url}",
        "",
        (
            "You are receiving this email because you were requested as an "
            "incident responder."
        ),
    ])

    return subject, "\n".join(lines)


def build_responder_notification_slack_text(responder):
    """Build the Slack message text for a responder request.

    Dynamic fields (alert title, requester name, free-text message) are escaped
    for Slack mrkdwn so an injected ``<!channel>``/``<!here>``/``<@U...>`` cannot
    trigger a real broadcast or mention. The ``*...*`` emphasis and the alert URL
    are generated by this function and are safe as-is.
    """
    group = responder.group
    context = _responder_notification_context(responder)
    alert_url = build_alert_web_url(group)

    title = escape_mrkdwn(format_alert_title_with_priority(group))
    requested_by = escape_mrkdwn(context["requested_by_name"])

    text = (
        f"You were added as a responder to *{title}* "
        f"by {requested_by}."
    )

    if context["message"]:
        text = f"{text}\nMessage: {escape_mrkdwn(context['message'])}"

    if alert_url:
        text = f"{text}\n{alert_url}"

    return text


def _responder_recipients(responder):
    """Resolve responder targets to notifiable participant recipients."""
    recipients = []

    for user in resolve_responder_recipients(responder):
        if not is_notifiable_user(user):
            continue

        recipients.append(
            ParticipantRecipient(
                display_name=user_display_name(user),
                user=user,
                email=user_contact_email(user),
            )
        )

    return recipients


def notify_incident_responder_requested(responder):
    """Enqueue responder notifications over email, Slack and browser push.

    Delivery happens asynchronously in the scheduler, so this returns once the
    work is persisted. The responder notification status is left as ``queued``;
    the worker records the final ``sent``/``failed`` outcome once every
    enqueued delivery is terminal.
    """
    recipients = _responder_recipients(responder)

    if not recipients:
        return _mark_notification_failed(
            responder,
            "no active responder recipients",
        )

    subject, body = build_responder_notification_email(responder)

    enqueued = enqueue_participant_notifications(
        responder.group,
        recipients,
        kind=KIND_RESPONDER,
        source_id=responder.id,
        subject=subject,
        body=body,
        slack_text=build_responder_notification_slack_text(responder),
        push_event_type=RESPONDER_NOTIFICATION_EVENT,
        push_context=_responder_notification_context(responder),
    )

    incidents_repo.update_incident_responder_notification(
        responder.id,
        status="queued",
        error=None,
    )

    alerts_repo.create_alert_event(
        group_id=responder.group_id,
        event_type="responder_notification_queued",
        message=f"Responder notification queued for delivery ({enqueued} deliveries)",
        user_id=None,
    )

    return {"status": "queued", "enqueued": enqueued}
