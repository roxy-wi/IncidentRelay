from functools import reduce
from operator import or_

from peewee import fn

from app.modules.db.models import (
    ApiToken,
    RotationLayerMember,
    RotationMember,
    RotationOverride,
    TeamUser,
    User,
    UserGroup,
    UserRole,
)
from app.modules.common import utc_now


DEFAULT_USERS_PAGE_SIZE = 25
MAX_USERS_PAGE_SIZE = 100


def _normalize_page(value):
    try:
        return max(1, int(value or 1))
    except (TypeError, ValueError):
        return 1


def _normalize_page_size(value):
    try:
        page_size = int(value or DEFAULT_USERS_PAGE_SIZE)
    except (TypeError, ValueError):
        page_size = DEFAULT_USERS_PAGE_SIZE

    return min(MAX_USERS_PAGE_SIZE, max(1, page_size))


def _build_user_search_condition(search):
    """Build a simple user search condition."""
    search = str(search or "").strip()

    if not search:
        return None

    pattern = f"%{search.lower()}%"
    conditions = [
        fn.LOWER(User.username) % pattern,
        fn.LOWER(User.display_name) % pattern,
        fn.LOWER(User.email) % pattern,
        fn.LOWER(User.phone) % pattern,
        fn.LOWER(User.telegram_user_id) % pattern,
        fn.LOWER(User.slack_user_id) % pattern,
        fn.LOWER(User.mattermost_user_id) % pattern,
    ]

    if search.isdigit():
        conditions.append(User.id == int(search))

    return reduce(or_, conditions)


def apply_user_search(query, search=None):
    """Apply search filter to a user query."""
    condition = _build_user_search_condition(search)

    if condition is None:
        return query

    return query.where(condition)


def build_all_users_query(active_only=False, include_deleted=False):
    """Build query for all users."""
    query = User.select().order_by(User.id.asc())

    if not include_deleted:
        query = query.where(User.deleted == False)

    if active_only:
        query = query.where(User.active == True)

    return query


def build_users_by_group_ids_query(group_ids, active_only=True):
    """Build query for unique users from provided group ids."""
    if not group_ids:
        return None

    query = (
        User
        .select()
        .join(UserGroup)
        .where(
            (UserGroup.group.in_(group_ids))
            & (UserGroup.active == True)
            & (User.deleted == False)
        )
        .distinct()
        .order_by(User.id.asc())
    )

    if active_only:
        query = query.where(User.active == True)

    return query


def paginate_user_query(query, page=1, page_size=DEFAULT_USERS_PAGE_SIZE, search=None):
    """Paginate a user query and return items, pagination metadata and summary."""
    page = _normalize_page(page)
    page_size = _normalize_page_size(page_size)

    if query is None:
        return {
            "items": [],
            "pagination": {
                "page": 1,
                "page_size": page_size,
                "total_items": 0,
                "total_pages": 1,
                "from": 0,
                "to": 0,
                "has_prev": False,
                "has_next": False,
            },
            "summary": {
                "total": 0,
                "active": 0,
                "inactive": 0,
                "admins": 0,
            },
        }

    filtered_query = apply_user_search(query, search)
    count_query = filtered_query.order_by()

    total_items = count_query.count()
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    page = min(page, total_pages)

    if total_items:
        page_from = ((page - 1) * page_size) + 1
        page_to = min(page * page_size, total_items)
    else:
        page_from = 0
        page_to = 0

    active_count = count_query.where(User.active == True).count()
    admin_count = count_query.where(User.is_admin == True).count()

    return {
        "items": list(filtered_query.paginate(page, page_size)),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": total_pages,
            "from": page_from,
            "to": page_to,
            "has_prev": page > 1,
            "has_next": page < total_pages,
        },
        "summary": {
            "total": total_items,
            "active": active_count,
            "inactive": total_items - active_count,
            "admins": admin_count,
        },
    }


def list_users_by_group_ids(group_ids, active_only=True):
    """
    Return unique users that belong to one of the provided groups.

    Args:
        group_ids: List of group ids available to the current user.
        active_only: If True, return only active users.

    Returns:
        list[User]: Users ordered by id.
    """
    query = build_users_by_group_ids_query(group_ids, active_only=active_only)

    if query is None:
        return []

    return list(query)


def list_users(group_ids=None, include_deleted=False):
    """
    Return users ordered by id.
    """
    if group_ids is not None:
        return list_users_by_group_ids(group_ids, active_only=True)

    return list(build_all_users_query(include_deleted=include_deleted))


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
    """ Update a user."""
    user = get_user(user_id)
    for field in [
        "username",
        "display_name",
        "email",
        "phone",
        "timezone",
        "locale",
        "theme",
        "telegram_user_id",
        "slack_user_id",
        "mattermost_user_id",
        "notify_oncall_shift_start_email",
        "notify_oncall_shift_end_email",
        "notify_oncall_shift_start_mattermost",
        "active",
        "is_admin",
        "password_hash",
    ]:
        if field in data:
            setattr(user, field, data[field])
    user.save()
    return user


def get_user_or_none(user_id, include_deleted=False):
    """
    Return one user or None.
    """
    query = User.select().where(User.id == user_id)

    if not include_deleted:
        query = query.where(User.deleted == False)

    return query.get_or_none()


def soft_delete_user(user_id):
    """
    Soft-delete a user and revoke access-related records.

    This does not physically delete the user row, so historical alert references
    remain safe. The user is removed from active memberships and rotations, and
    personal API tokens are revoked.

    Returns:
        User | None: Removed user or None if user was not found.
    """
    user = get_user_or_none(user_id)

    if not user:
        return None

    now = utc_now()
    database = User._meta.database

    if user.is_admin and user.active and count_active_admins(exclude_user_id=user.id) == 0:
        raise ValueError("Cannot remove the last active admin user")

    with database.atomic():
        UserGroup.delete().where(UserGroup.user == user.id).execute()
        TeamUser.delete().where(TeamUser.user == user.id).execute()
        RotationLayerMember.delete().where(RotationLayerMember.user == user.id).execute()
        RotationOverride.delete().where(RotationOverride.user == user.id).execute()
        RotationMember.delete().where(RotationMember.user == user.id).execute()
        RotationOverride.delete().where(RotationOverride.user == user.id).execute()
        UserRole.delete().where(UserRole.user == user.id).execute()
        ApiToken.update(
            active=False,
            deleted=True,
            deleted_at=now,
        ).where(
            (ApiToken.user == user.id)
            & (ApiToken.deleted == False)
        ).execute()

        user.active = False
        user.deleted = True
        user.deleted_at = now
        user.active_group = None
        user.save()

    return user


def get_user_by_mattermost_id(mattermost_user_id):
    """Return a user by Mattermost user id."""
    if not mattermost_user_id:
        return None

    return User.get_or_none(
        (User.mattermost_user_id == mattermost_user_id)
        & (User.deleted == False)
    )


def get_user_by_slack_id(slack_user_id):
    """Return an active user by Slack user id."""
    if not slack_user_id:
        return None

    return User.get_or_none(
        (User.slack_user_id == str(slack_user_id))
        & (User.deleted == False)
        & (User.active == True)
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
    return list(
        build_all_users_query(
            active_only=active_only,
            include_deleted=include_deleted,
        )
    )


def set_active_group(user_id, group_id):
    """
    Set a user's active group.
    """

    user = get_user(user_id)
    user.active_group = group_id
    user.save()
    return user


def count_active_admins(exclude_user_id=None):
    """
    Return count of active non-deleted admin users.

    Args:
        exclude_user_id: Optional user id to exclude from count.

    Returns:
        int: Number of active admin users.
    """
    query = User.select().where(
        (User.is_admin == True)
        & (User.active == True)
        & (User.deleted == False)
    )

    if exclude_user_id:
        query = query.where(User.id != exclude_user_id)

    return query.count()


def get_user_by_telegram_id(telegram_user_id):
    """
    Return a user by Telegram user id.
    """
    if not telegram_user_id:
        return None

    return User.get_or_none(
        (User.telegram_user_id == str(telegram_user_id))
        & (User.deleted == False)
        & (User.active == True)
    )
