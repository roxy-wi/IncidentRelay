from flask import has_request_context, jsonify, request

from app.api.schemas.roles import (
    GROUP_EDITOR_ROLE,
    GROUP_USER_ADMIN_ROLE,
    GROUP_VIEWER_ROLE,
    TEAM_MANAGER_ROLE,
    TEAM_RESPONDER_ROLE,
    TEAM_VIEWER_ROLE,
)
from app.modules.db import groups_repo, teams_repo

GROUP_READ_ROLES = {GROUP_VIEWER_ROLE, GROUP_EDITOR_ROLE, GROUP_USER_ADMIN_ROLE}
GROUP_WRITE_ROLES = {
    GROUP_EDITOR_ROLE,
    GROUP_USER_ADMIN_ROLE,
}
GROUP_USER_ADMIN_ROLES = {GROUP_USER_ADMIN_ROLE}

TEAM_READ_ROLES = {TEAM_VIEWER_ROLE, TEAM_RESPONDER_ROLE, TEAM_MANAGER_ROLE}
TEAM_RESPOND_ROLES = {TEAM_RESPONDER_ROLE, TEAM_MANAGER_ROLE}
TEAM_WRITE_ROLES = {TEAM_MANAGER_ROLE}


def current_user():
    """Return the current request user."""

    if not has_request_context():
        return None

    return getattr(request, "current_user", None)


def current_api_token():
    """Return the current request API token."""

    if not has_request_context():
        return None

    return getattr(request, "current_api_token", None)


def is_admin_user(user=None):
    """Return True when the current principal is an administrator."""
    user = user or current_user()
    return bool(user and user.is_admin)


def token_group_filter(group_ids):
    """Apply group restriction from the current API token."""
    api_token = current_api_token()
    if not api_token or not api_token.group_id:
        return group_ids

    return [
        group_id
        for group_id in group_ids
        if group_id == api_token.group_id
    ]


def get_allowed_group_ids(user=None, write_required=False, manage_users_required=False, use_active_group=False):
    """Return group ids available to a user or personal API token.

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

    groups = groups_repo.list_groups_for_user(
        user,
        write_required=write_required,
        manage_users_required=manage_users_required,
    )
    group_ids = [group.id for group in groups]

    if use_active_group and user.active_group_id and user.active_group_id in group_ids:
        return token_group_filter([user.active_group_id])
    return token_group_filter(group_ids)


def get_allowed_team_ids(
    user=None,
    write_required=False,
    respond_required=False,
    use_active_group=True,
    active_only=True,
):
    """
    Return team ids available to a user.
    """
    user = user or current_user()
    group_ids = get_allowed_group_ids(
        user=user,
        write_required=False,
        use_active_group=use_active_group,
    )
    if not group_ids:
        return []

    if not user:
        return [
            team.id
            for team in teams_repo.list_teams(
                active_only=active_only,
                group_ids=group_ids,
            )
        ]

    if user.is_admin:
        return [
            team.id
            for team in teams_repo.list_teams(
                active_only=active_only,
                group_ids=group_ids,
            )
        ]

    managed_group_ids = get_managed_group_ids(
        user=user,
        use_active_group=use_active_group,
    )

    managed_team_ids = {
        team.id
        for team in teams_repo.list_teams(
            active_only=active_only,
            group_ids=managed_group_ids,
        )
    }

    roles = TEAM_READ_ROLES
    if write_required:
        roles = TEAM_WRITE_ROLES
    elif respond_required:
        roles = TEAM_RESPOND_ROLES

    member_team_ids = {
        team.id
        for team in teams_repo.list_teams_for_user(
            user.id,
            roles=roles,
            group_ids=group_ids,
            active_only=active_only,
        )
    }

    return sorted(managed_team_ids | member_team_ids)


def get_allowed_oncall_team_ids(
    user=None,
    use_active_group=True,
    active_only=True,
):
    """
    Return team ids whose on-call schedule is visible to a user.

    This is intentionally broader than get_allowed_team_ids():
    group members may view on-call schedules for all teams in their groups,
    but they still cannot read or edit team resources without team membership.
    """

    user = user or current_user()

    group_ids = get_allowed_group_ids(
        user=user,
        write_required=False,
        manage_users_required=False,
        use_active_group=use_active_group,
    )

    if not group_ids:
        return []

    return [
        team.id
        for team in teams_repo.list_teams(
            active_only=active_only,
            group_ids=group_ids,
        )
    ]


def can_read_group(user, group_id):
    """Return True when a user can read a group."""
    if not user:
        return False
    if user.is_admin:
        return True
    return groups_repo.get_user_group_role(user.id, group_id) in GROUP_READ_ROLES


def can_write_group(user, group_id):
    """Return True when a user can create/edit group operational resources."""
    if not user:
        return False
    if user.is_admin:
        return True
    return groups_repo.get_user_group_role(user.id, group_id) in GROUP_WRITE_ROLES


def can_manage_group_users(user, group_id):
    """Return True when a user can manage users inside the group boundary."""
    if not user:
        return False
    if user.is_admin:
        return True
    return groups_repo.get_user_group_role(user.id, group_id) in GROUP_USER_ADMIN_ROLES


def can_read_team(user, team_id):
    """
    Return True when a user can read a team.
    """
    if not user:
        return False
    if user.is_admin:
        return True

    team = teams_repo.get_team(team_id)
    if not team or not team.group_id:
        return False
    if can_manage_group_users(user, team.group_id):
        return True
    if not can_read_group(user, team.group_id):
        return False
    return teams_repo.get_user_team_role(user.id, team_id) in TEAM_READ_ROLES


def can_view_team_oncall(user, team_id):
    """Return True when user can view on-call schedule for a team."""

    if not user:
        return False

    if user.is_admin:
        return True

    team = teams_repo.get_team(team_id)

    if not team or not team.group_id:
        return False

    return can_read_group(user, team.group_id)


def can_respond_team(user, team_id):
    """Return True when a user can acknowledge or resolve alerts for a team."""
    if not user:
        return False
    if user.is_admin:
        return True

    team = teams_repo.get_team(team_id)
    if not team.group_id:
        return False
    if not can_read_group(user, team.group_id):
        return False
    return teams_repo.get_user_team_role(user.id, team_id) in TEAM_RESPOND_ROLES


def can_write_team(user, team_id):
    """Return True when a user can write team resources."""
    if not user:
        return False

    if user.is_admin:
        return True

    team = teams_repo.get_team(team_id)
    if not team or not team.group_id:
        return False

    if not can_read_group(user, team.group_id):
        return False

    if can_manage_group_users(user, team.group_id):
        return True

    return teams_repo.get_user_team_role(user.id, team_id) in TEAM_WRITE_ROLES


def can_access_team_or_group_resource(user, team_id, write_required=False):
    """Return True when a user can access a team-owned operational resource.

    Used for resources such as notification channels and silences:
    - team members keep their normal team-level permissions;
    - group editors/admins can manage operational resources in their group;
    - this does not make group editors team writers.
    """
    if not user:
        return False

    if write_required:
        if can_write_team(user, team_id):
            return True
    else:
        if can_read_team(user, team_id):
            return True

    team = teams_repo.get_team(team_id)
    if not team or not team.group_id:
        return False

    return can_write_group(user, team.group_id)


def get_allowed_team_or_group_resource_ids(
    user=None,
    write_required=False,
    use_active_group=True,
    active_only=True,
):
    """Return team ids available for team-owned operational resources."""
    user = user or current_user()

    team_ids = set(
        get_allowed_team_ids(
            user=user,
            write_required=write_required,
            use_active_group=use_active_group,
            active_only=active_only,
        )
    )

    group_ids = get_allowed_group_ids(
        user=user,
        write_required=True,
        use_active_group=use_active_group,
    )

    team_ids.update(
        team.id
        for team in teams_repo.list_teams(
            active_only=active_only,
            group_ids=group_ids,
        )
    )

    return sorted(team_ids)


def require_team_or_group_resource_access(team_id, write_required=False):
    """Return an error response when user cannot access an operational resource."""
    if is_admin_user():
        return None

    if can_access_team_or_group_resource(
        current_user(),
        team_id,
        write_required=write_required,
    ):
        return None

    if write_required:
        return jsonify({
            "error": "team_or_group_write_required",
            "message": "Team manager or group editor role is required for this team",
        }), 403

    return jsonify({
        "error": "team_or_group_access_denied",
        "message": "Access to this team resource is denied",
    }), 403


def require_admin_user():
    """Return an error response when current user is not an admin."""
    user = current_user()
    if not user or not user.is_admin:
        return jsonify({
            "error": "admin_required",
            "message": "Admin role is required",
        }), 403

    return None


def require_group_write(group_id):
    """Return an error response when current user cannot write group resources."""
    if is_admin_user():
        return None
    if not can_write_group(current_user(), group_id):
        return jsonify({
            "error": "group_write_required",
            "message": "Group editor or group admin role is required for this group",
        }), 403

    return None


def require_group_user_admin(group_id):
    """Return an error response when current user cannot manage group users."""
    if is_admin_user():
        return None
    if not can_manage_group_users(current_user(), group_id):
        return jsonify({"error": "Group user admin role is required for this group"}), 403
    return None


def require_team_read(team_id):
    """Return an error response when current user cannot read a team."""
    if is_admin_user():
        return None
    if not can_read_team(current_user(), team_id):
        return jsonify({"error": "Access to this team is denied"}), 403
    return None


def require_team_oncall_read(team_id):
    """Return an error response when current user cannot view team on-call schedule."""

    if is_admin_user():
        return None

    if not can_view_team_oncall(current_user(), team_id):
        return jsonify({
            "error": "team_oncall_access_denied",
            "message": "Access to this team on-call schedule is denied",
        }), 403

    return None


def require_team_respond(team_id):
    """Return an error response when current user cannot operate team alerts."""
    if is_admin_user():
        return None
    if not can_respond_team(current_user(), team_id):
        return jsonify({"error": "Team responder role is required for this team"}), 403
    return None


def require_team_write(team_id):
    """Return an error response when current user cannot write team resources."""
    if is_admin_user():
        return None
    if not can_write_team(current_user(), team_id):
        return jsonify({"error": "Team manager role is required for this team"}), 403
    return None


def parse_date_or_datetime(value):
    """Parse an ISO date or datetime string."""
    from datetime import datetime, time

    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.combine(datetime.strptime(value, "%Y-%m-%d").date(), time.min)


def get_managed_group_ids(user=None, use_active_group=True):
    """
    Return groups where the user can manage users.
    """
    return get_allowed_group_ids(
        user=user,
        manage_users_required=True,
        use_active_group=use_active_group,
    )


def require_user_management_access():
    """
    Return an error response when current user cannot manage users.
    """
    user = current_user()

    if not user:
        return jsonify({"error": "Authentication is required"}), 401

    if user.is_admin:
        return None

    if get_allowed_group_ids(user=user, manage_users_required=True):
        return None

    return jsonify({"error": "Group Admin role is required"}), 403


def get_group_permissions(user, group_id):
    """Return group-level permissions for a user."""
    return {
        "can_read": can_read_group(user, group_id),
        "can_write": can_write_group(user, group_id),
        "can_manage_users": can_manage_group_users(user, group_id),
    }


def get_team_permissions(user, team_id):
    """Return team-level permissions for a user."""
    return {
        "can_read": can_read_team(user, team_id),
        "can_write": can_write_team(user, team_id),
        "can_respond": can_respond_team(user, team_id),
        "can_manage_users": can_manage_team_users(user, team_id),
        "can_view_oncall": can_view_team_oncall(user, team_id),
    }


def is_global_admin_user(user=None):
    """Return true when user is a global administrator."""
    if user is None:
        user = current_user()

    return bool(user and user.is_admin)


def can_assign_group_role(role, user=None):
    """Return true when user can assign selected group role."""
    if is_global_admin_user(user):
        return True

    return role != GROUP_USER_ADMIN_ROLE


def can_manage_team_users(user, team_id):
    """Return True when a user can manage team membership."""
    if not user:
        return False

    if user.is_admin:
        return True

    team = teams_repo.get_team(team_id)

    if not team or not team.group_id:
        return False

    if can_manage_group_users(user, team.group_id):
        return True

    if not can_read_group(user, team.group_id):
        return False

    return teams_repo.get_user_team_role(user.id, team_id) == TEAM_MANAGER_ROLE


def require_assign_group_role(role):
    """Return an error response when current user cannot assign selected role."""
    if can_assign_group_role(role):
        return None

    return jsonify({
        "error": "role_not_allowed",
        "message": "Only global admin can assign group user-admin role",
    }), 403


def require_team_user_admin(team_id):
    """Return an error response when current user cannot manage team users."""
    if is_admin_user():
        return None

    if not can_manage_team_users(current_user(), team_id):
        return jsonify({
            "error": "team_user_admin_required",
            "message": "Team manager or group admin role is required for this team",
        }), 403

    return None
