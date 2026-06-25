import re

from flask import Blueprint, jsonify, request

from app.api.schemas.matchers import MatcherPreviewSchema
from app.modules.db import matcher_presets_repo
from app.services.rbac import require_team_read
from app.services.routing.matcher.matcher_preview import build_matcher_preview
from app.services.routing.matcher.matcher_suggestions import build_matcher_suggestions
from app.services.validation import make_error_response, validate_body

matchers_bp = Blueprint("matchers_api", __name__)


@matchers_bp.route("/suggestions", methods=["GET"])
def matcher_suggestions():
    """Return matcher label and field suggestions from recent alerts."""
    team_id = request.args.get("team_id", type=int)

    if not team_id:
        return jsonify({
            "error": "validation_error",
            "message": "team_id is required",
        }), 400

    error = require_team_read(team_id)

    if error:
        return error

    route_id = request.args.get("route_id", type=int)
    service_id = request.args.get("service_id", type=int)
    sample_limit = request.args.get("limit", default=200, type=int)
    values_limit = request.args.get("values_limit", default=20, type=int)

    suggestions = build_matcher_suggestions(
        team_id=team_id,
        route_id=route_id,
        service_id=service_id,
        sample_limit=sample_limit,
        values_limit=values_limit,
    )

    return jsonify(suggestions)


@matchers_bp.route("/preview", methods=["POST"])
def matcher_preview():
    """Return recent alerts matching unsaved matcher conditions."""
    payload, error = validate_body(MatcherPreviewSchema)

    if error:
        return error

    error = require_team_read(payload.team_id)

    if error:
        return error

    preset = None

    if payload.matcher_preset_id:
        preset = matcher_presets_repo.get_matcher_preset_or_none(
            payload.matcher_preset_id
        )

        if not preset or not preset.enabled or preset.team_id != payload.team_id:
            return make_error_response(
                "validation_error",
                "Matcher preset was not found or is unavailable.",
                400,
            )

    try:
        result = build_matcher_preview(
            team_id=payload.team_id,
            route_id=payload.route_id,
            service_id=payload.service_id,
            preset=preset,
            matchers=payload.matchers,
            scan_limit=payload.scan_limit,
            result_limit=payload.result_limit,
        )
    except (re.error, TypeError, ValueError) as exc:
        return make_error_response(
            "validation_error",
            "Matchers are invalid.",
            400,
            details=[
                {
                    "field": "matchers",
                    "loc": ["matchers"],
                    "message": str(exc),
                    "type": "invalid_matcher",
                }
            ],
        )

    return jsonify(result)
