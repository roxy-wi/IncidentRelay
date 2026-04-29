from flask import Blueprint, jsonify

from app.login import hash_password

from app.api.schemas.users import UserUpdateSchema
from app.modules.db import users_repo
from app.services.audit import write_audit
from app.services.rbac import require_admin_user
from app.services.rbac import require_permission
from app.services.serializers import serialize_user
from app.services.validation import validate_body


admin_users_bp = Blueprint("admin_users_api", __name__)


@admin_users_bp.route("", methods=["GET"])
@require_permission("users:admin")
def admin_list_users():
    """
    Return users for the admin workspace.
    """

    return jsonify([serialize_user(user) for user in users_repo.list_users(active_only=False)])


@admin_users_bp.route("/<int:user_id>", methods=["GET"])
@require_permission("users:admin")
def admin_get_user(user_id):
    """
    Return one user for the admin workspace.
    """

    return jsonify(serialize_user(users_repo.get_user(user_id)))


@admin_users_bp.route("/<int:user_id>", methods=["PUT"])
@require_permission("users:admin")
def admin_update_user(user_id):
    """
    Update a user from the admin workspace.
    """

    admin_error = require_admin_user()
    if admin_error:
        return admin_error

    payload, error = validate_body(UserUpdateSchema)
    if error:
        return error

    data = payload.model_dump()
    password = data.pop("password", None)

    if password:
        data["password_hash"] = hash_password(password)

    user = users_repo.update_user(user_id, data)
    write_audit("admin.user.update", object_type="user", object_id=user.id, data={**data, "password_hash": "***" if password else None})
    return jsonify(serialize_user(user))


@admin_users_bp.route("/<int:user_id>", methods=["DELETE"])
@require_permission("users:admin")
def admin_delete_user(user_id):
    """
    Disable a user from the admin workspace.
    """

    admin_error = require_admin_user()
    if admin_error:
        return admin_error

    user = users_repo.disable_user(user_id)
    write_audit("admin.user.disable", object_type="user", object_id=user.id)
    return jsonify(serialize_user(user))
