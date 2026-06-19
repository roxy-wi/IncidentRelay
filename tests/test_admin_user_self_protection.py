from app.modules.db.models import User, UserGroup
from app.views.admin_users_view import admin_delete_user, admin_list_users, admin_update_user
from tests.factories import create_group, create_user


def _user_update_payload(user, *, active=True):
    return {
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "phone": user.phone,
        "telegram_user_id": user.telegram_user_id,
        "slack_user_id": user.slack_user_id,
        "mattermost_user_id": user.mattermost_user_id,
        "password": None,
        "is_admin": bool(user.is_admin),
        "active": active,
    }


def test_admin_users_marks_current_user(app):
    current_admin = create_user(is_admin=True)
    other_admin = create_user(is_admin=True)

    with app.test_request_context("/api/admin/users", method="GET"):
        from flask import request

        request.current_user = current_admin
        response = admin_list_users()

    users = response.get_json()
    by_id = {item["id"]: item for item in users}

    assert by_id[current_admin.id]["is_current_user"] is True
    assert by_id[other_admin.id]["is_current_user"] is False


def test_admin_cannot_disable_own_account(app):
    current_admin = create_user(is_admin=True)

    with app.test_request_context(
        f"/api/admin/users/{current_admin.id}",
        method="PUT",
        json=_user_update_payload(current_admin, active=False),
    ):
        from flask import request

        request.current_user = current_admin
        response, status = admin_update_user(current_admin.id)

    current_admin = type(current_admin).get_by_id(current_admin.id)
    assert status == 400
    assert response.get_json()["error"] == "self_deactivation_denied"
    assert current_admin.active is True


def test_admin_cannot_remove_own_account(app):
    current_admin = create_user(is_admin=True)

    with app.test_request_context(
        f"/api/admin/users/{current_admin.id}",
        method="DELETE",
    ):
        from flask import request

        request.current_user = current_admin
        response, status = admin_delete_user(current_admin.id)

    current_admin = type(current_admin).get_by_id(current_admin.id)
    payload = response.get_json()

    assert status == 400
    assert payload["error"] == "self_delete_denied"
    assert payload["message"] == "You cannot remove your own user account."
    assert current_admin.active is True


def test_global_admin_can_update_user_group_and_role_from_users_page(app):
    current_admin = create_user(is_admin=True)
    group = create_group()
    target = create_user()

    payload = _user_update_payload(target, active=True)
    payload["group_id"] = group.id
    payload["group_role"] = "user_admin"

    with app.test_request_context(
        f"/api/admin/users/{target.id}",
        method="PUT",
        json=payload,
    ):
        from flask import request

        request.current_user = current_admin
        response = admin_update_user(target.id)

    data = response.get_json()
    membership = UserGroup.get(
        (UserGroup.user == target.id)
        & (UserGroup.group == group.id)
    )
    target = User.get_by_id(target.id)

    assert data["active_group_id"] == group.id
    assert data["active_group_role"] == "user_admin"
    assert membership.role == "user_admin"
    assert membership.active is True
    assert target.active_group.id == group.id
