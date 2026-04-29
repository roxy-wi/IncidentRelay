from flask import jsonify, request

from app.modules.db import groups_repo, teams_repo


READ_ONLY_ROLE = "read_only"
RW_ROLE = "rw"


def current_user():
    """
    Return the current request user.

    Personal API tokens set request.current_user to the token owner.
    """

    return getattr(request, "current_user", None)


def current_api_token():
    """
    Return the current request API token.
    """

    return getattr(request, "current_api_token", None)


def is_admin_user(user=None):
    """
    Return True when the current principal is an administrator.
    """

    user = user or current_user()
    return bool(user and user.is_admin)


def token_group_filter(group_ids):
    """
    Apply group restriction from the current API token.

    Web UI uses JWT and is never restricted by this helper. Personal API tokens
    can optionally be bound to one group.
    """

    api_token = current_api_token()

    if not api_token or not api_token.group_id:
        return group_ids

    return [group_id for group_id in group_ids if group_id == api_token.group_id]


def get_allowed_group_ids(user=None, write_required=False, use_active_group=False):
    """
    Return group ids available to a user or personal API token.

    Active group is a UI filter, not a security boundary. If the selected active
    group is stale or inactive, it is ignored.
    """

    user = user or current_user()

    if not user:
        api_token = current_api_token()

        if api_token and api_token.group_id:
            return [api_token.group_id]

        return []

    if user.is_admin:
        groups = groups_repo.list_groups(active_only=True)
        group_ids = [group.id for group in groups]
        return token_group_filter(group_ids)

    groups = groups_repo.list_groups_for_user(user, write_required=write_required)
    group_ids = [group.id for group in groups]

    if use_active_group and user.active_group_id and user.active_group_id in group_ids:
        return token_group_filter([user.active_group_id])

    return token_group_filter(group_ids)


def get_allowed_team_ids(user=None, write_required=False, use_active_group=True):
    """
    Return team ids available to a user.
    """

    group_ids = get_allowed_group_ids(
        user=user,
        write_required=write_required,
        use_active_group=use_active_group,
    )

    if not group_ids:
        return []

    return [team.id for team in teams_repo.list_teams(active_only=True, group_ids=group_ids)]

def can_read_group(user, group_id):
    """
    Return True when a user can read a group.
    """

    if not user:
        return False

    if user.is_admin:
        return True

    return groups_repo.get_user_group_role(user.id, group_id) in (READ_ONLY_ROLE, RW_ROLE)


def can_write_group(user, group_id):
    """
    Return True when a user can write to a group.
    """

    if not user:
        return False

    if user.is_admin:
        return True

    return groups_repo.get_user_group_role(user.id, group_id) == RW_ROLE


def can_read_team(user, team_id):
    """
    Return True when a user can read a team.
    """

    team = teams_repo.get_team(team_id)

    if not team.group_id:
        return bool(user and user.is_admin)

    return can_read_group(user, team.group_id)


def can_write_team(user, team_id):
    """
    Return True when a user can write to a team.
    """

    team = teams_repo.get_team(team_id)

    if not team.group_id:
        return bool(user and user.is_admin)

    return can_write_group(user, team.group_id)


def require_admin_user():
    """
    Return an error response when current user is not an admin.
    """

    user = current_user()

    if not user or not user.is_admin:
        return jsonify({"error": "Admin role is required"}), 403

    return None


def require_group_write(group_id):
    """
    Return an error response when current user cannot write a group.
    """

    if is_admin_user():
        return None

    if not can_write_group(current_user(), group_id):
        return jsonify({"error": "RW role is required for this group"}), 403

    return None


def require_team_read(team_id):
    """
    Return an error response when current user cannot read a team.
    """

    if is_admin_user():
        return None

    if not can_read_team(current_user(), team_id):
        return jsonify({"error": "Access to this team is denied"}), 403

    return None


def require_team_write(team_id):
    """
    Return an error response when current user cannot write a team.
    """

    if is_admin_user():
        return None

    if not can_write_team(current_user(), team_id):
        return jsonify({"error": "RW role is required for this team"}), 403

    return None


def require_permission(permission):
    """
    Backward-compatible permission decorator.

    Older views import this function. The current RBAC model is group-based:
    read permissions require an authenticated user, write permissions require
    RW role in at least one group, and admin permissions require is_admin.
    """

    def decorator(func):
        from functools import wraps

        @wraps(func)
        def wrapper(*args, **kwargs):
            user = current_user()

            if not user:
                return jsonify({"error": "Authentication is required"}), 401

            if user.is_admin:
                return func(*args, **kwargs)

            if permission.startswith("admin:"):
                return jsonify({"error": "Admin role is required"}), 403

            if permission.endswith(":write") or permission in ("write", "rw"):
                if not get_allowed_group_ids(user, write_required=True):
                    return jsonify({"error": "RW role is required"}), 403

            return func(*args, **kwargs)

        return wrapper

    return decorator


def require_any_permission(*permissions):
    """
    Backward-compatible decorator for views that accept several permissions.
    """

    def decorator(func):
        from functools import wraps

        @wraps(func)
        def wrapper(*args, **kwargs):
            user = current_user()

            if not user:
                return jsonify({"error": "Authentication is required"}), 401

            if user.is_admin:
                return func(*args, **kwargs)

            for permission in permissions:
                if permission.startswith("admin:"):
                    continue

                if permission.endswith(":write") or permission in ("write", "rw"):
                    if get_allowed_group_ids(user, write_required=True):
                        return func(*args, **kwargs)
                else:
                    if get_allowed_group_ids(user, write_required=False):
                        return func(*args, **kwargs)

            return jsonify({"error": "Permission denied"}), 403

        return wrapper

    return decorator


def parse_date_or_datetime(value):
    """
    Parse an ISO date or datetime string.

    This helper is kept here for backward compatibility with older imports.
    New code should keep date parsing close to the view or service that uses it.
    """

    from datetime import datetime, time

    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.combine(datetime.strptime(value, "%Y-%m-%d").date(), time.min)
