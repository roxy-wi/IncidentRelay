from datetime import datetime

from app.modules.db.models import AlertRouteChannel, NotificationChannel


def list_channels(team_id=None, team_ids=None, enabled_only=False, include_deleted=False):
    """
    Return notification channels.
    """

    query = NotificationChannel.select().order_by(NotificationChannel.id.asc())

    if not include_deleted:
        query = query.where(NotificationChannel.deleted == False)

    if team_id:
        query = query.where(NotificationChannel.team == team_id)
    elif team_ids is not None:
        if not team_ids:
            return []
        query = query.where(NotificationChannel.team.in_(team_ids))

    if enabled_only:
        query = query.where(NotificationChannel.enabled == True)

    return list(query)


def get_channel(channel_id, include_deleted=False):
    """
    Return a channel by id.
    """

    query = NotificationChannel.select().where(NotificationChannel.id == channel_id)

    if not include_deleted:
        query = query.where(NotificationChannel.deleted == False)

    return query.get()


def create_channel(team_id, name, channel_type, config, enabled=True, group_id=None):
    """
    Create a notification channel.
    """

    return NotificationChannel.create(
        group=group_id,
        team=team_id,
        name=name,
        channel_type=channel_type,
        config=config or {},
        enabled=enabled,
    )


def create_channel_if_missing(team_id, name, channel_type, config):
    """
    Create a notification channel if missing.
    """

    channel, _ = NotificationChannel.get_or_create(
        team=team_id,
        name=name,
        defaults={"channel_type": channel_type, "config": config or {}},
    )

    if channel.deleted:
        channel.deleted = False
        channel.deleted_at = None
        channel.enabled = True
        channel.save()

    return channel


def update_channel(channel_id, data):
    """
    Update a notification channel.
    """

    channel = get_channel(channel_id)

    for field in ["group", "team", "name", "channel_type", "config", "enabled"]:
        if field in data:
            setattr(channel, field, data[field])

    channel.save()
    return channel


def disable_channel(channel_id):
    """
    Soft-delete a notification channel without removing historical references.
    """

    return soft_delete_channel(channel_id)


def soft_delete_channel(channel_id):
    """
    Soft-delete a notification channel without removing historical references.
    """

    channel = get_channel(channel_id)
    channel.enabled = False
    channel.deleted = True
    channel.deleted_at = datetime.utcnow()
    channel.save()
    return channel


def delete_channel(channel_id):
    """
    Soft-delete a notification channel and remove its route links.
    """

    AlertRouteChannel.delete().where(AlertRouteChannel.channel == channel_id).execute()
    return soft_delete_channel(channel_id)
