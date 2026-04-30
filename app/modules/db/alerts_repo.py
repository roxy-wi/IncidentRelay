from datetime import datetime, timedelta

from app.modules.db.models import Alert, AlertEvent


def list_alerts(team_id=None, team_ids=None, status=None, source=None, severity=None, limit=300):
    """
    Return alerts using optional filters.
    """

    query = Alert.select().order_by(Alert.id.desc())
    if team_id:
        query = query.where(Alert.team == team_id)
    elif team_ids is not None:
        if not team_ids:
            return []
        query = query.where(Alert.team.in_(team_ids))
    if status:
        query = query.where(Alert.status == status)
    if source:
        query = query.where(Alert.source == source)
    if severity:
        query = query.where(Alert.severity == severity)
    return list(query.limit(limit))


def get_alert(alert_id):
    """
    Return an alert by id.
    """

    return Alert.get_by_id(alert_id)


def find_existing_alert(source, dedup_key, window_seconds):
    """
    Return an existing alert inside the deduplication window.
    """

    threshold = datetime.utcnow() - timedelta(seconds=window_seconds)
    return (
        Alert.select()
        .where(
            (Alert.source == source)
            & (Alert.dedup_key == dedup_key)
            & ((Alert.status != "resolved") | (Alert.last_seen_at >= threshold))
        )
        .order_by(Alert.id.desc())
        .first()
    )


def create_alert(**kwargs):
    """
    Create an alert.
    """

    return Alert.create(**kwargs)


def update_alert_from_payload(alert, alert_data, status, group_key):
    """
    Update an alert from normalized payload data.
    """

    previous_status = alert.status
    alert.previous_status = previous_status
    alert.last_seen_at = datetime.utcnow()
    alert.payload = alert_data.get("payload")
    alert.labels = alert_data.get("labels")
    alert.message = alert_data.get("message")
    alert.severity = alert_data.get("severity")
    alert.group_key = group_key
    if previous_status in ("acknowledged", "silenced") and status == "firing":
        alert.status = previous_status
    else:
        alert.status = status
    alert.save()
    return alert, previous_status


def acknowledge_alert(alert_id, user_id=None):
    """
    Mark an alert as acknowledged.
    """

    alert = get_alert(alert_id)
    alert.status = "acknowledged"
    alert.acknowledged_by = user_id
    alert.acknowledged_at = datetime.utcnow()
    alert.save()
    return alert


def resolve_alert(alert_id):
    """
    Mark an alert as resolved.
    """

    alert = get_alert(alert_id)
    alert.status = "resolved"
    alert.save()
    return alert


def list_firing_alerts():
    """
    Return firing alerts for reminder evaluation.
    """

    return list(Alert.select().where(Alert.status == "firing"))


def record_notification_time(alert, now):
    """
    Update alert notification time.
    """

    alert.last_notification_at = now
    alert.save()
    return alert


def increment_reminder(alert, now):
    """
    Increment reminder count.
    """

    alert.reminder_count += 1
    alert.last_notification_at = now
    alert.save()
    return alert


def escalate_alert(alert, user_id):
    """
    Assign an alert to another user and increase escalation level.
    """

    alert.assignee = user_id
    alert.escalation_level += 1
    alert.reminder_count = 0
    alert.save()
    return alert


def create_alert_event(alert_id, event_type, message=None, user_id=None):
    """
    Create an alert event.
    """

    return AlertEvent.create(alert=alert_id, event_type=event_type, message=message, user=user_id)


def list_alert_events(alert_id):
    """
    Return alert events.
    """

    return list(
        AlertEvent.select()
        .where(AlertEvent.alert == alert_id)
        .order_by(AlertEvent.id.asc())
    )
