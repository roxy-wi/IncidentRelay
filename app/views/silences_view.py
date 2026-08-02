from typing import Any

from flask import Blueprint, jsonify, request

from app.api.schemas.silences import SilenceCreateSchema, SilenceUpdateSchema
from app.modules.db import silences_repo
from app.modules.db.models import Silence, User
from app.services.audit import write_audit
from app.services.rbac import (
    current_user,
    get_allowed_team_or_group_resource_ids,
    require_team_or_group_resource_access,
)
from app.services.serializers.common import attach_team_permissions, serialize_utc_datetime
from app.services.routing.matcher import service as matcher_preset_service
from app.services.silences import reconcile_silence
from app.services.validation import make_error_response, validate_body


silences_bp = Blueprint("silences_api", __name__)


def _validate_silence_matcher_preset(team_id, preset_id):
    try:
        preset = matcher_preset_service.validate_preset_assignment(
            preset_id,
            team_id=team_id,
        )
    except matcher_preset_service.MatcherPresetNotFoundError as exc:
        return None, make_error_response(
            "matcher_preset_not_found",
            str(exc),
            400,
        )
    except matcher_preset_service.MatcherPresetError as exc:
        return None, make_error_response(
            "matcher_preset_invalid",
            str(exc),
            400,
        )

    return preset, None


@silences_bp.route("", methods=["GET"])
def list_silences():
    """Return silence rules."""
    team_id = request.args.get("team_id", type=int)
    include_expired_history = request.args.get("include_expired_history") in {
        "1",
        "true",
        "yes",
        "on",
    }

    if team_id:
        error = require_team_or_group_resource_access(team_id)
        if error:
            return error

        silences = silences_repo.list_silences(
            team_id=team_id,
            include_expired_history=include_expired_history,
        )
    else:
        silences = silences_repo.list_silences(
            team_ids=get_allowed_team_or_group_resource_ids(),
            include_expired_history=include_expired_history,
        )

    return jsonify([
        serialize_silence(silence, current_user=current_user())
        for silence in silences
    ])


@silences_bp.route("/<int:silence_id>", methods=["GET"])
def get_silence(silence_id):
    """
    Return a single silence.
    """

    silence = silences_repo.get_silence(silence_id)
    error = require_team_or_group_resource_access(silence.team_id)
    if error:
        return error
    return jsonify(serialize_silence(silence, current_user=current_user()))


@silences_bp.route("", methods=["POST"])
def create_silence():
    """
    Create a silence rule.
    """

    payload, error = validate_body(SilenceCreateSchema)
    if error:
        return error

    error = require_team_or_group_resource_access(
        payload.team_id,
        write_required=True,
    )
    if error:
        return error

    preset, preset_error = _validate_silence_matcher_preset(
        payload.team_id,
        payload.matcher_preset_id,
    )
    if preset_error:
        return preset_error

    silence = silences_repo.create_silence(
        team_id=payload.team_id,
        name=payload.name,
        reason=payload.reason,
        matcher_preset_id=preset.id if preset else None,
        matchers=payload.matchers,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        created_by=payload.created_by,
        apply_to_existing=payload.apply_to_existing,
    )
    write_audit(
        "silence.create",
        object_type="silence",
        object_id=silence.id,
        team_id=silence.team.id,
        data=payload.model_dump(mode="json"),
    )
    reconcile_silence(silence, trigger_source="api")
    return jsonify(serialize_silence(silence, current_user=current_user())), 201


@silences_bp.route("/<int:silence_id>", methods=["PUT"])
def update_silence(silence_id):
    """
    Update a silence rule.
    """

    payload, error = validate_body(SilenceUpdateSchema)
    if error:
        return error

    current_silence = silences_repo.get_silence(silence_id)
    error = require_team_or_group_resource_access(
        current_silence.team_id,
        write_required=True,
    )
    if error:
        return error
    if payload.team_id != current_silence.team_id:
        error = require_team_or_group_resource_access(
            payload.team_id,
            write_required=True,
        )
        if error:
            return error

    preset, preset_error = _validate_silence_matcher_preset(
        payload.team_id,
        payload.matcher_preset_id,
    )
    if preset_error:
        return preset_error

    silence = silences_repo.update_silence(
        silence_id,
        {
            "team": payload.team_id,
            "name": payload.name,
            "reason": payload.reason,
            "matcher_preset": preset.id if preset else None,
            "matchers": payload.matchers,
            "starts_at": payload.starts_at,
            "ends_at": payload.ends_at,
            "created_by": payload.created_by,
            "apply_to_existing": payload.apply_to_existing,
        },
    )
    write_audit(
        "silence.update",
        object_type="silence",
        object_id=silence.id,
        team_id=silence.team.id,
        data=payload.model_dump(mode="json"),
    )
    reconcile_silence(silence, trigger_source="api")
    return jsonify(serialize_silence(silence, current_user=current_user()))


@silences_bp.route("/<int:silence_id>/enable", methods=["POST"])
def enable_silence(silence_id: int):
    """Enable a silence rule."""
    current_silence = silences_repo.get_silence(silence_id)
    error = require_team_or_group_resource_access(
        current_silence.team_id,
        write_required=True,
    )
    if error:
        return error

    silence = silences_repo.enable_silence(silence_id)
    write_audit(
        "silence.enable",
        object_type="silence",
        object_id=silence.id,
        team_id=silence.team.id,
    )
    reconcile_silence(silence, trigger_source="api")
    return jsonify(serialize_silence(silence, current_user=current_user()))


@silences_bp.route("/<int:silence_id>", methods=["DELETE"])
def delete_silence(silence_id):
    """
    Disable a silence rule.
    """

    current_silence = silences_repo.get_silence(silence_id)
    error = require_team_or_group_resource_access(
        current_silence.team_id,
        write_required=True,
    )
    if error:
        return error
    silence = silences_repo.disable_silence(silence_id)
    write_audit(
        "silence.disable",
        object_type="silence",
        object_id=silence.id,
        team_id=silence.team.id,
    )
    reconcile_silence(silence, trigger_source="api")
    return jsonify(serialize_silence(silence, current_user=current_user()))


def serialize_silence(
    silence: Silence,
    current_user: User | None = None,
) -> dict[str, Any]:
    """Serialize a silence rule."""
    matcher_preset = (
        silence.matcher_preset
        if getattr(silence, "matcher_preset_id", None)
        else None
    )
    data = {
        "id": silence.id,
        "team_id": silence.team.id,
        "team_name": silence.team.name,
        "team_slug": silence.team.slug,
        "name": silence.name,
        "reason": silence.reason,
        "matcher_preset_id": matcher_preset.id if matcher_preset else None,
        "matcher_preset": {
            "id": matcher_preset.id,
            "name": matcher_preset.name,
            "version": matcher_preset.version,
            "enabled": matcher_preset.enabled,
        } if matcher_preset else None,
        "matchers": silence.matchers or {},
        "starts_at": serialize_utc_datetime(silence.starts_at),
        "ends_at": serialize_utc_datetime(silence.ends_at),
        "created_by": silence.created_by.username if silence.created_by else None,
        "apply_to_existing": bool(silence.apply_to_existing),
        "enabled": silence.enabled,
    }

    data = attach_team_permissions(data, silence.team.id, current_user)

    if current_user:
        from app.services.rbac import can_access_team_or_group_resource

        data.setdefault("permissions", {})["can_write"] = (
            can_access_team_or_group_resource(
                current_user,
                silence.team.id,
                write_required=True,
            )
        )

    return data
