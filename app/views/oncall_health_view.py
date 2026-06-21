from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from app.modules.db import rotations_repo
from app.services.oncall_health import (
    DEFAULT_HEALTH_SAMPLE_MINUTES,
    check_rotation_health,
    check_team_oncall_health,
    get_rotation_or_none,
    get_team_or_none,
    get_rotation_health_summary,
    get_team_health_summary,
)
from app.services.rbac import require_team_read
from app.services.validation import make_error_response

oncall_health_bp = Blueprint("oncall_health_api", __name__)


def _parse_bool(value, default=False):
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_positive_int(name: str, default: int, *, minimum: int = 1, maximum: int | None = None):
    raw_value = request.args.get(name)
    if raw_value is None or raw_value == "":
        return default, None

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None, make_error_response(
            error="validation_error",
            message=f"Query parameter '{name}' must be an integer.",
            status_code=400,
        )

    if value < minimum:
        return None, make_error_response(
            error="validation_error",
            message=f"Query parameter '{name}' must be >= {minimum}.",
            status_code=400,
        )

    if maximum is not None and value > maximum:
        return None, make_error_response(
            error="validation_error",
            message=f"Query parameter '{name}' must be <= {maximum}.",
            status_code=400,
        )

    return value, None


def _parse_datetime_arg(name: str):
    raw_value = request.args.get(name)
    if not raw_value:
        return None, None

    try:
        return datetime.fromisoformat(raw_value.replace("Z", "+00:00")), None
    except ValueError:
        return None, make_error_response(
            error="validation_error",
            message=f"Query parameter '{name}' must be an ISO datetime.",
            status_code=400,
        )


def _health_query_options():
    days, error = _parse_positive_int("days", 14, minimum=1, maximum=90)
    if error:
        return None, error

    sample_minutes, error = _parse_positive_int(
        "sample_minutes",
        DEFAULT_HEALTH_SAMPLE_MINUTES,
        minimum=1,
        maximum=1440,
    )
    if error:
        return None, error

    starts_at, error = _parse_datetime_arg("starts_at")
    if error:
        return None, error

    ends_at, error = _parse_datetime_arg("ends_at")
    if error:
        return None, error

    if starts_at and not ends_at:
        ends_at = starts_at + timedelta(days=days)

    include_schedule_gaps = _parse_bool(
        request.args.get("include_schedule_gaps"),
        default=True,
    )

    return {
        "starts_at": starts_at,
        "ends_at": ends_at,
        "sample_minutes": sample_minutes,
        "include_schedule_gaps": include_schedule_gaps,
    }, None


@oncall_health_bp.route("/rotations/<int:rotation_id>", methods=["GET"])
def get_rotation_health(rotation_id):
    rotation = get_rotation_or_none(rotation_id)
    if not rotation:
        return make_error_response(
            error="not_found",
            message="Rotation not found.",
            status_code=404,
        )

    error = require_team_read(rotation.team_id)
    if error:
        return error

    options, error = _health_query_options()
    if error:
        return error

    payload = check_rotation_health(
        rotation,
        starts_at=options["starts_at"],
        ends_at=options["ends_at"],
        include_schedule_gaps=options["include_schedule_gaps"],
        sample_minutes=options["sample_minutes"],
    )
    return jsonify(payload)


@oncall_health_bp.route("/rotations/summaries", methods=["GET"])
def list_rotation_health_summaries():
    raw_ids = request.args.getlist("rotation_id") or request.args.getlist("id")
    rotation_ids = []

    for raw_id in raw_ids:
        try:
            rotation_id = int(raw_id)
        except (TypeError, ValueError):
            return make_error_response(
                error="validation_error",
                message="Query parameter 'rotation_id' must be an integer.",
                status_code=400,
            )

        if rotation_id not in rotation_ids:
            rotation_ids.append(rotation_id)

    if not rotation_ids:
        return jsonify({"items": [], "by_id": {}})

    rotations = rotations_repo.list_rotations_for_health(rotation_ids)
    rotations_by_id = {rotation.id: rotation for rotation in rotations}

    items = []
    by_id = {}

    for rotation_id in rotation_ids:
        rotation = rotations_by_id.get(rotation_id)
        if not rotation:
            continue

        error = require_team_read(rotation.team_id)
        if error:
            continue

        summary = get_rotation_health_summary(rotation)

        items.append({
            "rotation_id": rotation.id,
            "summary": summary,
        })
        by_id[str(rotation.id)] = summary

    return jsonify({
        "items": items,
        "by_id": by_id,
    })


@oncall_health_bp.route("/teams/summaries", methods=["GET"])
def list_team_health_summaries():
    raw_ids = request.args.getlist("team_id") or request.args.getlist("id")
    team_ids = []

    for raw_id in raw_ids:
        try:
            team_id = int(raw_id)
        except (TypeError, ValueError):
            return make_error_response(
                error="validation_error",
                message="Query parameter 'team_id' must be an integer.",
                status_code=400,
            )

        if team_id not in team_ids:
            team_ids.append(team_id)

    if not team_ids:
        return jsonify({
            "items": [],
            "by_id": {},
        })

    if len(team_ids) > 200:
        return make_error_response(
            error="validation_error",
            message="At most 200 team_id values are allowed.",
            status_code=400,
        )

    items = []
    by_id = {}

    for team_id in team_ids:
        team = get_team_or_none(team_id)
        if not team:
            continue

        error = require_team_read(team.id)
        if error:
            continue

        summary = get_team_health_summary(team)

        items.append({
            "team_id": team.id,
            "summary": summary,
        })
        by_id[str(team.id)] = summary

    return jsonify({
        "items": items,
        "by_id": by_id,
    })


@oncall_health_bp.route("/teams/<int:team_id>", methods=["GET"])
def get_team_health(team_id):
    team = get_team_or_none(team_id)
    if not team:
        return make_error_response(
            error="not_found",
            message="Team not found.",
            status_code=404,
        )

    error = require_team_read(team.id)
    if error:
        return error

    options, error = _health_query_options()
    if error:
        return error

    payload = check_team_oncall_health(
        team,
        starts_at=options["starts_at"],
        ends_at=options["ends_at"],
        include_schedule_gaps=options["include_schedule_gaps"],
        sample_minutes=options["sample_minutes"],
    )
    return jsonify(payload)
