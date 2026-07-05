from app.modules.common import as_utc_aware, as_naive_datetime


def serialize_utc_datetime(value):
    """Serialize a datetime/string value as an explicit UTC ISO-8601 string."""
    value = as_utc_aware(value)

    if not value:
        return None

    return value.isoformat().replace("+00:00", "Z")


def serialize_local_datetime(value):
    """Serialize a local wall-clock datetime without timezone conversion."""
    value = as_naive_datetime(value)

    if not value:
        return None

    return value.isoformat()


def attach_group_permissions(data, group_id, current_user=None):
    """Attach group permissions to serialized data."""
    if current_user and group_id:
        from app.services.rbac import get_group_permissions

        data["permissions"] = get_group_permissions(current_user, group_id)

    return data


def attach_team_permissions(data, team_id, current_user=None):
    """Attach team permissions to serialized data."""
    if current_user and team_id:
        from app.services.rbac import (
            get_team_permissions,
            can_access_team_or_group_resource,
            can_respond_team,
            is_admin_user,
        )

        permissions = get_team_permissions(current_user, team_id)
        permissions["can_write_resources"] = can_access_team_or_group_resource(
            current_user,
            team_id,
            write_required=True,
        )

        permissions["can_create_manual_incident"] = (
            is_admin_user(current_user)
            or can_respond_team(current_user, team_id)
            or permissions["can_write_resources"]
        )

        data["permissions"] = permissions

    return data
