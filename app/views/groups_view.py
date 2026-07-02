from flask import Blueprint, jsonify, request
from peewee import DoesNotExist, IntegrityError

from app.modules.db.common import integrity_conflict, unique_field_conflict
from app.api.schemas.groups import (
    GroupCreateSchema,
    GroupUpdateSchema,
    UserGroupAddSchema,
    UserGroupUpdateSchema,
)
from app.api.schemas.roles import GROUP_USER_ADMIN_ROLE, GROUP_VIEWER_ROLE
from app.api.schemas.users import GroupUserCreateSchema
from app.db import database_proxy as db
from app.login import hash_password
from app.modules.db import groups_repo, users_repo
from app.modules.db.models import UserGroup
from app.services.audit import write_audit
from app.services.rbac import (
    can_read_group,
    get_allowed_group_ids,
    require_admin_user,
    require_group_user_admin,
    require_group_write,
    require_assign_group_role,
)
from app.services.serializers import serialize_group, serialize_user, serialize_user_group
from app.services.validation import validate_body


groups_bp = Blueprint("groups_api", __name__)


@groups_bp.route("", methods=["GET"])
def list_groups():
    """Return groups visible to the current user."""
    user = request.current_user
    if user and user.is_admin:
        return jsonify([
            serialize_group(group, user)
            for group in groups_repo.list_groups(active_only=False)
        ])

    allowed_group_ids = get_allowed_group_ids()
    groups = [
        group
        for group in groups_repo.list_groups(active_only=True)
        if group.id in allowed_group_ids
    ]

    return jsonify([
        serialize_group(group, user)
        for group in groups
    ])


@groups_bp.route("", methods=["POST"])
def create_group():
    """Create a group. Admin only."""
    error = require_admin_user()
    if error:
        return error

    payload, error = validate_body(GroupCreateSchema)
    if error:
        return error

    try:
        group = groups_repo.create_group(
            payload.slug,
            payload.name,
            payload.description,
            active=payload.active,
        )
    except IntegrityError as exc:
        error_text = str(exc).lower()

        if "slug" in error_text:
            return unique_field_conflict(
                "slug",
                payload.slug,
                "Group with this slug already exists",
            )

        return integrity_conflict("Group could not be saved because it conflicts with existing data")

    from app.services.service_catalog.presets import ensure_basic_operational_standard

    ensure_basic_operational_standard(group, actor_user=request.current_user)
    write_audit(
        "group.create",
        object_type="group",
        object_id=group.id,
        group_id=group.id,
        data=payload.model_dump()
    )

    return jsonify(serialize_group(group, request.current_user)), 201


@groups_bp.route("/<int:group_id>", methods=["PUT"])
def update_group(group_id):
    """Update a group. Group editor or global admin required."""
    error = require_group_write(group_id)
    if error:
        return error

    payload, error = validate_body(GroupUpdateSchema)
    if error:
        return error

    group = groups_repo.update_group(group_id, payload.model_dump())
    write_audit("group.update", object_type="group", object_id=group.id, group_id=group.id, data=payload.model_dump())
    return jsonify(serialize_group(group, request.current_user))


@groups_bp.route("/<int:group_id>/users", methods=["GET"])
def list_group_users(group_id):
    """Return group users."""
    user = request.current_user
    if not user or (not user.is_admin and not can_read_group(user, group_id)):
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


@groups_bp.route("/<int:group_id>/users/create", methods=["POST"])
def create_group_user(group_id):
    """Create a user inside this group. Group user-admin or global admin required."""
    error = require_group_user_admin(group_id)
    if error:
        return error

    try:
        group = groups_repo.get_group(group_id)
    except DoesNotExist:
        return jsonify({"error": "group_not_found", "message": "Selected group was not found"}), 404
    if not group.active:
        return jsonify({"error": "group_inactive", "message": "Selected group is inactive"}), 400

    payload, error = validate_body(GroupUserCreateSchema)
    if error:
        return error

    data = payload.model_dump()
    group_role = data.pop("group_role", GROUP_VIEWER_ROLE)
    password = data.pop("password")
    data["password_hash"] = hash_password(password)
    data["active"] = True
    data["is_admin"] = False

    try:
        with db.atomic():
            user = users_repo.create_user(**data)
            groups_repo.add_user_to_group(user_id=user.id, group_id=group_id, role=group_role)
            users_repo.set_active_group(user.id, group_id)
            user = users_repo.get_user(user.id)
    except IntegrityError:
        return jsonify({
            "error": "user_conflict",
            "message": "User with this username or unique field already exists",
        }), 409

    write_audit(
        "group.user.create",
        object_type="user",
        object_id=user.id,
        group_id=group_id,
        data={**data, "password_hash": "***", "group_role": group_role},
    )
    return jsonify(serialize_user(user)), 201


@groups_bp.route("/<int:group_id>/users", methods=["POST"])
def add_group_user(group_id):
    """Add an existing user to a group.

    Group user-admin or global admin required.
    """
    error = require_group_user_admin(group_id)
    if error:
        return error

    try:
        group = groups_repo.get_group(group_id)
    except DoesNotExist:
        return jsonify({
            "error": "group_not_found",
            "message": "Selected group was not found",
        }), 404

    if not group.active:
        return jsonify({
            "error": "group_inactive",
            "message": "Selected group is inactive",
        }), 400

    payload, error = validate_body(UserGroupAddSchema)
    if error:
        return error

    role_error = require_assign_group_role(payload.role)
    if role_error:
        return role_error

    membership = groups_repo.add_user_to_group(
        payload.user_id,
        group_id,
        payload.role,
        active=payload.active,
    )

    write_audit(
        "group.user.add",
        object_type="group",
        object_id=group_id,
        group_id=group_id,
        data=payload.model_dump(),
    )

    return jsonify(serialize_user_group(membership)), 201


@groups_bp.route("/users/<int:membership_id>", methods=["PUT"])
def update_group_user(membership_id):
    """Update a group membership.

    Group user-admin or global admin required.
    """
    membership = groups_repo.get_group_membership(membership_id)
    error = require_group_user_admin(membership.group.id)
    if error:
        return error

    payload, error = validate_body(UserGroupUpdateSchema)
    if error:
        return error

    role_error = require_assign_group_role(payload.role)
    if role_error:
        return role_error

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
    """Remove user from group, group teams and group rotations.

    Group user-admin or global admin required.
    """
    membership = groups_repo.get_group_membership(membership_id)

    error = require_group_user_admin(membership.group.id)
    if error:
        return error

    group_id = membership.group.id
    data = groups_repo.delete_group_membership(membership_id)
    write_audit(
        "group.user.remove",
        object_type="group",
        object_id=data["group_id"],
        group_id=data["group_id"],
        data={
            "membership_id": data["id"],
            "user_id": data["user_id"],
            "removed_team_memberships": data.get("removed_team_memberships", 0),
            "removed_rotation_members": data.get("removed_rotation_members", 0),
            "removed_rotation_layer_members": data.get("removed_rotation_layer_members", 0),
            "removed_rotation_overrides": data.get("removed_rotation_overrides", 0),
        },
    )
    return jsonify({"deleted": True, "id": membership_id, "group_id": group_id})


@groups_bp.route("/<int:group_id>", methods=["DELETE"])
def delete_group(group_id):
    """Soft-delete a group and all resources under it. Admin only."""
    error = require_admin_user()
    if error:
        return error

    group = groups_repo.soft_delete_group(group_id)
    write_audit(
        "group.delete",
        object_type="group",
        object_id=group.id,
        group_id=group.id,
        data={
            "slug": group.slug,
            "name": group.name,
            "deleted": True,
        },
    )
    return jsonify({
        "deleted": True,
        "id": group.id,
        "slug": group.slug,
        "name": group.name,
    })
