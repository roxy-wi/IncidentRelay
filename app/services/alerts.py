import logging
from datetime import datetime, timedelta

from app.settings import Config
from app.modules.db import alerts_repo
from app.services.notifier import notify_alert, update_alert_messages
from app.services.oncall import get_current_oncall_user, get_next_rotation_user
from app.services.routing import build_group_key, find_route_for_alert
from app.services.silences import find_active_silence


logger = logging.getLogger("oncall.alerts")


def upsert_alert(alert_data):
    """
    Create or update an alert from normalized alert data.
    """

    route = find_route_for_alert(alert_data)
    team = route.team if route else None
    rotation = route.rotation if route else None
    group_key = build_group_key(route, alert_data)
    status = alert_data.get("status", "firing")

    existing_alert = alerts_repo.find_existing_alert(alert_data["source"], alert_data["dedup_key"], Config.ALERT_GROUP_WINDOW_SECONDS)
    if existing_alert:
        existing_alert, previous_status = alerts_repo.update_alert_from_payload(existing_alert, alert_data, status, group_key)
        if status == "resolved" and previous_status != "resolved":
            alerts_repo.create_alert_event(existing_alert.id, "resolved", "Alert resolved by incoming payload")
            logger.info("alert resolved by incoming payload", extra={"extra": {"alert_id": existing_alert.id, "source": existing_alert.source}})
            notify_alert(existing_alert, event_type="resolved")
        else:
            alerts_repo.create_alert_event(existing_alert.id, "updated", "Alert updated from incoming payload")
            logger.info("alert updated", extra={"extra": {"alert_id": existing_alert.id, "source": existing_alert.source}})
        return existing_alert, False

    assignee = get_current_oncall_user(rotation) if rotation else None
    silence = find_active_silence(team.id if team else None, alert_data)
    if silence and status == "firing":
        status = "silenced"

    alert = alerts_repo.create_alert(
        team=team.id if team else None,
        route=route.id if route else None,
        rotation=rotation.id if rotation else None,
        assignee=assignee.id if assignee else None,
        source=alert_data["source"],
        external_id=alert_data.get("external_id"),
        dedup_key=alert_data["dedup_key"],
        group_key=group_key,
        title=alert_data["title"],
        message=alert_data.get("message"),
        severity=alert_data.get("severity"),
        labels=alert_data.get("labels"),
        payload=alert_data.get("payload"),
        status=status,
        first_seen_at=datetime.utcnow(),
        last_seen_at=datetime.utcnow(),
        silenced=bool(silence),
    )

    alerts_repo.create_alert_event(alert.id, "created", "Alert created")

    if alert_data.get("routing_error"):
        alerts_repo.create_alert_event(alert.id, "routing_error", alert_data["routing_error"])

    logger.info(
        "alert created",
        extra={
            "extra": {
                "alert_id": alert.id,
                "team": alert.team.slug if alert.team else None,
                "route_id": alert.route.id if alert.route else None,
                "routing_error": alert_data.get("routing_error"),
            }
        },
    )
    if silence:
        alerts_repo.create_alert_event(alert.id, "silenced", f"Matched silence: {silence.name}")
    if status == "firing":
        notify_alert(alert, event_type="notification")
    return alert, True


def acknowledge_alert(alert_id, user_id=None):
    """
    Acknowledge an alert.
    """

    alert = alerts_repo.acknowledge_alert(alert_id, user_id=user_id)
    alerts_repo.create_alert_event(alert.id, "acknowledged", "Alert acknowledged", user_id=user_id)
    logger.info("alert acknowledged", extra={"extra": {"alert_id": alert.id, "user_id": user_id}})
    update_alert_messages(alert, event_type="acknowledged")
    return alert


def resolve_alert(alert_id, user_id=None):
    """
    Resolve an alert.
    """

    alert = alerts_repo.resolve_alert(alert_id)
    alerts_repo.create_alert_event(alert.id, "resolved", "Alert resolved", user_id=user_id)
    logger.info("alert resolved", extra={"extra": {"alert_id": alert.id, "user_id": user_id}})
    update_alert_messages(alert, event_type="resolved")
    return alert


def maybe_escalate_alert(alert):
    """
    Escalate an alert according to the team policy.
    """

    if not alert.team or not alert.team.escalation_enabled:
        return False
    if alert.reminder_count < alert.team.escalation_after_reminders:
        return False

    next_user = get_next_rotation_user(alert.rotation, alert.assignee)
    if not next_user or (alert.assignee and next_user.id == alert.assignee.id):
        return False

    alerts_repo.escalate_alert(alert, next_user.id)
    alerts_repo.create_alert_event(alert.id, "escalated", f"Escalated to {next_user.username}")
    notify_alert(alert, event_type="escalation")
    return True


def get_alert_reminder_interval(alert):
    """
    Return the reminder interval for an alert.

    Rotation settings have priority. The global setting is only a fallback
    for alerts without a rotation or for old database records.
    """

    if alert.rotation and getattr(alert.rotation, "reminder_interval_seconds", None):
        return alert.rotation.reminder_interval_seconds

    return Config.REMINDER_AFTER_SECONDS


def should_send_reminder(alert, now):
    """
    Check whether a reminder should be sent now.
    """

    if not alert.last_notification_at:
        return True

    reminder_interval = get_alert_reminder_interval(alert)
    return alert.last_notification_at <= now - timedelta(seconds=reminder_interval)


def send_unacked_reminders():
    """
    Send reminder notifications for unacknowledged alerts.
    """

    now = datetime.utcnow()
    count = 0

    for alert in alerts_repo.list_firing_alerts():
        if not should_send_reminder(alert, now):
            continue

        if maybe_escalate_alert(alert):
            count += 1
            continue

        notify_alert(alert, event_type="reminder")
        alerts_repo.increment_reminder(alert, now)
        alerts_repo.create_alert_event(alert.id, "reminder_sent", f"Reminder count: {alert.reminder_count}")
        count += 1

    return count
