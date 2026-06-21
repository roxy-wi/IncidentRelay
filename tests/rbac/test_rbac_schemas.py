import pytest
from pydantic import ValidationError

from app.api.schemas.roles import (
    GROUP_EDITOR_ROLE,
    GROUP_USER_ADMIN_ROLE,
    GROUP_VIEWER_ROLE,
    TEAM_MANAGER_ROLE,
    TEAM_RESPONDER_ROLE,
    TEAM_VIEWER_ROLE,
)
from app.api.schemas.teams import TeamUserAddSchema
from app.api.schemas.users import GroupUserCreateSchema, UserCreateSchema, UserUpdateSchema


def test_group_user_create_rejects_group_id():
    with pytest.raises(ValidationError):
        GroupUserCreateSchema.model_validate({
            "username": "john",
            "password": "strong-password",
            "group_id": 2,
        })


def test_group_user_create_rejects_is_admin():
    with pytest.raises(ValidationError):
        GroupUserCreateSchema.model_validate({
            "username": "john",
            "password": "strong-password",
            "is_admin": True,
        })


def test_group_user_create_rejects_user_admin_role():
    with pytest.raises(ValidationError):
        GroupUserCreateSchema.model_validate({
            "username": "john",
            "password": "strong-password",
            "group_role": GROUP_USER_ADMIN_ROLE,
        })


def test_group_user_create_accepts_viewer_and_editor_roles():
    for role in (GROUP_VIEWER_ROLE, GROUP_EDITOR_ROLE):
        payload = GroupUserCreateSchema.model_validate({
            "username": f"john-{role}",
            "password": "strong-password",
            "group_role": role,
        })
        assert payload.group_role == role


def test_admin_user_create_accepts_user_admin_role():
    payload = UserCreateSchema.model_validate({
        "username": "john",
        "password": "strong-password",
        "group_id": 1,
        "group_role": GROUP_USER_ADMIN_ROLE,
    })
    assert payload.group_role == GROUP_USER_ADMIN_ROLE


def test_team_user_accepts_new_roles():
    for role in (TEAM_VIEWER_ROLE, TEAM_RESPONDER_ROLE, TEAM_MANAGER_ROLE):
        payload = TeamUserAddSchema.model_validate({
            "user_id": 1,
            "role": role,
        })
        assert payload.role == role


def test_team_user_rejects_old_rw_role_after_migration():
    with pytest.raises(ValidationError):
        TeamUserAddSchema.model_validate({
            "user_id": 1,
            "role": "rw",
        })


def test_admin_user_update_accepts_group_and_role():
    payload = UserUpdateSchema.model_validate({
        "username": "john",
        "password": "strong-password",
        "group_id": 1,
        "group_role": GROUP_USER_ADMIN_ROLE,
    })
    assert payload.group_id == 1
    assert payload.group_role == GROUP_USER_ADMIN_ROLE


def test_admin_user_update_rejects_old_group_role():
    with pytest.raises(ValidationError):
        UserUpdateSchema.model_validate({
            "username": "john",
            "password": "strong-password",
            "group_id": 1,
            "group_role": "rw",
        })
