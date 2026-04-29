from flask import Blueprint, jsonify, request

from app.api.schemas.groups import GroupCreateSchema, GroupUpdateSchema, UserGroupAddSchema, UserGroupUpdateSchema
from app.modules.db import groups_repo
from app.models import UserGroup
from app.services.audit import write_audit
from app.services.rbac import get_allowed_group_ids, require_admin_user, require_group_write
from app.services.serializers import serialize_group, serialize_user_group
from app.services.validation import validate_body


groups_bp = Blueprint("groups_api", __name__)


@groups_bp.route("", methods=["GET"])
def list_groups():
    """
    Return groups visible to the current user.
    """

    user = request.current_user

    if user and user.is_admin:
        return jsonify([serialize_group(group) for group in groups_repo.list_groups(active_only=True)])

    allowed_group_ids = get_allowed_group_ids()
    groups = [group for group in groups_repo.list_groups(active_only=True) if group.id in allowed_group_ids]

    return jsonify([serialize_group(group) for group in groups])


@groups_bp.route("", methods=["POST"])
def create_group():
    """
    Create a group. Admin only.
    """

    error = require_admin_user()
    if error:
        return error

    payload, error = validate_body(GroupCreateSchema)
    if error:
        return error

    group = groups_repo.create_group(payload.slug, payload.name, payload.description)
    write_audit("group.create", object_type="group", object_id=group.id, group_id=group.id, data=payload.model_dump())

    return jsonify(serialize_group(group)), 201


@groups_bp.route("/<int:group_id>", methods=["PUT"])
def update_group(group_id):
    """
    Update a group. RW role in the group or admin required.
    """

    error = require_group_write(group_id)
    if error:
        return error

    payload, error = validate_body(GroupUpdateSchema)
    if error:
        return error

    group = groups_repo.update_group(group_id, payload.model_dump())
    write_audit("group.update", object_type="group", object_id=group.id, group_id=group.id, data=payload.model_dump())

    return jsonify(serialize_group(group))


@groups_bp.route("/<int:group_id>/users", methods=["GET"])
def list_group_users(group_id):
    """
    Return group users.
    """

    if not request.current_user.is_admin and group_id not in get_allowed_group_ids():
        return jsonify({"error": "Access to this group is denied"}), 403

    result = []
    for membership in UserGroup.select().where(UserGroup.group == group_id).order_by(UserGroup.id.asc()):
        result.append({
            "id": membership.id,
            "user_id": membership.user.id,
            "username": membership.user.username,
            "display_name": membership.user.display_name,
            "role": membership.role,
            "active": membership.active,
        })

    return jsonify(result)


@groups_bp.route("/<int:group_id>/users", methods=["POST"])
def add_group_user(group_id):
    """
    Add a user to a group. RW role in the group or admin required.
    """

    error = require_group_write(group_id)
    if error:
        return error

    payload, error = validate_body(UserGroupAddSchema)
    if error:
        return error

    membership = groups_repo.add_user_to_group(payload.user_id, group_id, payload.role)
    write_audit("group.user.add", object_type="group", object_id=group_id, group_id=group_id, data=payload.model_dump())

    return jsonify(serialize_user_group(membership)), 201


@groups_bp.route("/users/<int:membership_id>", methods=["PUT"])
def update_group_user(membership_id):
    """
    Update a group membership.
    """

    membership = groups_repo.get_group_membership(membership_id)
    error = require_group_write(membership.group.id)
    if error:
        return error

    payload, error = validate_body(UserGroupUpdateSchema)
    if error:
        return error

    membership = groups_repo.update_group_membership(
        membership_id=membership_id,
        role=payload.role,
        active=payload.active,
    )

    write_audit(
        "group.user.update",
        object_type="group",
        object_id=membership.group.id,
        group_id=membership.group.id,
        data={"membership_id": membership.id, **payload.model_dump()},
    )

    return jsonify({
        "id": membership.id,
        "user_id": membership.user.id,
        "username": membership.user.username,
        "display_name": membership.user.display_name,
        "role": membership.role,
        "active": membership.active,
    })


@groups_bp.route("/users/<int:membership_id>", methods=["DELETE"])
def delete_group_user(membership_id):
    """
    Disable a group membership.
    """

    membership = groups_repo.get_group_membership(membership_id)
    error = require_group_write(membership.group.id)
    if error:
        return error

    membership = groups_repo.disable_group_membership(membership_id)

    write_audit(
        "group.user.disable",
        object_type="group",
        object_id=membership.group.id,
        group_id=membership.group.id,
        data={"membership_id": membership.id, "user_id": membership.user.id},
    )

    return jsonify({"deleted": True, "id": membership.id})


@groups_bp.route("/<int:group_id>", methods=["DELETE"])
def delete_group(group_id):
    """
    Soft-delete a group and all resources under it.
    """

    error = require_group_write(group_id)
    if error:
        return error

    group = groups_repo.soft_delete_group(group_id)

    write_audit(
        "group.delete",
        object_type="group",
        object_id=group.id,
        group_id=group.id,
    )

    return jsonify(serialize_group(group))
