from flask import Blueprint, jsonify, request

from app.api.schemas.silences import SilenceCreateSchema, SilenceUpdateSchema
from app.modules.db import silences_repo
from app.services.audit import write_audit
from app.services.rbac import (
    current_user,
    get_allowed_team_or_group_resource_ids,
    require_team_or_group_resource_access,
)
from app.services.serializers import attach_team_permissions
from app.services.validation import validate_body


silences_bp = Blueprint("silences_api", __name__)


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

    silence = silences_repo.create_silence(
        team_id=payload.team_id,
        name=payload.name,
        reason=payload.reason,
        matchers=payload.matchers,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        created_by=payload.created_by,
    )
    write_audit("silence.create", object_type="silence", object_id=silence.id, team_id=silence.team.id, data=payload.model_dump(mode="json"))
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

    silence = silences_repo.update_silence(
        silence_id,
        {
            "team": payload.team_id,
            "name": payload.name,
            "reason": payload.reason,
            "matchers": payload.matchers,
            "starts_at": payload.starts_at,
            "ends_at": payload.ends_at,
            "created_by": payload.created_by,
        },
    )
    write_audit("silence.update", object_type="silence", object_id=silence.id, team_id=silence.team.id, data=payload.model_dump(mode="json"))
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
    write_audit("silence.disable", object_type="silence", object_id=silence.id, team_id=silence.team.id)
    return jsonify(serialize_silence(silence, current_user=current_user()))


def serialize_silence(silence, current_user=None):
    """Serialize a silence rule."""
    data = {
        "id": silence.id,
        "team_id": silence.team.id,
        "team_name": silence.team.name,
        "team_slug": silence.team.slug,
        "name": silence.name,
        "reason": silence.reason,
        "matchers": silence.matchers,
        "starts_at": silence.starts_at.isoformat(),
        "ends_at": silence.ends_at.isoformat(),
        "created_by": silence.created_by.username if silence.created_by else None,
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
