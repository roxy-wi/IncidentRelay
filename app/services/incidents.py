import smtplib
from email.message import EmailMessage

from app.modules.db import alerts_repo, incidents_repo
from app import Config
from app.services.alerts.priority import (
    alert_priority_label,
    format_alert_title_with_priority,
)
from app.services.links import build_alert_web_url
from app.services.notifications.delivery import update_alert_messages


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


def build_stakeholder_priority_changed_email(group, old_priority=None):
    """Build subject and body for stakeholder priority change notification."""
    priority_label = alert_priority_label(group)
    old_priority = old_priority or "-"

    subject = (
        "[IncidentRelay] "
        f"{format_alert_title_with_priority(group)} priority changed"
    )

    alert_url = build_alert_web_url(group) or "-"
    team = group.team.slug if group.team else "-"
    service = getattr(group.service, "name", None) if group.service else None

    body = "\n".join([
        f"Incident priority changed: {old_priority} -> {priority_label}",
        "",
        f"Incident: {format_alert_title_with_priority(group)}",
        f"Status: {group.status or '-'}",
        f"Severity: {group.severity or '-'}",
        f"Priority: {priority_label}",
        f"Team: {team}",
        f"Service: {service or '-'}",
        f"URL: {alert_url}",
        "",
        "You are receiving this email because you are an incident stakeholder.",
    ])

    return subject, body


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


def notify_stakeholders_on_priority_change(group, old_priority=None):
    """Notify active stakeholders that requested priority change emails."""
    stakeholders = incidents_repo.list_incident_stakeholders(group.id)

    sent = 0
    skipped = 0
    failed = 0

    subject, body = build_stakeholder_priority_changed_email(
        group,
        old_priority=old_priority,
    )

    for stakeholder in stakeholders:
        if not getattr(stakeholder, "notify_on_priority_change", True):
            skipped += 1
            continue

        recipient = stakeholder_email(stakeholder)

        if not recipient:
            skipped += 1
            continue

        try:
            send_stakeholder_email(recipient, subject, body)
            sent += 1
        except Exception as exc:
            failed += 1
            alerts_repo.create_alert_event(
                group_id=group.id,
                event_type="stakeholder_notification_failed",
                message=(
                    "Stakeholder priority change notification failed for "
                    f"{stakeholder_display_name(stakeholder)}: {exc}"
                ),
                user_id=None,
            )

    return {
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
    }


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
        notify_stakeholders_on_priority_change(
            group,
            old_priority=old_priority,
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
