from flask import Blueprint, jsonify, request

from app.api.schemas.matcher_presets import MatcherPresetCreateSchema, MatcherPresetUpdateSchema
from app.services.audit import write_audit
from app.services.rbac import (
    current_user,
    get_allowed_team_ids,
    require_team_read,
    require_team_write,
)
from app.services.routing.matcher import service
from app.services.validation import validate_body


matcher_presets_bp = Blueprint("matcher_presets_api", __name__)


@matcher_presets_bp.errorhandler(service.MatcherPresetError)
def handle_matcher_preset_error(error):
    """Convert matcher preset domain errors to API responses."""
    if isinstance(error, service.MatcherPresetNotFoundError):
        error_code = "matcher_preset_not_found"
        status = 404
    elif isinstance(error, service.MatcherPresetInUseError):
        error_code = "matcher_preset_in_use"
        status = 409
    elif isinstance(error, service.MatcherPresetConflictError):
        error_code = "matcher_preset_conflict"
        status = 409
    else:
        error_code = "matcher_preset_invalid"
        status = 400

    return jsonify({"error": error_code, "message": str(error)}), status


def _require_preset_read(preset_id):
    preset = service.get_preset(preset_id)
    error = require_team_read(preset.team_id)

    if error:
        return None, error

    return preset, None


def _require_preset_write(preset_id):
    preset = service.get_preset(preset_id)
    error = require_team_write(preset.team_id)

    if error:
        return None, error

    return preset, None


@matcher_presets_bp.route("", methods=["GET"])
def list_matcher_presets():
    """Return matcher presets visible to the current user."""
    team_id = request.args.get("team_id", type=int)
    enabled_only = request.args.get("enabled_only") == "1"

    if team_id:
        error = require_team_read(team_id)

        if error:
            return error

        team_ids = None
    else:
        team_ids = get_allowed_team_ids()

    presets = service.list_presets(
        team_id=team_id,
        team_ids=team_ids,
        enabled_only=enabled_only,
        current_user=current_user(),
    )

    return jsonify(presets)


@matcher_presets_bp.route("/<int:preset_id>", methods=["GET"])
def get_matcher_preset(preset_id):
    """Return one matcher preset and its usages."""
    preset, error = _require_preset_read(preset_id)

    if error:
        return error

    return jsonify(service.serialize_preset(preset, current_user(), include_usages=True))


@matcher_presets_bp.route("", methods=["POST"])
def create_matcher_preset():
    """Create or restore a matcher preset."""
    payload, error = validate_body(MatcherPresetCreateSchema)

    if error:
        return error

    error = require_team_write(payload.team_id)

    if error:
        return error

    preset = service.create_preset(payload)

    write_audit(
        "matcher_preset.create",
        object_type="matcher_preset",
        object_id=preset.id,
        group_id=preset.team.group_id,
        team_id=preset.team_id,
        data=payload.model_dump(),
    )

    return jsonify(service.serialize_preset(preset, current_user())), 201


@matcher_presets_bp.route("/<int:preset_id>", methods=["PUT"])
def update_matcher_preset(preset_id):
    """Update a matcher preset."""
    preset_before, error = _require_preset_write(preset_id)

    if error:
        return error

    payload, error = validate_body(MatcherPresetUpdateSchema)

    if error:
        return error

    preset = service.update_preset(preset_before.id, payload)

    write_audit(
        "matcher_preset.update",
        object_type="matcher_preset",
        object_id=preset.id,
        group_id=preset.team.group_id,
        team_id=preset.team_id,
        data=payload.model_dump(exclude_unset=True),
    )

    return jsonify(service.serialize_preset(preset, current_user(), include_usages=True))


@matcher_presets_bp.route("/<int:preset_id>", methods=["DELETE"])
def delete_matcher_preset(preset_id):
    """Soft-delete a matcher preset."""
    preset_before, error = _require_preset_write(preset_id)

    if error:
        return error

    preset = service.delete_preset(preset_before.id)

    write_audit(
        "matcher_preset.delete",
        object_type="matcher_preset",
        object_id=preset.id,
        group_id=preset.team.group_id,
        team_id=preset.team_id,
        data={"deleted": True},
    )

    return jsonify({"deleted": True, "id": preset.id})
