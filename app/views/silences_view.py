from flask import Blueprint, jsonify, request

from app.api.schemas.silences import SilenceCreateSchema, SilenceUpdateSchema
from app.modules.db import silences_repo
from app.services.audit import write_audit
from app.services.rbac import get_allowed_team_ids, require_team_read, require_team_write
from app.services.validation import validate_body


silences_bp = Blueprint("silences_api", __name__)


@silences_bp.route("", methods=["GET"])
def list_silences():
    """
    Return silence rules.
    """

    team_id = request.args.get("team_id", type=int)
    if team_id:
        error = require_team_read(team_id)
        if error:
            return error
        silences = silences_repo.list_silences(team_id=team_id)
    else:
        silences = silences_repo.list_silences(team_ids=get_allowed_team_ids())
    return jsonify([serialize_silence(silence) for silence in silences])


@silences_bp.route("/<int:silence_id>", methods=["GET"])
def get_silence(silence_id):
    """
    Return a single silence.
    """

    silence = silences_repo.get_silence(silence_id)
    error = require_team_read(silence.team_id)
    if error:
        return error
    return jsonify(serialize_silence(silence))


@silences_bp.route("", methods=["POST"])
def create_silence():
    """
    Create a silence rule.
    """

    payload, error = validate_body(SilenceCreateSchema)
    if error:
        return error

    error = require_team_write(payload.team_id)
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
    return jsonify(serialize_silence(silence)), 201


@silences_bp.route("/<int:silence_id>", methods=["PUT"])
def update_silence(silence_id):
    """
    Update a silence rule.
    """

    payload, error = validate_body(SilenceUpdateSchema)
    if error:
        return error

    current_silence = silences_repo.get_silence(silence_id)
    error = require_team_write(current_silence.team_id)
    if error:
        return error
    if payload.team_id != current_silence.team_id:
        error = require_team_write(payload.team_id)
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
    return jsonify(serialize_silence(silence))


@silences_bp.route("/<int:silence_id>", methods=["DELETE"])
def delete_silence(silence_id):
    """
    Disable a silence rule.
    """

    current_silence = silences_repo.get_silence(silence_id)
    error = require_team_write(current_silence.team_id)
    if error:
        return error
    silence = silences_repo.disable_silence(silence_id)
    write_audit("silence.disable", object_type="silence", object_id=silence.id, team_id=silence.team.id)
    return jsonify(serialize_silence(silence))


def serialize_silence(silence):
    """
    Serialize a silence rule.
    """

    return {
        "id": silence.id,
        "team_id": silence.team.id,
        "team_slug": silence.team.slug,
        "name": silence.name,
        "reason": silence.reason,
        "matchers": silence.matchers,
        "starts_at": silence.starts_at.isoformat(),
        "ends_at": silence.ends_at.isoformat(),
        "created_by": silence.created_by.username if silence.created_by else None,
        "enabled": silence.enabled,
    }
