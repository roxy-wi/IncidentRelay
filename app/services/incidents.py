import smtplib
from email.message import EmailMessage

from app.modules.common import truncate_text
from app.modules.db import alerts_repo, incidents_repo
from app import Config
from app.services.alerts.priority import (
    PRIORITY_DISPLAY_LABELS,
    alert_priority_label,
    format_alert_title_with_priority,
)
from app.services.links import build_alert_web_url
from app.services.notifications.delivery import update_alert_messages
from app.notifiers.browser_push import service as browser_push


VALID_RESPONDER_TARGETS = {
    "user",
    "team",
    "rotation",
    "escalation_policy",
}

VALID_RESPONDER_STATUSES = {
    "requested",
    "accepted",
    "declined",
    "expired",
    "resolved",
}

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
    smtp_host = Config.SMTP_HOST
    smtp_port = int(Config.SMTP_PORT)

    if not smtp_host:
        raise RuntimeError("smtp host is missing: set [smtp] host in config")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = Config.SMTP_FROM
    message["To"] = recipient
    message.set_content(body)

    username = (Config.SMTP_USER or "").strip()
    password = Config.SMTP_PASSWORD or ""

    with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as smtp:
        smtp.ehlo()

        if Config.SMTP_USE_TLS:
            smtp.starttls()
            smtp.ehlo()

        if username or password:
            if not username or not password:
                raise RuntimeError(
                    "SMTP auth is partially configured: both [smtp] user "
                    "and password must be set, or both must be empty"
                )

            if not smtp.has_extn("auth"):
                raise RuntimeError(
                    "SMTP auth is configured, but the SMTP server does not "
                    "support AUTH"
                )

            smtp.login(username, password)

        smtp.send_message(message)


def set_incident_priority(*, group_id, priority, user_id=None):
    if not priority:
        raise ValueError("priority is required")

    group = alerts_repo.get_alert_group(group_id)

    if not group:
        raise LookupError("incident not found")

    old_priority = group.priority_slug

    group = incidents_repo.set_incident_priority(
        group.id,
        priority,
        user_id=user_id,
        manual=True,
    )

    if old_priority != group.priority_slug:
        update_alert_messages(group, event_type="priority_changed")
        notify_stakeholders(
            group,
            "priority_changed",
            old_value=old_priority,
        )

    return group


def create_incident_responder(*, group_id, payload, user_id=None):
    group = alerts_repo.get_alert_group(group_id)

    if not group:
        raise LookupError("incident not found")

    target_type = payload.get("target_type")

    if target_type not in VALID_RESPONDER_TARGETS:
        raise ValueError(
            "target_type must be one of: user, team, rotation, escalation_policy"
        )

    target_fields = {
        "user": "target_user_id",
        "team": "target_team_id",
        "rotation": "target_rotation_id",
        "escalation_policy": "target_escalation_policy_id",
    }

    required_field = target_fields[target_type]

    if not payload.get(required_field):
        raise ValueError(f"{required_field} is required for {target_type} responder")

    responder = incidents_repo.create_incident_responder(
        group.id,
        {
            "target_type": target_type,
            "target_user_id": payload.get("target_user_id"),
            "target_team_id": payload.get("target_team_id"),
            "target_rotation_id": payload.get("target_rotation_id"),
            "target_escalation_policy_id": payload.get("target_escalation_policy_id"),
            "requested_by_id": user_id,
            "message": payload.get("message"),
            "expires_after_minutes": payload.get("expires_after_minutes"),
            "status": "requested",
        },
    )

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type="responder_requested",
        message=payload.get("message") or f"Responder requested: {target_type}",
        user_id=user_id,
    )

    return responder


def set_incident_responder_status(
    *,
    group_id,
    responder_id,
    status,
    response_message=None,
    user_id=None,
):
    group = alerts_repo.get_alert_group(group_id)

    if not group:
        raise LookupError("incident not found")

    if status not in VALID_RESPONDER_STATUSES:
        raise ValueError(
            "status must be one of: requested, accepted, declined, expired, resolved"
        )

    responder = incidents_repo.get_incident_responder(responder_id)

    if not responder or responder.group_id != group.id:
        raise LookupError("responder not found in this incident")

    responder = incidents_repo.update_incident_responder_status(
        responder.id,
        status,
        user_id=user_id,
        response_message=response_message,
    )

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type=f"responder_{status}",
        message=response_message or f"Responder status changed to {status}",
        user_id=user_id,
    )

    return responder


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
