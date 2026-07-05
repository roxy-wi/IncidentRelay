from app.services.serializers.common import attach_team_permissions, serialize_utc_datetime


def serialize_rotation_short(rotation):
    """Serialize a compact rotation object."""
    if not rotation:
        return None

    team = rotation.team if getattr(rotation, "team_id", None) else None

    return {
        "id": rotation.id,
        "name": rotation.name,
        "team_id": team.id if team else None,
        "team_slug": team.slug if team else None,
        "team_name": team.name if team else None,
        "enabled": rotation.enabled,
        "timezone": rotation.timezone,
    }


def serialize_escalation_policy_short(policy):
    """Serialize a compact escalation policy object."""
    if not policy:
        return None

    team = policy.team if getattr(policy, "team_id", None) else None

    return {
        "id": policy.id,
        "name": policy.name,
        "team_id": team.id if team else None,
        "team_slug": team.slug if team else None,
        "team_name": team.name if team else None,
        "enabled": policy.enabled,
    }


def serialize_rotation(rotation, current_user=None, request_user=None):
    """Serialize a rotation.

    current_user is the current on-call user.
    request_user is the authenticated user used for permissions.
    """
    data = {
        "id": rotation.id,
        "team_id": rotation.team.id,
        "team_name": rotation.team.name,
        "team_slug": rotation.team.slug,
        "name": rotation.name,
        "description": rotation.description,
        "start_at": rotation.start_at.isoformat(),
        "duration_seconds": rotation.duration_seconds,
        "reminder_interval_seconds": rotation.reminder_interval_seconds,
        "rotation_type": rotation.rotation_type,
        "interval_value": rotation.interval_value,
        "interval_unit": rotation.interval_unit,
        "handoff_time": rotation.handoff_time,
        "handoff_weekday": rotation.handoff_weekday,
        "timezone": rotation.timezone,
        "enabled": rotation.enabled,
        "current_oncall": current_user.username if current_user else None,
    }

    return attach_team_permissions(data, rotation.team.id, request_user)


def serialize_rotation_layer(layer, current_user=None):
    """Serialize a rotation layer."""
    team_id = layer.rotation.team.id

    data = {
        "id": layer.id,
        "rotation_id": layer.rotation.id,
        "team_id": team_id,
        "name": layer.name,
        "description": layer.description,
        "priority": layer.priority,
        "start_at": layer.start_at.isoformat() if layer.start_at else None,
        "duration_seconds": layer.duration_seconds,
        "rotation_type": layer.rotation_type,
        "interval_value": layer.interval_value,
        "interval_unit": layer.interval_unit,
        "handoff_time": layer.handoff_time,
        "handoff_weekday": layer.handoff_weekday,
        "timezone": layer.timezone,
        "enabled": layer.enabled,
        "deleted": layer.deleted,
    }

    return attach_team_permissions(data, team_id, current_user)


def serialize_rotation_layer_member(member):
    """Serialize a rotation layer member."""
    return {
        "id": member.id,
        "layer_id": member.layer.id,
        "user_id": member.user.id,
        "username": member.user.username,
        "display_name": member.user.display_name,
        "position": member.position,
        "active": member.active,
        "starts_at": serialize_utc_datetime(member.starts_at),
        "ends_at": serialize_utc_datetime(member.ends_at),
    }


def serialize_rotation_layer_restriction(item):
    """Serialize a rotation layer restriction."""
    return {
        "id": item.id,
        "layer_id": item.layer.id,
        "weekday": item.weekday,
        "start_time": item.start_time,
        "end_time": item.end_time,
    }
