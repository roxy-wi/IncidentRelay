from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request

from app.api.schemas.rotations import (
    RotationCreateSchema,
    RotationMemberAddSchema,
    RotationMemberUpdateSchema,
    RotationOverrideCreateSchema,
    RotationUpdateSchema,
    RotationLayerCreateSchema,
    RotationLayerUpdateSchema,
    RotationLayerMemberAddSchema,
    RotationLayerMemberUpdateSchema,
    RotationLayerRestrictionsReplaceSchema,
    RotationEnabledUpdateSchema
)
from app.modules.db import rotations_repo, teams_repo
from app.services.audit import write_audit
from app.services.rbac import get_allowed_team_ids, require_team_read, require_team_write
from app.services.oncall import get_current_oncall_user
from app.services.serializers import serialize_rotation, serialize_rotation_layer, serialize_rotation_layer_member, serialize_rotation_layer_restriction
from app.services.validation import (
    make_error_response,
    safe_exception_response,
    validate_body,
)


rotations_bp = Blueprint("rotations_api", __name__)


def _rotation_timezone(rotation):
    """Return ZoneInfo for rotation timezone."""
    timezone_name = getattr(rotation, "timezone", None) or "UTC"

    try:
        return ZoneInfo(timezone_name)
    except Exception:
        return ZoneInfo("UTC")


def _layer_timezone(layer):
    """Return ZoneInfo for layer timezone."""

    timezone_name = (
        getattr(layer, "timezone", None)
        or getattr(layer.rotation, "timezone", None)
        or "UTC"
    )

    try:
        return ZoneInfo(timezone_name)
    except Exception:
        return ZoneInfo("UTC")


def _layer_local_to_utc_naive(value, layer):
    """
    Convert datetime from layer timezone to UTC naive.

    datetime-local from browser comes without tzinfo, so we treat it as
    local time in layer.timezone.
    """

    if value is None:
        return None

    zone = _layer_timezone(layer)

    if value.tzinfo is None:
        value = value.replace(tzinfo=zone)

    return value.astimezone(dt_timezone.utc).replace(tzinfo=None)


def _rotation_local_to_utc_naive(value, rotation):
    """
    Convert datetime from rotation timezone to UTC naive.

    datetime-local from browser comes without tzinfo, so we treat it as
    local time in rotation.timezone.
    """
    if value is None:
        return None

    zone = _rotation_timezone(rotation)

    if value.tzinfo is None:
        value = value.replace(tzinfo=zone)

    return value.astimezone(dt_timezone.utc).replace(tzinfo=None)


def _utc_naive_to_rotation_local(value, rotation):
    """Convert stored UTC naive datetime to rotation-local ISO datetime."""
    if value is None:
        return None

    zone = _rotation_timezone(rotation)

    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_timezone.utc)

    return value.astimezone(zone).replace(tzinfo=None)


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
    return jsonify([
        serialize_rotation(
            rotation,
            get_current_oncall_user(rotation),
            request.current_user,
        )
        for rotation in rotations
    ])


@rotations_bp.route("/<int:rotation_id>", methods=["GET"])
def get_rotation(rotation_id):
    """
    Return a single rotation.
    """

    rotation = rotations_repo.get_rotation(rotation_id)
    error = require_team_read(rotation.team_id)
    if error:
        return error
    return jsonify(serialize_rotation(
        rotation,
        get_current_oncall_user(rotation),
        request.current_user,
    ))


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

    try:
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
            enabled=payload.enabled,
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="rotation_conflict",
            message="Rotation conflicts with an existing rotation.",
            status_code=400,
        )
    write_audit("rotation.create", object_type="rotation", object_id=rotation.id, team_id=rotation.team.id, data=payload.model_dump(mode="json"))

    if payload.add_team_members:
        default_layer = rotations_repo.get_or_create_default_layer(rotation.id)
        team_members = teams_repo.list_team_users(payload.team_id)

        position = 0
        for membership in team_members:
            if not membership.active:
                continue

            rotations_repo.add_rotation_layer_member(
                layer_id=default_layer.id,
                user_id=membership.user.id,
                position=position,
            )
            position += 1

    return jsonify(serialize_rotation(
        rotation,
        get_current_oncall_user(rotation),
        request.current_user,
    )), 201


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
            "enabled": payload.enabled,
        },
    )
    write_audit("rotation.update", object_type="rotation", object_id=rotation.id, team_id=rotation.team.id, data=payload.model_dump(mode="json"))
    return jsonify(serialize_rotation(
        rotation,
        get_current_oncall_user(rotation),
        request.current_user,
    ))


@rotations_bp.route("/<int:rotation_id>/enabled", methods=["PUT"])
def set_rotation_enabled(rotation_id):
    """Enable or disable a rotation without deleting its schedule data."""
    payload, error = validate_body(RotationEnabledUpdateSchema)
    if error:
        return error

    current_rotation = rotations_repo.get_rotation(rotation_id)
    error = require_team_write(current_rotation.team_id)
    if error:
        return error

    rotation = rotations_repo.set_rotation_enabled(rotation_id, payload.enabled)

    write_audit(
        "rotation.enable" if payload.enabled else "rotation.disable",
        object_type="rotation",
        object_id=rotation.id,
        team_id=rotation.team.id,
        data={"enabled": payload.enabled},
    )

    return jsonify(serialize_rotation(rotation, get_current_oncall_user(rotation)))


@rotations_bp.route("/<int:rotation_id>", methods=["DELETE"])
def delete_rotation(rotation_id):
    """Remove a rotation and detach related route references."""
    current_rotation = rotations_repo.get_rotation(rotation_id)
    error = require_team_write(current_rotation.team_id)
    if error:
        return error

    rotation = rotations_repo.soft_delete_rotation(rotation_id)

    write_audit(
        "rotation.delete",
        object_type="rotation",
        object_id=rotation.id,
        team_id=rotation.team.id,
    )

    return jsonify(serialize_rotation(
        rotation,
        get_current_oncall_user(rotation),
        request.current_user,
    ))


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
        return safe_exception_response(
            exc,
            error="validation_error",
            message="User cannot be added to this rotation.",
            status_code=400,
        )

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
    Return active and upcoming rotation overrides.

    Expired overrides are hidden by default. Pass include_expired=1 to show
    historical overrides.
    """
    rotation = rotations_repo.get_rotation(rotation_id)

    error = require_team_read(rotation.team_id)
    if error:
        return error

    include_expired = request.args.get("include_expired") in ("1", "true", "yes")

    return jsonify([
        {
            "id": override.id,
            "rotation_id": override.rotation.id,
            "user_id": override.user.id,
            "username": override.user.username,
            "display_name": override.user.display_name,
            "starts_at": _utc_naive_to_rotation_local(
                override.starts_at,
                rotation,
            ).isoformat(timespec="minutes"),
            "ends_at": _utc_naive_to_rotation_local(
                override.ends_at,
                rotation,
            ).isoformat(timespec="minutes"),
            "reason": override.reason,
            "expired": override.ends_at <= datetime.utcnow(),
        }
        for override in rotations_repo.list_rotation_overrides(
            rotation_id,
            include_expired=include_expired,
        )
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
        return safe_exception_response(
            exc,
            error="validation_error",
            message="User cannot be used for this rotation override.",
            status_code=400,
        )

    starts_at = _rotation_local_to_utc_naive(payload.starts_at, rotation)
    ends_at = _rotation_local_to_utc_naive(payload.ends_at, rotation)

    if ends_at <= starts_at:
        return make_error_response(
            error="validation_error",
            message="ends_at must be greater than starts_at.",
            status_code=400,
        )

    override = rotations_repo.create_rotation_override(
        rotation_id=rotation_id,
        user_id=payload.user_id,
        starts_at=starts_at,
        ends_at=ends_at,
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


@rotations_bp.route("/<int:rotation_id>/layers", methods=["GET"])
def list_rotation_layers(rotation_id):
    rotation = rotations_repo.get_rotation(rotation_id)
    error = require_team_read(rotation.team_id)
    if error:
        return error

    return jsonify([
        serialize_rotation_layer(layer)
        for layer in rotations_repo.list_rotation_layers(rotation_id)
    ])


@rotations_bp.route("/<int:rotation_id>/layers", methods=["POST"])
def create_rotation_layer(rotation_id):
    rotation = rotations_repo.get_rotation(rotation_id)
    error = require_team_write(rotation.team_id)
    if error:
        return error

    payload, error = validate_body(RotationLayerCreateSchema)
    if error:
        return error

    layer = rotations_repo.create_rotation_layer(
        rotation_id=rotation_id,
        name=payload.name,
        description=payload.description,
        priority=payload.priority,
        start_at=payload.start_at,
        duration_seconds=payload.duration_seconds,
        rotation_type=payload.rotation_type,
        interval_value=payload.interval_value,
        interval_unit=payload.interval_unit,
        handoff_time=payload.handoff_time,
        handoff_weekday=payload.handoff_weekday,
        timezone=payload.timezone,
        enabled=payload.enabled,
    )

    write_audit(
        "rotation.layer.create",
        object_type="rotation",
        object_id=rotation_id,
        team_id=rotation.team.id,
        data=payload.model_dump(mode="json"),
    )

    return jsonify(serialize_rotation_layer(layer)), 201


@rotations_bp.route("/layers/<int:layer_id>", methods=["PUT"])
def update_rotation_layer(layer_id):
    layer_before = rotations_repo.get_rotation_layer(layer_id)
    error = require_team_write(layer_before.rotation.team_id)
    if error:
        return error

    payload, error = validate_body(RotationLayerUpdateSchema)
    if error:
        return error

    layer = rotations_repo.update_rotation_layer(
        layer_id,
        {
            "name": payload.name,
            "description": payload.description,
            "priority": payload.priority,
            "start_at": payload.start_at,
            "duration_seconds": payload.duration_seconds,
            "rotation_type": payload.rotation_type,
            "interval_value": payload.interval_value,
            "interval_unit": payload.interval_unit,
            "handoff_time": payload.handoff_time,
            "handoff_weekday": payload.handoff_weekday,
            "timezone": payload.timezone,
            "enabled": payload.enabled,
        },
    )

    write_audit(
        "rotation.layer.update",
        object_type="rotation",
        object_id=layer.rotation.id,
        team_id=layer.rotation.team.id,
        data=payload.model_dump(mode="json"),
    )

    return jsonify(serialize_rotation_layer(layer))


@rotations_bp.route("/layers/<int:layer_id>", methods=["DELETE"])
def delete_rotation_layer(layer_id):
    layer_before = rotations_repo.get_rotation_layer(layer_id)
    error = require_team_write(layer_before.rotation.team_id)
    if error:
        return error

    layer = rotations_repo.soft_delete_rotation_layer(layer_id)

    write_audit(
        "rotation.layer.delete",
        object_type="rotation",
        object_id=layer.rotation.id,
        team_id=layer.rotation.team.id,
        data={"layer_id": layer.id},
    )

    return jsonify({"deleted": True, "id": layer.id})


@rotations_bp.route("/layers/<int:layer_id>/members", methods=["GET"])
def list_rotation_layer_members(layer_id):
    layer = rotations_repo.get_rotation_layer(layer_id)
    error = require_team_read(layer.rotation.team_id)
    if error:
        return error

    return jsonify([
        serialize_rotation_layer_member(member)
        for member in rotations_repo.list_rotation_layer_members(
            layer_id,
            active_only=True,
            at=None,
            include_inactive_users=False,
        )
    ])


@rotations_bp.route("/layers/<int:layer_id>/members", methods=["POST"])
def add_rotation_layer_member(layer_id):
    layer = rotations_repo.get_rotation_layer(layer_id)
    error = require_team_write(layer.rotation.team_id)
    if error:
        return error

    payload, error = validate_body(RotationLayerMemberAddSchema)
    if error:
        return error

    try:
        rotations_repo.ensure_user_in_rotation_team(layer.rotation.id, payload.user_id)
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="validation_error",
            message="User cannot be added to this rotation layer.",
            status_code=400,
        )

    starts_at = _layer_local_to_utc_naive(payload.starts_at, layer)

    try:
        member = rotations_repo.add_rotation_layer_member(
            layer_id=layer_id,
            user_id=payload.user_id,
            position=payload.position,
            starts_at=starts_at,
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="rotation_layer_member_conflict",
            message="Rotation layer member conflicts with an existing member.",
            status_code=400,
        )

    write_audit(
        "rotation.layer.member.add",
        object_type="rotation",
        object_id=layer.rotation.id,
        team_id=layer.rotation.team.id,
        data=payload.model_dump(mode="json"),
    )

    return jsonify(serialize_rotation_layer_member(member)), 201


@rotations_bp.route("/layers/members/<int:member_id>", methods=["PUT"])
def update_rotation_layer_member(member_id):
    member_before = rotations_repo.get_rotation_layer_member(member_id)
    error = require_team_write(member_before.layer.rotation.team_id)
    if error:
        return error

    payload, error = validate_body(RotationLayerMemberUpdateSchema)
    if error:
        return error

    try:
        member = rotations_repo.update_rotation_layer_member(
            member_id=member_id,
            position=payload.position,
            active=payload.active,
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="validation_error",
            message="Invalid rotation layer member update request.",
            status_code=400,
        )

    write_audit(
        "rotation.layer.member.update",
        object_type="rotation",
        object_id=member.layer.rotation.id,
        team_id=member.layer.rotation.team.id,
        data={"member_id": member.id, **payload.model_dump()},
    )

    return jsonify(serialize_rotation_layer_member(member))


@rotations_bp.route("/layers/members/<int:member_id>", methods=["DELETE"])
def delete_rotation_layer_member(member_id):
    member = rotations_repo.get_rotation_layer_member(member_id)
    error = require_team_write(member.layer.rotation.team_id)
    if error:
        return error

    data = rotations_repo.delete_rotation_layer_member(member_id)

    write_audit(
        "rotation.layer.member.remove",
        object_type="rotation",
        object_id=data["rotation_id"],
        team_id=data["team_id"],
        data=data,
    )

    return jsonify({"deleted": True, "id": member_id})


@rotations_bp.route("/layers/<int:layer_id>/restrictions", methods=["GET"])
def list_rotation_layer_restrictions(layer_id):
    layer = rotations_repo.get_rotation_layer(layer_id)
    error = require_team_read(layer.rotation.team_id)
    if error:
        return error

    return jsonify([
        serialize_rotation_layer_restriction(item)
        for item in rotations_repo.list_rotation_layer_restrictions(layer_id)
    ])


@rotations_bp.route("/layers/<int:layer_id>/restrictions", methods=["PUT"])
def replace_rotation_layer_restrictions(layer_id):
    layer = rotations_repo.get_rotation_layer(layer_id)
    error = require_team_write(layer.rotation.team_id)
    if error:
        return error

    payload, error = validate_body(RotationLayerRestrictionsReplaceSchema)
    if error:
        return error

    restrictions = rotations_repo.replace_rotation_layer_restrictions(
        layer_id,
        [item.model_dump() for item in payload.restrictions],
    )

    write_audit(
        "rotation.layer.restrictions.replace",
        object_type="rotation",
        object_id=layer.rotation.id,
        team_id=layer.rotation.team.id,
        data=payload.model_dump(),
    )

    return jsonify([
        serialize_rotation_layer_restriction(item)
        for item in restrictions
    ])
