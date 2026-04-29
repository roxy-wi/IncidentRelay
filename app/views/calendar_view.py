from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from app.services.calendar_service import build_team_calendar
from app.services.rbac import require_team_read, parse_date_or_datetime


calendar_bp = Blueprint("calendar_api", __name__)


@calendar_bp.route("", methods=["GET"])
def get_calendar():
    """
    Return on-call calendar events for a team.
    """

    team_id = request.args.get("team_id", type=int)
    if not team_id:
        return jsonify({"error": "team_id is required"}), 400

    start_raw = request.args.get("start") or datetime.utcnow().date().isoformat()
    end_raw = request.args.get("end")

    start_at = parse_date_or_datetime(start_raw)
    end_at = parse_date_or_datetime(end_raw) if end_raw else start_at + timedelta(days=30)

    error = require_team_read(team_id)
    if error:
        return error
    return jsonify(build_team_calendar(team_id, start_at, end_at))
