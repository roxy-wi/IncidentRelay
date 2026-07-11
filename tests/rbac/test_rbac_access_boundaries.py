from app.api.schemas.roles import (
    GROUP_EDITOR_ROLE,
    GROUP_USER_ADMIN_ROLE,
    GROUP_VIEWER_ROLE,
    TEAM_MANAGER_ROLE,
)
from app.modules.db import groups_repo
from app.services.rbac import (
    can_access_team_or_group_resource,
    can_assign_group_role,
    can_manage_team_users,
    can_read_team,
    can_view_team_oncall,
    can_write_team,
    get_allowed_group_ids,
    get_allowed_oncall_team_ids,
    get_allowed_team_ids,
)
from tests.factories import add_user_to_team, create_group, create_team, create_user


def test_group_editor_can_manage_operational_resources_without_team_membership(db):
    group = create_group()
    user = create_user(group=group, group_role=GROUP_EDITOR_ROLE)
    team = create_team(group)

    assert can_read_team(user, team.id) is False
    assert can_write_team(user, team.id) is False
    assert can_access_team_or_group_resource(user, team.id) is True
    assert can_access_team_or_group_resource(user, team.id, write_required=True) is True


def test_group_viewer_can_view_oncall_but_cannot_read_unjoined_team(db):
    group = create_group()
    user = create_user(group=group, group_role=GROUP_VIEWER_ROLE)
    team = create_team(group)

    assert can_view_team_oncall(user, team.id) is True
    assert can_read_team(user, team.id) is False
    assert get_allowed_oncall_team_ids(user=user) == [team.id]
    assert get_allowed_team_ids(user=user) == []


def test_team_manager_membership_grants_team_resource_access_to_group_viewer(db):
    group = create_group()
    user = create_user(group=group, group_role=GROUP_VIEWER_ROLE)
    team = create_team(group)

    add_user_to_team(team, user, TEAM_MANAGER_ROLE)

    assert can_read_team(user, team.id) is True
    assert can_write_team(user, team.id) is True
    assert can_manage_team_users(user, team.id) is True
    assert can_access_team_or_group_resource(user, team.id) is True
    assert can_access_team_or_group_resource(user, team.id, write_required=True) is True


def test_group_user_admin_can_manage_team_users_without_team_membership(db):
    group = create_group()
    user = create_user(group=group, group_role=GROUP_USER_ADMIN_ROLE)
    team = create_team(group)

    assert can_read_team(user, team.id) is True
    assert can_write_team(user, team.id) is True
    assert can_manage_team_users(user, team.id) is True


def test_active_group_filter_does_not_grant_unrelated_group_access(db):
    first_group = create_group()
    second_group = create_group()
    unrelated_group = create_group()
    user = create_user(group=first_group, group_role=GROUP_VIEWER_ROLE)

    groups_repo.add_user_to_group(user.id, second_group.id, GROUP_VIEWER_ROLE)
    user.active_group = unrelated_group
    user.save()

    allowed = set(get_allowed_group_ids(user=user, use_active_group=True))

    assert allowed == {first_group.id, second_group.id}
    assert unrelated_group.id not in allowed


def test_active_group_filter_limits_to_selected_membership_when_valid(db):
    first_group = create_group()
    second_group = create_group()
    user = create_user(group=first_group, group_role=GROUP_VIEWER_ROLE)

    groups_repo.add_user_to_group(user.id, second_group.id, GROUP_VIEWER_ROLE)
    user.active_group = second_group
    user.save()

    assert get_allowed_group_ids(user=user, use_active_group=True) == [second_group.id]
    assert set(get_allowed_group_ids(user=user, use_active_group=False)) == {
        first_group.id,
        second_group.id,
    }


def test_non_admin_cannot_assign_group_user_admin_role(db):
    group = create_group()
    group_admin = create_user(group=group, group_role=GROUP_USER_ADMIN_ROLE)
    global_admin = create_user(is_admin=True)

    assert can_assign_group_role(GROUP_VIEWER_ROLE, user=group_admin) is True
    assert can_assign_group_role(GROUP_EDITOR_ROLE, user=group_admin) is True
    assert can_assign_group_role(GROUP_USER_ADMIN_ROLE, user=group_admin) is False
    assert can_assign_group_role(GROUP_USER_ADMIN_ROLE, user=global_admin) is True
