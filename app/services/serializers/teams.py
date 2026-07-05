from app.services.serializers.common import attach_group_permissions, attach_team_permissions


def serialize_group(group, current_user=None):
    """
    Serialize a group.
    """

    data = {
        "id": group.id,
        "slug": group.slug,
        "name": group.name,
        "description": group.description,
        "active": group.active,
    }

    return attach_group_permissions(data, group.id, current_user)


def serialize_team(team, current_user=None):
    """
    Serialize a team.
    """

    data = {
        "id": team.id,
        "group_id": team.group.id if team.group else None,
        "group_slug": team.group.slug if team.group else None,
        "group_name": team.group.name if team.group else None,
        "slug": team.slug,
        "name": team.name,
        "description": team.description,
        "escalation_enabled": team.escalation_enabled,
        "escalation_after_reminders": team.escalation_after_reminders,
        "active": team.active,
    }

    return attach_team_permissions(data, team.id, current_user)


def serialize_team_short(team):
    """Serialize a compact team object."""
    if not team:
        return None

    return {
        "id": team.id,
        "slug": team.slug,
        "name": team.name,
        "active": team.active,
        "group_id": team.group.id if team.group else None,
        "group_slug": team.group.slug if team.group else None,
    }
