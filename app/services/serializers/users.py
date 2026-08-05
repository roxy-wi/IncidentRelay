def serialize_user_group(membership):
    """
    Serialize a group membership.
    """

    return {
        "id": membership.id,
        "group_id": membership.group.id,
        "group_slug": membership.group.slug,
        "group_name": membership.group.name,
        "role": membership.role,
        "active": membership.active,
    }


def serialize_user(user, groups=None):
    """
    Serialize a user.
    """

    data = {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "phone": user.phone,
        "timezone": user.timezone,
        "locale": getattr(user, "locale", None),
        "theme": getattr(user, "theme", "system") or "system",
        "telegram_user_id": user.telegram_user_id,
        "slack_user_id": user.slack_user_id,
        "mattermost_user_id": user.mattermost_user_id,
        "active": user.active,
        "is_admin": user.is_admin,
        "active_group_id": user.active_group.id if user.active_group else None,
        "active_group_slug": user.active_group.slug if user.active_group else None,
        "notify_oncall_shift_start_email": bool(
            getattr(user, "notify_oncall_shift_start_email", True)
        ),
        "notify_oncall_shift_end_email": bool(
            getattr(user, "notify_oncall_shift_end_email", True)
        ),
        "notify_oncall_shift_start_mattermost": bool(
            getattr(user, "notify_oncall_shift_start_mattermost", True)
        ),
    }

    if groups is not None:
        data["groups"] = [serialize_profile_group(item) for item in groups]

    return data


def serialize_user_short(user):
    """
    Serialize a compact user object.
    """

    if not user:
        return None

    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "telegram_user_id": user.telegram_user_id,
        "slack_user_id": user.slack_user_id,
        "mattermost_user_id": user.mattermost_user_id,
    }


def serialize_profile_group(item):
    """Serialize a real UserGroup membership or a synthetic profile group."""
    if isinstance(item, dict):
        return item

    return serialize_user_group(item)
