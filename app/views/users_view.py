from flask import Blueprint, jsonify, request

from app.modules.db import users_repo
from app.services.rbac import get_allowed_group_ids
from app.services.serializers import serialize_user


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
