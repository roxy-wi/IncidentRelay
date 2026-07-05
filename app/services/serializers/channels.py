from app.services.serializers.common import attach_team_permissions


def serialize_channel(channel, current_user=None):
    """Serialize a notification channel."""
    team_id = channel.team.id if channel.team else None

    data = {
        "id": channel.id,
        "group_id": channel.group.id if getattr(channel, "group", None) else None,
        "group_name": channel.group.name if getattr(channel, "name", None) else None,
        "group_slug": channel.group.slug if getattr(channel, "group", None) else None,
        "team_id": team_id,
        "team_name": channel.team.name if channel.team else None,
        "team_slug": channel.team.slug if channel.team else None,
        "name": channel.name,
        "channel_type": channel.channel_type,
        "config": channel.config,
        "enabled": channel.enabled,
    }

    data = attach_team_permissions(data, team_id, current_user)

    if current_user and team_id:
        from app.services.rbac import can_access_team_or_group_resource

        data.setdefault("permissions", {})["can_write"] = (
            can_access_team_or_group_resource(
                current_user,
                team_id,
                write_required=True,
            )
        )

    return data


def serialize_channel_short(channel):
    """
    Serialize a compact channel object.
    """

    if not channel:
        return None

    return {
        "id": channel.id,
        "name": channel.name,
        "channel_type": channel.channel_type,
        "enabled": channel.enabled,
    }
