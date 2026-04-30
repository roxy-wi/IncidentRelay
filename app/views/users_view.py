from flask import Blueprint, jsonify, request

from app.login import hash_password

from app.api.schemas.users import UserCreateSchema, UserUpdateSchema
from app.modules.db import users_repo
from app.services.audit import write_audit
from app.services.rbac import get_allowed_group_ids
from app.services.serializers import serialize_user
from app.services.validation import validate_body


users_bp = Blueprint("users_api", __name__)


@users_bp.route("", methods=["GET"])
def list_users():
    """
    List users.

    Admin with all=1 can see all users.
    Non-admin users can see only users from groups they have access to.
    """
    show_all = request.args.get("all") == "1"
    user = request.current_user

    if user and user.is_admin and show_all:
        return jsonify([
            serialize_user(item)
            for item in users_repo.list_all_users(active_only=True)
        ])

    group_ids = get_allowed_group_ids(write_required=False)

    if not group_ids:
        return jsonify([])

    return jsonify([
        serialize_user(item)
        for item in users_repo.list_users_by_group_ids(group_ids, active_only=True)
    ])


@users_bp.route("", methods=["POST"])
def create_user():
    """
    Create a user.
    """

    payload, error = validate_body(UserCreateSchema)
    if error:
        return error

    data = payload.model_dump()
    password = data.pop("password", None)

    if password:
        data["password_hash"] = hash_password(password)

    user = users_repo.create_user(**data)
    write_audit("user.create", object_type="user", object_id=user.id, data={**data, "password_hash": "***" if password else None})
    return jsonify(serialize_user(user)), 201


@users_bp.route("/<int:user_id>", methods=["PUT"])
def update_user(user_id):
    """
    Update a user.
    """

    payload, error = validate_body(UserUpdateSchema)
    if error:
        return error

    data = payload.model_dump()
    password = data.pop("password", None)

    if password:
        data["password_hash"] = hash_password(password)

    user = users_repo.update_user(user_id, data)
    write_audit("user.update", object_type="user", object_id=user.id, data={**data, "password_hash": "***" if password else None})
    return jsonify(serialize_user(user))


@users_bp.route("/<int:user_id>", methods=["DELETE"])
def delete_user(user_id):
    """
    Disable a user.
    """

    user = users_repo.disable_user(user_id)
    write_audit("user.disable", object_type="user", object_id=user.id)
    return jsonify(serialize_user(user))
