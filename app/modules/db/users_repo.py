from datetime import datetime

from app.modules.db.models import User, UserGroup


def list_users_by_group_ids(group_ids, active_only=True):
    """
    Return unique users that belong to one of the provided groups.

    Args:
        group_ids: List of group ids available to the current user.
        active_only: If True, return only active users.

    Returns:
        list[User]: Users ordered by id.
    """
    if not group_ids:
        return []

    query = (
        User
        .select()
        .join(UserGroup)
        .where(
            (UserGroup.group.in_(group_ids)) &
            (UserGroup.active == True) &
            (User.deleted == False)
        )
        .distinct()
        .order_by(User.id.asc())
    )

    if active_only:
        query = query.where(User.active == True)

    return list(query)


def list_users(group_ids=None, include_deleted=False):
    """
    Return users ordered by id.
    """

    query = User.select().order_by(User.id.asc())

    if not include_deleted:
        query = query.where(User.deleted == False)

    if group_ids is not None:
        if not group_ids:
            return []
        query = (
            query
            .join(UserGroup)
            .where(
                (UserGroup.group.in_(group_ids))
                & (UserGroup.active == True)
                & (User.active == True)
                & (User.deleted == False)
            )
            .distinct()
            .order_by(User.id.asc())
        )

    return list(query)


def get_user(user_id, include_deleted=False):
    """
    Return a user by id.
    """

    query = User.select().where(User.id == user_id)

    if not include_deleted:
        query = query.where(User.deleted == False)

    return query.get()


def create_user(**kwargs):
    """
    Create a user.
    """

    return User.create(**kwargs)


def create_user_if_missing(username, **kwargs):
    """
    Create a user if it does not exist.
    """

    user, _ = User.get_or_create(username=username, defaults=kwargs)
    return user


def update_user(user_id, data):
    """
    Update a user.
    """

    user = get_user(user_id)
    for field in [
        "username",
        "display_name",
        "email",
        "phone",
        "telegram_chat_id",
        "slack_user_id",
        "mattermost_user_id",
        "active",
        "is_admin",
        "password_hash",
    ]:
        if field in data:
            setattr(user, field, data[field])
    user.save()
    return user


def disable_user(user_id):
    """
    Disable a user.
    """

    user = get_user(user_id)
    user.active = False
    user.save()
    return user


def soft_delete_user(user_id):
    """
    Soft-delete a user.
    """

    user = get_user(user_id)
    user.active = False
    user.deleted = True
    user.deleted_at = datetime.utcnow()
    user.save()
    return user


def get_user_by_mattermost_id(mattermost_user_id):
    """
    Return a user by Mattermost user id.
    """

    if not mattermost_user_id:
        return None

    return User.get_or_none(
        (User.mattermost_user_id == mattermost_user_id)
        & (User.deleted == False)
    )


def get_user_by_username(username):
    """
    Return a user by username.
    """

    if not username:
        return None

    return User.get_or_none(
        (User.username == username)
        & (User.deleted == False)
    )


def set_user_password(user_id, password_hash):
    """
    Store a password hash for a user.
    """

    user = get_user(user_id)
    user.password_hash = password_hash
    user.save()
    return user


def list_all_users(active_only=False, include_deleted=False):
    """
    Return all users ordered by id.
    """

    query = User.select().order_by(User.id.asc())

    if not include_deleted:
        query = query.where(User.deleted == False)

    if active_only:
        query = query.where(User.active == True)

    return list(query)


def set_active_group(user_id, group_id):
    """
    Set a user's active group.
    """

    user = get_user(user_id)
    user.active_group = group_id
    user.save()
    return user
