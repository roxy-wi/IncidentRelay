import logging

from app.modules.common import truncate_text
from app.modules.db import incidents_repo, alerts_repo
from app.modules.db.models import User
from app.modules.smtp import send_plain_email
from app.notifiers.browser_push import service as browser_push
from app.services.alerts.priority import PRIORITY_DISPLAY_LABELS, format_alert_title_with_priority, alert_priority_label
from app.services.incidents.participant_notifications import (
    ParticipantRecipient,
    is_notifiable_user,
    notify_participants,
    record_participant_notification_events,
)
from app.services.links import build_alert_web_url

logger = logging.getLogger("oncall.incidents.stakeholders")

VALID_STAKEHOLDER_ROLES = {
    "stakeholder",
    "business_owner",
    "executive",
    "support",
    "customer_success",
    "custom",
}
STAKEHOLDER_NOTIFICATION_EVENTS = {
    "created": {
        "flag": "notify_on_created",
        "subject_suffix": "created",
        "push_event_type": "incident_created",
        "failure_label": "incident-created",
    },
    "priority_changed": {
        "flag": "notify_on_priority_change",
        "subject_suffix": "priority changed",
        "push_event_type": "priority_changed",
        "failure_label": "priority change",
    },
    "status_changed": {
        "flag": "notify_on_status_change",
        "subject_suffix": "status changed",
        "push_event_type": "status_changed",
        "failure_label": "status change",
    },
    "resolved": {
        "flag": "notify_on_resolved",
        "subject_suffix": "resolved",
        "push_event_type": "incident_resolved",
        "failure_label": "resolved",
    },
    "comment_added": {
        "flag": "notify_on_comment",
        "subject_suffix": "new comment",
        "push_event_type": "incident_comment_added",
        "failure_label": "comment",
    },
}


def _stakeholder_comment_lines(context):
    context = context or {}

    author_name = context.get("author_name") or "Unknown user"
    comment_body = context.get("comment_body") or ""
    comment_target = context.get("comment_target") or "incident"

    return [
        f"Comment target: {comment_target}",
        f"Author: {author_name}",
        "",
        "Comment:",
        comment_body,
    ]


def _stakeholder_notification_config(event_type):
    config = STAKEHOLDER_NOTIFICATION_EVENTS.get(event_type)

    if not config:
        raise ValueError(f"unknown stakeholder notification event: {event_type}")

    return config


def _priority_label_from_slug(priority_slug):
    slug = str(priority_slug or "").strip().lower()

    if not slug:
        return "-"

    return PRIORITY_DISPLAY_LABELS.get(slug, slug.upper())


def _stakeholder_notification_headline(group, event_type, old_value=None):
    incident_title = format_alert_title_with_priority(group)

    if event_type == "created":
        return f"New incident created: {incident_title}"

    if event_type == "priority_changed":
        return (
            "Incident priority changed: "
            f"{_priority_label_from_slug(old_value)} -> {alert_priority_label(group)}"
        )

    if event_type == "comment_added":
        context = old_value or {}
        author_name = context.get("author_name") or "Unknown user"
        comment_body = truncate_text(context.get("comment_body"), limit=140)

        if comment_body:
            return f"New comment from {author_name}: {comment_body}"

        return f"New comment from {author_name}"

    if event_type == "status_changed":
        return (
            "Incident status changed: "
            f"{old_value or '-'} -> {group.status or '-'}"
        )

    if event_type == "resolved":
        return f"Incident resolved: {incident_title}"

    return f"Incident updated: {incident_title}"


def build_stakeholder_notification_email(group, event_type, old_value=None):
    """Build subject and body for a stakeholder notification."""
    config = _stakeholder_notification_config(event_type)

    subject = (
        "[IncidentRelay] "
        f"{format_alert_title_with_priority(group)} {config['subject_suffix']}"
    )

    alert_url = build_alert_web_url(group) or "-"
    team = group.team.slug if group.team else "-"
    service = getattr(group.service, "name", None) if group.service else None
    extra_lines = []

    if event_type == "comment_added":
        extra_lines = [""] + _stakeholder_comment_lines(old_value)

    body = "\n".join([
        _stakeholder_notification_headline(
            group,
            event_type,
            old_value=old_value,
        ),
        "",
        f"Incident: {format_alert_title_with_priority(group)}",
        f"Status: {group.status or '-'}",
        f"Severity: {group.severity or '-'}",
        f"Priority: {alert_priority_label(group)}",
        f"Team: {team}",
        f"Service: {service or '-'}",
        *extra_lines,
        f"URL: {alert_url}",
        "",
        "You are receiving this email because you are an incident stakeholder.",
    ])

    return subject, body


def notify_stakeholders(group, event_type, old_value=None, skip_user_id=None):
    """Notify incident stakeholders for one incident event.

    Sends email and browser push when possible. The corresponding notify_on_*
    flag controls both channels for this event.
    """
    config = _stakeholder_notification_config(event_type)
    stakeholders = incidents_repo.list_incident_stakeholders(group.id)

    sent = 0
    skipped = 0
    failed = 0

    subject, body = build_stakeholder_notification_email(
        group,
        event_type,
        old_value=old_value,
    )

    for stakeholder in stakeholders:
        if skip_user_id and getattr(stakeholder, "user_id", None) == skip_user_id:
            skipped += 1
            continue

        if not getattr(stakeholder, config["flag"], True):
            skipped += 1
            continue

        delivered = False
        recipient = stakeholder_email(stakeholder)

        if recipient:
            try:
                send_stakeholder_email(recipient, subject, body)
                sent += 1
                delivered = True
            except Exception as exc:
                failed += 1
                alerts_repo.create_alert_event(
                    group_id=group.id,
                    event_type="stakeholder_notification_failed",
                    message=(
                        f"Stakeholder {config['failure_label']} "
                        "notification failed for "
                        f"{stakeholder_display_name(stakeholder)}: {exc}"
                    ),
                    user_id=None,
                )

        try:
            push_context = old_value if event_type == "comment_added" else None

            push_sent = send_stakeholder_push(
                stakeholder,
                group,
                event_type=config["push_event_type"],
                context=push_context,
            )

            if push_sent:
                sent += push_sent
                delivered = True
        except Exception as exc:
            failed += 1
            alerts_repo.create_alert_event(
                group_id=group.id,
                event_type="stakeholder_push_notification_failed",
                message=(
                    f"Stakeholder {config['failure_label']} push "
                    "notification failed for "
                    f"{stakeholder_display_name(stakeholder)}: {exc}"
                ),
                user_id=None,
            )

        if not delivered:
            skipped += 1

    return {
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
    }


STAKEHOLDER_ADDED_NOTIFICATION_EVENT = "stakeholder_added"
STAKEHOLDER_ADDED_PUSH_EVENT = "stakeholder_added"


def build_stakeholder_added_email(group, added_by_name=None):
    """Build subject and body telling a stakeholder they were added."""
    alert_url = build_alert_web_url(group) or "-"
    team = group.team.slug if group.team else "-"
    service = getattr(group.service, "name", None) if group.service else None

    subject = (
        "[IncidentRelay] You were added as a stakeholder: "
        f"{format_alert_title_with_priority(group)}"
    )

    headline = (
        f"{added_by_name} added you as a stakeholder to this incident."
        if added_by_name
        else "You were added as a stakeholder to this incident."
    )

    body = "\n".join([
        headline,
        "",
        f"Incident: {format_alert_title_with_priority(group)}",
        f"Status: {group.status or '-'}",
        f"Severity: {group.severity or '-'}",
        f"Priority: {alert_priority_label(group)}",
        f"Team: {team}",
        f"Service: {service or '-'}",
        f"URL: {alert_url}",
        "",
        (
            "You are receiving this email because you were added as an "
            "incident stakeholder."
        ),
    ])

    return subject, body


def build_stakeholder_added_slack_text(group, added_by_name=None):
    """Build the Slack message text for a stakeholder addition."""
    alert_url = build_alert_web_url(group)

    who = f" by {added_by_name}" if added_by_name else ""
    text = (
        "You were added as a stakeholder to "
        f"*{format_alert_title_with_priority(group)}*{who}."
    )

    if alert_url:
        text = f"{text}\n{alert_url}"

    return text


def notify_stakeholder_added(stakeholder, group, added_by=None):
    """Notify one stakeholder that they were added to an incident.

    This is a distinct event from the incident lifecycle stakeholder
    notifications and is dispatched when the stakeholder is created.
    Stakeholders added by email address only are email-only, because there is
    no IncidentRelay profile to reach on Slack or browser push.
    """
    user = stakeholder_user(stakeholder)
    email = stakeholder_email(stakeholder)

    if user and not is_notifiable_user(user):
        return None

    if added_by is not None and user is not None:
        if getattr(added_by, "id", None) == getattr(user, "id", None):
            return None

    if not user and not email:
        return None

    added_by_name = None
    if added_by is not None:
        added_by_name = (
            getattr(added_by, "display_name", None)
            or getattr(added_by, "username", None)
        )

    recipient = ParticipantRecipient(
        display_name=stakeholder_display_name(stakeholder),
        user=user,
        email=email,
    )

    subject, body = build_stakeholder_added_email(
        group,
        added_by_name=added_by_name,
    )

    result = notify_participants(
        group,
        [recipient],
        subject=subject,
        body=body,
        slack_text=build_stakeholder_added_slack_text(
            group,
            added_by_name=added_by_name,
        ),
        push_event_type=STAKEHOLDER_ADDED_PUSH_EVENT,
    )

    record_participant_notification_events(
        group.id,
        result,
        sent_event_type="stakeholder_added_notification_sent",
        failed_event_type="stakeholder_added_notification_failed",
        label="Stakeholder added",
    )

    return result.as_dict()


def stakeholder_user(stakeholder):
    """Return active stakeholder user for profile-level notifications."""
    user = getattr(stakeholder, "user", None)

    if not user:
        return None

    if getattr(user, "deleted", False):
        return None

    if not getattr(user, "active", True):
        return None

    return user


def send_stakeholder_push(stakeholder, group, event_type, context=None):
    """Send stakeholder browser push if stakeholder is an active user."""
    user = stakeholder_user(stakeholder)

    if not user:
        return 0

    if context is None:
        return browser_push.send_stakeholder_push_to_user(
            user,
            group,
            event_type=event_type,
        )

    return browser_push.send_stakeholder_push_to_user(
        user,
        group,
        event_type=event_type,
        context=context,
    )


def stakeholder_email(stakeholder):
    """Return notification email for an incident stakeholder."""
    email = str(getattr(stakeholder, "email", None) or "").strip()

    if email:
        return email

    user = getattr(stakeholder, "user", None)

    if not user:
        return None

    if getattr(user, "deleted", False) or not getattr(user, "active", True):
        return None

    email = str(getattr(user, "email", None) or "").strip()

    return email or None


def stakeholder_display_name(stakeholder):
    """Return stakeholder display name for email text."""
    display_name = str(getattr(stakeholder, "display_name", None) or "").strip()

    if display_name:
        return display_name

    user = getattr(stakeholder, "user", None)

    if user:
        return (
            getattr(user, "display_name", None)
            or getattr(user, "username", None)
            or getattr(user, "email", None)
            or "stakeholder"
        )

    return stakeholder_email(stakeholder) or "stakeholder"


def send_stakeholder_email(recipient, subject, body):
    """Send a plain stakeholder notification email."""
    send_plain_email(recipient, subject, body)


def create_incident_stakeholder(*, group_id, payload, user_id=None):
    group = alerts_repo.get_alert_group(group_id)

    if not group:
        raise LookupError("incident not found")

    if not payload.get("user_id") and not payload.get("email"):
        raise ValueError("user_id or email is required")

    role = payload.get("role") or "stakeholder"

    if role not in VALID_STAKEHOLDER_ROLES:
        raise ValueError(
            "role must be one of: stakeholder, business_owner, executive, support, customer_success, custom"
        )

    stakeholder = incidents_repo.create_incident_stakeholder(
        group.id,
        {
            "user_id": payload.get("user_id"),
            "email": payload.get("email"),
            "display_name": payload.get("display_name"),
            "role": role,
            "source": "manual",
            "notify_on_created": payload.get("notify_on_created", True),
            "notify_on_priority_change": payload.get("notify_on_priority_change", True),
            "notify_on_status_change": payload.get("notify_on_status_change", True),
            "notify_on_resolved": payload.get("notify_on_resolved", True),
            "created_by_id": user_id,
        },
    )

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type="stakeholder_added",
        message="Stakeholder added",
        user_id=user_id,
    )

    # Only manually added stakeholders are notified on add. Stakeholders
    # created automatically from service defaults are intentionally excluded so
    # incident creation does not fan out a burst of notifications.
    added_by = None
    if user_id:
        added_by = User.get_or_none(User.id == user_id)

    try:
        notify_stakeholder_added(stakeholder, group, added_by=added_by)
    except Exception as exc:
        logger.exception(
            "stakeholder added notification failed",
            extra={
                "extra": {
                    "event_type": "stakeholder_added_notification_failed",
                    "group_id": group.id,
                    "stakeholder_id": stakeholder.id,
                    "error": str(exc),
                }
            },
        )

    return stakeholder


def remove_incident_stakeholder(*, group_id, stakeholder_id, user_id=None):
    group = alerts_repo.get_alert_group(group_id)

    if not group:
        raise LookupError("incident not found")

    stakeholder = incidents_repo.get_incident_stakeholder(stakeholder_id)

    if not stakeholder or stakeholder.group_id != group.id or not stakeholder.active:
        raise LookupError("stakeholder not found in this incident")

    incidents_repo.deactivate_incident_stakeholder(stakeholder.id)

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type="stakeholder_removed",
        message="Stakeholder removed",
        user_id=user_id,
    )

    return stakeholder
