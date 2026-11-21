
from app.modules.db.models import AlertNotification
from app.modules.common import utc_now


def get_notification(group_id, channel_id):
    """Return a delivery record for an alert group/channel pair."""

    return AlertNotification.get_or_none(
        (AlertNotification.group == group_id)
        & (AlertNotification.channel == channel_id)
    )


def save_notification(
    group_id,
    channel_id,
    provider=None,
    external_message_id=None,
    external_channel_id=None,
    event_type=None,
    error=None,
    provider_status=None,
    provider_payload=None,
):
    """Create or update group-level delivery record."""

    record = get_notification(
        group_id=group_id,
        channel_id=channel_id,
    )

    if not record:
        return AlertNotification.create(
            group=group_id,
            channel=channel_id,
            provider=provider,
            external_message_id=external_message_id,
            external_channel_id=external_channel_id,
            last_event_type=event_type,
            last_error=error,
            provider_status=provider_status,
            provider_payload=provider_payload,
            updated_at=utc_now(),
        )

    record.provider = provider or record.provider
    record.external_message_id = external_message_id or record.external_message_id
    record.external_channel_id = external_channel_id or record.external_channel_id
    record.last_event_type = event_type or record.last_event_type
    record.last_error = error
    record.provider_status = provider_status or record.provider_status

    if provider_payload is not None:
        record.provider_payload = provider_payload

    record.updated_at = utc_now()
    record.save()

    return record


def mark_notification_error(
    group_id,
    channel_id,
    provider=None,
    event_type=None,
    error=None,
):
    """Store latest group-level delivery error."""

    return save_notification(
        group_id=group_id,
        channel_id=channel_id,
        provider=provider,
        event_type=event_type,
        error=str(error),
    )


def list_notifications_for_group(group_id):
    """Return delivery records for alert group."""

    return list(
        AlertNotification
        .select()
        .where(AlertNotification.group == group_id)
        .order_by(AlertNotification.updated_at.desc(), AlertNotification.id.desc())
    )
