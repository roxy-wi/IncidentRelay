
from app.modules.db.models import AlertRouteChannel, Group, NotificationChannel, Team
from app.modules.common import utc_now


def list_channels(
    team_id=None,
    team_ids=None,
    enabled_only=False,
    active_only=True,
    include_deleted=False,
):
    """Return notification channels."""
    query = (
        NotificationChannel
        .select(NotificationChannel)
        .join(Team, on=(NotificationChannel.team == Team.id))
        .switch(NotificationChannel)
        .order_by(NotificationChannel.id.asc())
    )

    if not include_deleted:
        query = query.where(NotificationChannel.deleted == False)

    if active_only:
        query = query.where(
            (Team.active == True)
            & (Team.deleted == False)
        )
        query = (
            query
            .join(Group, on=(Team.group == Group.id))
            .where(
                (Group.active == True)
                & (Group.deleted == False)
            )
            .switch(NotificationChannel)
        )

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
    """Return a channel by id."""
    query = NotificationChannel.select().where(NotificationChannel.id == channel_id)

    if not include_deleted:
        query = query.where(NotificationChannel.deleted == False)

    return query.get()


def get_channel_by_team_and_name(
    team_id,
    name,
    *,
    exclude_channel_id=None,
    include_deleted=True,
):
    """Return a channel with the same name in the same team, if any.

    The database has a unique constraint on (team_id, name). Deleted channels are
    included by default because they still occupy that unique key.
    """
    query = NotificationChannel.select().where(
        (NotificationChannel.team == team_id)
        & (NotificationChannel.name == name)
    )

    if exclude_channel_id is not None:
        query = query.where(NotificationChannel.id != exclude_channel_id)

    if not include_deleted:
        query = query.where(NotificationChannel.deleted == False)

    return query.first()


def create_channel(team_id, name, channel_type, config, enabled=True, group_id=None):
    """Create a notification channel."""
    return NotificationChannel.create(
        group=group_id,
        team=team_id,
        name=name,
        channel_type=channel_type,
        config=config or {},
        enabled=enabled,
    )


def create_channel_if_missing(team_id, name, channel_type, config):
    """Create a notification channel if missing."""
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
    """Update a notification channel."""
    channel = get_channel(channel_id)

    for field in ["group", "team", "name", "channel_type", "config", "enabled"]:
        if field in data:
            setattr(channel, field, data[field])

    channel.save()
    return channel


def set_channel_enabled(channel_id, enabled):
    """Enable or disable a notification channel without deleting it.

    Disabled channels stay visible in channel management UI and can be enabled
    again later. Delivery code should use enabled channels only.
    """
    channel = get_channel(channel_id)
    channel.enabled = enabled
    channel.save()
    return channel


def disable_channel(channel_id):
    """Disable a notification channel without deleting it."""
    return set_channel_enabled(channel_id, False)


def enable_channel(channel_id):
    """Enable a previously disabled notification channel."""
    return set_channel_enabled(channel_id, True)


def soft_delete_channel(channel_id):
    """Soft-delete a notification channel without removing historical references."""
    channel = get_channel(channel_id)
    channel.enabled = False
    channel.deleted = True
    channel.deleted_at = utc_now()
    channel.save()
    return channel


def delete_channel(channel_id):
    """Soft-delete a notification channel and remove active route links.

    Route/channel links are active configuration, so they are removed when the
    channel is deleted. Historical alerts remain preserved.
    """
    AlertRouteChannel.delete().where(
        AlertRouteChannel.channel == channel_id
    ).execute()

    return soft_delete_channel(channel_id)


def restore_channel(
    channel_id,
    *,
    channel_type,
    config,
    enabled=True,
    group_id=None,
):
    """Restore and reconfigure a soft-deleted channel."""
    channel = get_channel(
        channel_id,
        include_deleted=True,
    )

    channel.channel_type = channel_type
    channel.config = config or {}
    channel.enabled = enabled
    channel.deleted = False
    channel.deleted_at = None

    if group_id is not None:
        channel.group = group_id

    channel.save()

    return channel

