from datetime import datetime

from app.modules.db.models import AlertNotification


def get_notification(alert_id, channel_id):
    """
    Return a delivery record for an alert/channel pair.
    """

    return AlertNotification.get_or_none(
        (AlertNotification.alert == alert_id) &
        (AlertNotification.channel == channel_id)
    )


def save_notification(alert_id, channel_id, provider, external_message_id=None, external_channel_id=None, event_type=None, error=None):
    """
    Create or update a delivery record.
    """

    record = get_notification(alert_id, channel_id)

    if not record:
        record = AlertNotification.create(
            alert=alert_id,
            channel=channel_id,
            provider=provider,
            external_message_id=external_message_id,
            external_channel_id=external_channel_id,
            last_event_type=event_type,
            last_error=error,
            updated_at=datetime.utcnow(),
        )
        return record

    record.provider = provider or record.provider
    record.external_message_id = external_message_id or record.external_message_id
    record.external_channel_id = external_channel_id or record.external_channel_id
    record.last_event_type = event_type or record.last_event_type
    record.last_error = error
    record.updated_at = datetime.utcnow()
    record.save()
    return record


def mark_notification_error(alert_id, channel_id, provider, event_type, error):
    """
    Store the latest delivery error for an alert/channel pair.
    """

    return save_notification(
        alert_id=alert_id,
        channel_id=channel_id,
        provider=provider,
        event_type=event_type,
        error=str(error),
    )


def list_notifications_for_alert(alert_id):
    """
    Return delivery records for an alert ordered by id.
    """

    return list(
        AlertNotification.select()
        .where(AlertNotification.alert == alert_id)
        .order_by(AlertNotification.id.asc())
    )
