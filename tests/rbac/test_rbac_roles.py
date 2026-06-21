from app.api.schemas.roles import (
    GROUP_EDITOR_ROLE,
    GROUP_USER_ADMIN_ROLE,
    GROUP_VIEWER_ROLE,
    TEAM_MANAGER_ROLE,
    TEAM_RESPONDER_ROLE,
    TEAM_VIEWER_ROLE,
)
from app.modules.db.models import User, UserGroup
from app.services.rbac import can_read_team, can_respond_team, can_write_team
from app.views.groups_view import create_group_user
from tests.factories import add_user_to_team, create_group, create_team, create_user, unique


def test_group_user_admin_creates_user_only_in_own_group(app):
    group = create_group()
    group_admin = create_user(group=group, group_role=GROUP_USER_ADMIN_ROLE)

    with app.test_request_context(
        f"/api/groups/{group.id}/users/create",
        method="POST",
        json={
            "username": unique("managed"),
            "password": "strong-password",
            "group_role": GROUP_VIEWER_ROLE,
        },
    ) as _ctx:
        from flask import request

        request.current_user = group_admin
        response, status = create_group_user(group.id)

    assert status == 201
    data = response.get_json()
    user = User.get_by_id(data["id"])
    membership = UserGroup.get(UserGroup.user == user.id, UserGroup.group == group.id)

    assert user.is_admin is False
    assert user.active is True
    assert user.active_group_id == group.id
    assert membership.role == GROUP_VIEWER_ROLE
    assert membership.active is True


def test_group_user_admin_cannot_override_group_or_is_admin(app):
    group = create_group()
    other_group = create_group()
    group_admin = create_user(group=group, group_role=GROUP_USER_ADMIN_ROLE)

    for forbidden_payload in (
        {
            "username": unique("managed"),
            "password": "strong-password",
            "group_id": other_group.id,
        },
        {
            "username": unique("managed"),
            "password": "strong-password",
            "is_admin": True,
        },
    ):
        with app.test_request_context(
            f"/api/groups/{group.id}/users/create",
            method="POST",
            json=forbidden_payload,
        ):
            from flask import request

            request.current_user = group_admin
            response, status = create_group_user(group.id)

        assert status == 400
        assert response.get_json()["error"] == "validation_error"


def test_group_editor_without_team_membership_cannot_write_team():
    group = create_group()
    user = create_user(group=group, group_role=GROUP_EDITOR_ROLE)
    team = create_team(group)

    assert can_write_team(user, team.id) is False


def test_team_manager_can_write_with_group_viewer_role():
    group = create_group()
    user = create_user(group=group, group_role=GROUP_VIEWER_ROLE)
    team = create_team(group)
    add_user_to_team(team, user, TEAM_MANAGER_ROLE)

    assert can_read_team(user, team.id) is True
    assert can_respond_team(user, team.id) is True
    assert can_write_team(user, team.id) is True


def test_team_responder_can_ack_resolve_but_cannot_manage_team():
    group = create_group()
    user = create_user(group=group, group_role=GROUP_VIEWER_ROLE)
    team = create_team(group)
    add_user_to_team(team, user, TEAM_RESPONDER_ROLE)

    assert can_read_team(user, team.id) is True
    assert can_respond_team(user, team.id) is True
    assert can_write_team(user, team.id) is False


def test_team_viewer_can_read_only():
    group = create_group()
    user = create_user(group=group, group_role=GROUP_VIEWER_ROLE)
    team = create_team(group)
    add_user_to_team(team, user, TEAM_VIEWER_ROLE)

    assert can_read_team(user, team.id) is True
    assert can_respond_team(user, team.id) is False
    assert can_write_team(user, team.id) is False
