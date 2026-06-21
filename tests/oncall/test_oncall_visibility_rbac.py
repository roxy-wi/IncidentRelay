from app.services import rbac
from tests.factories import (
    add_user_to_team,
    create_group,
    create_team,
    create_user,
)


def test_group_viewer_can_view_oncall_for_team_without_team_membership(db):
    group = create_group()
    team = create_team(group)

    viewer = create_user(
        "viewer",
        group,
        group_role="viewer",
    )

    assert rbac.can_view_team_oncall(viewer, team.id) is True
    assert rbac.can_read_team(viewer, team.id) is False
    assert rbac.can_write_team(viewer, team.id) is False


def test_group_editor_can_view_oncall_for_team_without_team_membership(db):
    group = create_group()
    team = create_team(group)

    editor = create_user(
        "editor",
        group,
        group_role="editor",
    )

    assert rbac.can_view_team_oncall(editor, team.id) is True
    assert rbac.can_read_team(editor, team.id) is False
    assert rbac.can_write_team(editor, team.id) is False


def test_team_member_can_still_read_own_team_resources(db):
    group = create_group()
    team = create_team(group)

    user = create_user(
        "alice",
        group,
        group_role="viewer",
    )

    add_user_to_team(team, user, role="viewer")

    assert rbac.can_view_team_oncall(user, team.id) is True
    assert rbac.can_read_team(user, team.id) is True
    assert rbac.can_write_team(user, team.id) is False


def test_get_allowed_oncall_team_ids_returns_all_group_teams_for_group_member(db):
    group = create_group()

    own_team = create_team(group, slug="own")
    other_team = create_team(group, slug="other")

    user = create_user(
        "alice",
        group,
        group_role="viewer",
    )

    add_user_to_team(own_team, user, role="viewer")

    team_ids = rbac.get_allowed_oncall_team_ids(
        user=user,
        use_active_group=False,
    )

    assert set(team_ids) == {own_team.id, other_team.id}


def test_get_team_permissions_contains_separate_oncall_permission(db):
    group = create_group()
    team = create_team(group)

    viewer = create_user(
        "viewer",
        group,
        group_role="viewer",
    )

    permissions = rbac.get_team_permissions(viewer, team.id)

    assert permissions["can_view_oncall"] is True
    assert permissions["can_read"] is False
    assert permissions["can_write"] is False
    assert permissions["can_respond"] is False
    assert permissions["can_manage_users"] is False
