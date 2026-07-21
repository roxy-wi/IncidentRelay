from datetime import datetime, timedelta, timezone as dt_timezone

from flask import Blueprint, jsonify, request, Response
from peewee import DoesNotExist

from app.services.calendar_service import build_team_calendar
from app.services.rbac import parse_date_or_datetime, require_team_oncall_read, require_team_write
from app.modules.db import calendar_feeds_repo
from app.services.calendar_feeds import (
    build_ics_for_calendar_feed,
    generate_calendar_feed_token,
    get_calendar_feed_by_token,
    serialize_calendar_feed,
)
from app.modules.common import utc_now

calendar_bp = Blueprint("calendar_api", __name__)

_DATE_FORMAT_MESSAGE = (
    "Invalid date or datetime format. Use ISO 8601 date or datetime, "
    "for example 2026-04-01 or 2026-04-01T00:00:00."
)


def _validation_detail(field, value, message, error_type="value_error"):
    """Build an API validation error detail for query parameters."""
    return {
        "field": field,
        "input": value,
        "loc": [field],
        "message": message,
        "type": error_type,
    }


def _validation_response(details):
    """Return a validation error response matching the common API shape."""
    return jsonify(
        {
            "details": details,
            "error": "validation_error",
            "message": "Request validation failed",
        }
    ), 400


def _parse_calendar_datetime(field, value):
    """Parse a calendar query datetime and return (value, validation_detail)."""
    if value in (None, ""):
        return None, None

    try:
        return parse_date_or_datetime(value), None
    except (TypeError, ValueError):
        return None, _validation_detail(
            field,
            value,
            _DATE_FORMAT_MESSAGE,
            error_type="datetime_parsing",
        )


@calendar_bp.route("", methods=["GET"])
def get_calendar():
    """Return on-call calendar events for a team."""
    team_id = request.args.get("team_id", type=int)
    if not team_id:
        return jsonify({"error": "team_id is required"}), 400

    start_raw = request.args.get("start") or utc_now().date().isoformat()
    end_raw = request.args.get("end")

    details = []
    start_at, start_error = _parse_calendar_datetime("start", start_raw)
    if start_error:
        details.append(start_error)

    end_at = None
    if end_raw:
        end_at, end_error = _parse_calendar_datetime("end", end_raw)
        if end_error:
            details.append(end_error)

    if details:
        return _validation_response(details)

    if end_at is None:
        end_at = start_at + timedelta(days=30)

    if end_at <= start_at:
        return _validation_response(
            [
                _validation_detail(
                    "end",
                    end_raw,
                    "end must be after start",
                )
            ]
        )

    error = require_team_oncall_read(team_id)
    if error:
        return error

    query_start_at = start_at
    query_end_at = end_at

    # Calendar inputs are local date boundaries.
    # On-call shifts are calculated in rotation/layer timezones and stored/processed as UTC.
    # Expand query range so local midnight handoffs are not clipped by UTC midnight.
    build_start_at = start_at - timedelta(days=1)
    build_end_at = end_at + timedelta(days=1)

    events = build_team_calendar(team_id, build_start_at, build_end_at)

    return jsonify(
        [
            event
            for event in events
            if event_overlaps_range(event, query_start_at, query_end_at)
        ]
    )


@calendar_bp.route("/feeds", methods=["GET"])
def list_calendar_feeds():
    team_id = request.args.get("team_id", type=int)

    if not team_id:
        return jsonify({"error": "team_id_required"}), 400

    error = require_team_write(team_id)
    if error:
        return error

    feeds = calendar_feeds_repo.list_calendar_feeds(team_id)

    return jsonify([
        serialize_calendar_feed(feed)
        for feed in feeds
    ])


@calendar_bp.route("/feeds", methods=["POST"])
def create_calendar_feed():
    payload = request.get_json(silent=True) or {}

    team_id = payload.get("team_id")
    if not team_id:
        return jsonify({"error": "team_id_required"}), 400

    error = require_team_write(team_id)
    if error:
        return error

    token, prefix, token_hash = generate_calendar_feed_token()

    feed = calendar_feeds_repo.create_calendar_feed(
        team_id=team_id,
        name=payload.get("name") or "On-call calendar",
        token_prefix=prefix,
        token_hash=token_hash,
        created_by=request.current_user,
        past_days=int(payload.get("past_days") or 7),
        future_days=int(payload.get("future_days") or 90),
    )

    return jsonify(
        serialize_calendar_feed(
            feed,
            base_url=request.url_root.rstrip("/"),
            token=token,
        )
    ), 201


@calendar_bp.route("/feeds/<int:feed_id>/token", methods=["POST"])
def regenerate_calendar_feed_token(feed_id):
    try:
        feed = calendar_feeds_repo.get_calendar_feed(feed_id)
    except DoesNotExist:
        return jsonify({"error": "calendar_feed_not_found"}), 404

    error = require_team_write(feed.team.id)
    if error:
        return error

    token, prefix, token_hash = generate_calendar_feed_token()

    feed = calendar_feeds_repo.update_calendar_feed(
        feed,
        token_prefix=prefix,
        token_hash=token_hash,
        enabled=True,
    )

    return jsonify(
        serialize_calendar_feed(
            feed,
            base_url=request.url_root.rstrip("/"),
            token=token,
        )
    )


@calendar_bp.route("/feeds/<int:feed_id>", methods=["DELETE"])
def delete_calendar_feed(feed_id):
    try:
        feed = calendar_feeds_repo.get_calendar_feed(feed_id)
    except DoesNotExist:
        return jsonify({"error": "calendar_feed_not_found"}), 404

    error = require_team_write(feed.team.id)
    if error:
        return error

    calendar_feeds_repo.soft_delete_calendar_feed(feed)

    return jsonify({"deleted": True, "id": feed_id})


@calendar_bp.route("/feeds/<token>.ics", methods=["GET"])
def export_calendar_feed(token):
    feed = get_calendar_feed_by_token(token)

    if not feed:
        return Response("Calendar feed not found\n", status=404, mimetype="text/plain")

    if not feed.team or feed.team.deleted or not feed.team.active:
        return Response("Calendar feed is not available\n", status=403, mimetype="text/plain")

    if feed.team.group and (
        feed.team.group.deleted or not feed.team.group.active
    ):
        return Response("Calendar feed is not available\n", status=403, mimetype="text/plain")

    body = build_ics_for_calendar_feed(feed)
    calendar_feeds_repo.mark_calendar_feed_used(feed)

    response = Response(body, mimetype="text/calendar; charset=utf-8")
    response.headers["Content-Disposition"] = (
        f'inline; filename="incidentrelay-team-{feed.team.id}.ics"'
    )
    response.headers["Cache-Control"] = "no-store"

    return response


def _as_utc_naive(value):
    if value.tzinfo is None:
        return value

    return value.astimezone(dt_timezone.utc).replace(tzinfo=None)


def _parse_calendar_event_datetime(value):
    if not value:
        return None

    value = str(value)

    # Python 3.10 datetime.fromisoformat() does not parse "Z",
    # so convert it to a regular UTC offset.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    parsed = datetime.fromisoformat(value)

    return _as_utc_naive(parsed)


def event_overlaps_range(event, start_at, end_at):
    event_start = _parse_calendar_event_datetime(event.get("start"))
    event_end = _parse_calendar_event_datetime(event.get("end"))

    if not event_start or not event_end:
        return False

    start_at = _as_utc_naive(start_at)
    end_at = _as_utc_naive(end_at)

    return event_start < end_at and event_end > start_at
