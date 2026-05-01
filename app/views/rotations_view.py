from flask import Blueprint, jsonify, request

from app.api.schemas.rotations import RotationCreateSchema, RotationMemberAddSchema, RotationMemberUpdateSchema, RotationOverrideCreateSchema, RotationUpdateSchema
from app.modules.db import rotations_repo, teams_repo
from app.services.audit import write_audit
from app.services.rbac import get_allowed_team_ids, require_team_read, require_team_write
from app.services.oncall import get_current_oncall_user
from app.services.serializers import serialize_rotation
from app.services.validation import validate_body


rotations_bp = Blueprint("rotations_api", __name__)


@rotations_bp.route("", methods=["GET"])
def list_rotations():
    """
    Return rotations.
    """

    team_id = request.args.get("team_id", type=int)
    if team_id:
        error = require_team_read(team_id)
        if error:
            return error
        rotations = rotations_repo.list_rotations(team_id=team_id)
    else:
        rotations = rotations_repo.list_rotations(team_ids=get_allowed_team_ids())
    return jsonify([serialize_rotation(rotation, get_current_oncall_user(rotation)) for rotation in rotations])


@rotations_bp.route("/<int:rotation_id>", methods=["GET"])
def get_rotation(rotation_id):
    """
    Return a single rotation.
    """

    rotation = rotations_repo.get_rotation(rotation_id)
    error = require_team_read(rotation.team_id)
    if error:
        return error
    return jsonify(serialize_rotation(rotation, get_current_oncall_user(rotation)))


@rotations_bp.route("", methods=["POST"])
def create_rotation():
    """
    Create a rotation.
    """

    payload, error = validate_body(RotationCreateSchema)
    if error:
        return error

    error = require_team_write(payload.team_id)
    if error:
        return error

    rotation = rotations_repo.create_rotation(
        team_id=payload.team_id,
        name=payload.name,
        description=payload.description,
        start_at=payload.start_at,
        duration_seconds=payload.duration_seconds,
        reminder_interval_seconds=payload.reminder_interval_seconds,
        rotation_type=payload.rotation_type,
        interval_value=payload.interval_value,
        interval_unit=payload.interval_unit,
        handoff_time=payload.handoff_time,
        handoff_weekday=payload.handoff_weekday,
        timezone=payload.timezone,
    )
    write_audit("rotation.create", object_type="rotation", object_id=rotation.id, team_id=rotation.team.id, data=payload.model_dump(mode="json"))

    if payload.add_team_members:
        team_members = teams_repo.list_team_users(payload.team_id)

        position = 0

        for membership in team_members:
            if not membership.active:
                continue

            rotations_repo.add_rotation_member(
                rotation_id=rotation.id,
                user_id=membership.user.id,
                position=position,
            )
            position += 1

    return jsonify(serialize_rotation(rotation, get_current_oncall_user(rotation))), 201


@rotations_bp.route("/<int:rotation_id>", methods=["PUT"])
def update_rotation(rotation_id):
    """
    Update a rotation.
    """

    payload, error = validate_body(RotationUpdateSchema)
    if error:
        return error

    current_rotation = rotations_repo.get_rotation(rotation_id)
    error = require_team_write(current_rotation.team_id)
    if error:
        return error
    if payload.team_id != current_rotation.team_id:
        error = require_team_write(payload.team_id)
        if error:
            return error

    rotation = rotations_repo.update_rotation(
        rotation_id,
        {
            "team": payload.team_id,
            "name": payload.name,
            "description": payload.description,
            "start_at": payload.start_at,
            "duration_seconds": payload.duration_seconds,
            "reminder_interval_seconds": payload.reminder_interval_seconds,
            "rotation_type": payload.rotation_type,
            "interval_value": payload.interval_value,
            "interval_unit": payload.interval_unit,
            "handoff_time": payload.handoff_time,
            "handoff_weekday": payload.handoff_weekday,
            "timezone": payload.timezone,
        },
    )
    write_audit("rotation.update", object_type="rotation", object_id=rotation.id, team_id=rotation.team.id, data=payload.model_dump(mode="json"))
    return jsonify(serialize_rotation(rotation, get_current_oncall_user(rotation)))


@rotations_bp.route("/<int:rotation_id>", methods=["DELETE"])
def delete_rotation(rotation_id):
    """
    Disable a rotation.
    """

    current_rotation = rotations_repo.get_rotation(rotation_id)
    error = require_team_write(current_rotation.team_id)
    if error:
        return error
    rotation = rotations_repo.disable_rotation(rotation_id)
    write_audit("rotation.disable", object_type="rotation", object_id=rotation.id, team_id=rotation.team.id)
    return jsonify(serialize_rotation(rotation, get_current_oncall_user(rotation)))


@rotations_bp.route("/<int:rotation_id>/members", methods=["GET"])
def list_rotation_members(rotation_id):
    """
    Return rotation members.
    """

    rotation = rotations_repo.get_rotation(rotation_id)
    error = require_team_read(rotation.team_id)
    if error:
        return error

    return jsonify([
        {
            "id": member.id,
            "user_id": member.user.id,
            "username": member.user.username,
            "display_name": member.user.display_name,
            "position": member.position,
            "active": member.active,
        }
        for member in rotations_repo.list_rotation_members(rotation_id)
    ])


@rotations_bp.route("/<int:rotation_id>/members", methods=["POST"])
def add_rotation_member(rotation_id):
    """
    Add a user to a rotation.
    """

    payload, error = validate_body(RotationMemberAddSchema)
    if error:
        return error

    rotation = rotations_repo.get_rotation(rotation_id)
    error = require_team_write(rotation.team_id)
    if error:
        return error

    try:
        rotations_repo.ensure_user_in_rotation_team(rotation_id, payload.user_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    member = rotations_repo.add_rotation_member(rotation_id, payload.user_id, payload.position)
    write_audit("rotation.member.add", object_type="rotation", object_id=rotation_id, team_id=member.rotation.team.id, data=payload.model_dump())
    return jsonify({"id": member.id}), 201


@rotations_bp.route("/<int:rotation_id>/eligible-users", methods=["GET"])
def list_rotation_eligible_users(rotation_id):
    """
    Return active users from the team of this rotation.

    These users can be added as rotation members or selected for overrides.
    """
    rotation = rotations_repo.get_rotation(rotation_id)

    error = require_team_read(rotation.team_id)
    if error:
        return error

    memberships = rotations_repo.list_rotation_team_users(rotation_id, active_only=True)

    return jsonify([
        {
            "user_id": membership.user.id,
            "username": membership.user.username,
            "display_name": membership.user.display_name,
            "team_member_id": membership.id,
            "role": membership.role,
            "active": membership.active,
        }
        for membership in memberships
    ])


@rotations_bp.route("/members/<int:member_id>", methods=["PUT"])
def update_rotation_member(member_id):
    """
    Update a rotation member.
    """

    member = rotations_repo.get_rotation_member(member_id)
    error = require_team_write(member.rotation.team.id)
    if error:
        return error

    payload, error = validate_body(RotationMemberUpdateSchema)
    if error:
        return error

    member = rotations_repo.update_rotation_member(
        member_id=member_id,
        position=payload.position,
        active=payload.active,
    )

    write_audit(
        "rotation.member.update",
        object_type="rotation",
        object_id=member.rotation.id,
        team_id=member.rotation.team.id,
        data={"member_id": member.id, **payload.model_dump()},
    )

    return jsonify({
        "id": member.id,
        "user_id": member.user.id,
        "username": member.user.username,
        "display_name": member.user.display_name,
        "position": member.position,
        "active": member.active,
    })


@rotations_bp.route("/members/<int:member_id>", methods=["DELETE"])
def delete_rotation_member(member_id):
    """
    Remove a user from a rotation.
    """
    member = rotations_repo.get_rotation_member(member_id)

    error = require_team_write(member.rotation.team.id)
    if error:
        return error

    data = rotations_repo.delete_rotation_member(member_id)

    write_audit(
        "rotation.member.remove",
        object_type="rotation",
        object_id=data["rotation_id"],
        team_id=data["team_id"],
        data=data,
    )

    return jsonify({"deleted": True, "id": member_id})


@rotations_bp.route("/<int:rotation_id>/overrides", methods=["GET"])
def list_rotation_overrides(rotation_id):
    """
    Return rotation overrides.
    """

    rotation = rotations_repo.get_rotation(rotation_id)
    error = require_team_read(rotation.team_id)
    if error:
        return error

    return jsonify([
        {
            "id": override.id,
            "rotation_id": override.rotation.id,
            "user_id": override.user.id,
            "username": override.user.username,
            "display_name": override.user.display_name,
            "starts_at": override.starts_at.isoformat(),
            "ends_at": override.ends_at.isoformat(),
            "reason": override.reason,
        }
        for override in rotations_repo.list_rotation_overrides(rotation_id)
    ])


@rotations_bp.route("/<int:rotation_id>/overrides", methods=["POST"])
def create_rotation_override(rotation_id):
    """
    Create a temporary rotation override.
    """

    payload, error = validate_body(RotationOverrideCreateSchema)
    if error:
        return error

    rotation = rotations_repo.get_rotation(rotation_id)
    error = require_team_write(rotation.team_id)
    if error:
        return error

    try:
        rotations_repo.ensure_user_in_rotation_team(rotation_id, payload.user_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    override = rotations_repo.create_rotation_override(
        rotation_id=rotation_id,
        user_id=payload.user_id,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        reason=payload.reason,
    )
    write_audit("rotation.override.create", object_type="rotation", object_id=rotation_id, team_id=override.rotation.team.id, data=payload.model_dump(mode="json"))
    return jsonify({"id": override.id}), 201


@rotations_bp.route("/overrides/<int:override_id>", methods=["DELETE"])
def delete_rotation_override(override_id):
    """
    Delete a rotation override.
    """

    override = rotations_repo.get_rotation_override(override_id)
    error = require_team_write(override.rotation.team_id)
    if error:
        return error

    rotation_id = override.rotation.id
    team_id = override.rotation.team.id
    rotations_repo.delete_rotation_override(override_id)
    write_audit("rotation.override.delete", object_type="rotation", object_id=rotation_id, team_id=team_id, data={"override_id": override_id})

    return jsonify({"deleted": True})
