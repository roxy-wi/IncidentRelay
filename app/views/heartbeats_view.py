from flask import Blueprint, jsonify, request
from peewee import DoesNotExist, IntegrityError

from app.api.schemas.heartbeats import HeartbeatCreateSchema, HeartbeatPingSchema, HeartbeatUpdateSchema
from app.modules.db import heartbeats_repo, routes_repo, services_repo, teams_repo
from app.services.heartbeats.service import (
    generate_heartbeat_token,
    initialize_heartbeat_schedule,
    pause_heartbeat,
    process_overdue_heartbeats,
    receive_heartbeat_ping,
    resume_heartbeat,
)
from app.services.rbac import get_allowed_team_ids, require_team_or_group_resource_access, require_team_read
from app.services.serializers.heartbeats import serialize_heartbeat, serialize_heartbeat_ping
from app.services.validation import make_error_response, validate_body


heartbeats_bp = Blueprint("heartbeats_api", __name__)


def _base_url():
    return request.host_url.rstrip("/") if request else None


def _request_payload_or_empty():
    if request.is_json:
        return request.get_json(silent=True) or {}
    return {}


def _validate_heartbeat_scope(payload):
    error = require_team_or_group_resource_access(payload.team_id, write_required=True)
    if error:
        return None, None, None, error

    try:
        team = teams_repo.get_team(payload.team_id)
    except DoesNotExist:
        return None, None, None, make_error_response(
            "team_not_found",
            "Team was not found.",
            400,
        )

    try:
        route = routes_repo.get_route(payload.route_id)
    except DoesNotExist:
        return None, None, None, make_error_response(
            "route_not_found",
            "Heartbeat route was not found.",
            400,
        )

    if route.team_id != team.id:
        return None, None, None, make_error_response(
            "route_team_mismatch",
            "Heartbeat route must belong to the selected team.",
            400,
        )

    if route.source != "heartbeat":
        return None, None, None, make_error_response(
            "route_source_mismatch",
            "Heartbeat route source must be heartbeat.",
            400,
        )

    service = None
    if payload.service_id:
        service = services_repo.get_service_or_none(payload.service_id)
        if not service or service.team_id != team.id:
            return None, None, None, make_error_response(
                "service_team_mismatch",
                "Heartbeat service must belong to the selected team.",
                400,
            )

    return team, route, service, None


def _heartbeat_data(payload, *, token_prefix=None, token_hash=None, created_by_id=None):
    data = {
        "team": payload.team_id,
        "route": payload.route_id,
        "service": payload.service_id,
        "name": payload.name,
        "slug": payload.slug,
        "description": payload.description,
        "mode": payload.mode,
        "expected_interval_seconds": payload.expected_interval_seconds,
        "grace_period_seconds": payload.grace_period_seconds,
        "schedule_kind": payload.schedule_kind,
        "schedule_time": payload.schedule_time,
        "schedule_weekday": payload.schedule_weekday,
        "schedule_monthday": payload.schedule_monthday,
        "timezone": payload.timezone,
        "severity": payload.severity,
        "priority_slug": payload.priority_slug,
        "enabled": payload.enabled,
        "auto_resolve": payload.auto_resolve,
        "labels": payload.labels or {},
        "metadata": payload.metadata or {},
    }

    team = teams_repo.get_team(payload.team_id)
    data["group"] = team.group_id

    if token_prefix is not None:
        data["token_prefix"] = token_prefix
    if token_hash is not None:
        data["token_hash"] = token_hash
    if created_by_id is not None:
        data["created_by"] = created_by_id

    return data


@heartbeats_bp.route("", methods=["GET"])
def list_heartbeats():
    team_id = request.args.get("team_id", type=int)
    group_id = request.args.get("group_id", type=int)
    status = request.args.get("status") or None
    enabled_only = str(request.args.get("enabled", "")).lower() == "true"

    if team_id:
        error = require_team_read(team_id)
        if error:
            return error
        team_ids = [team_id]
    else:
        team_ids = get_allowed_team_ids(use_active_group=True)

    items = heartbeats_repo.list_heartbeats(
        team_ids=team_ids,
        group_id=group_id,
        enabled_only=enabled_only,
        status=status,
    )

    return jsonify([serialize_heartbeat(item) for item in items])


@heartbeats_bp.route("", methods=["POST"])
def create_heartbeat():
    payload, error = validate_body(HeartbeatCreateSchema)
    if error:
        return error

    _, _, _, error = _validate_heartbeat_scope(payload)
    if error:
        return error

    existing = heartbeats_repo.get_heartbeat_by_slug(payload.team_id, payload.slug, include_deleted=True)
    if existing and not existing.deleted:
        return make_error_response(
            "conflict",
            "Heartbeat slug must be unique within the team.",
            409,
        )

    raw_token, token_prefix, token_hash = generate_heartbeat_token()
    data = _heartbeat_data(
        payload,
        token_prefix=token_prefix,
        token_hash=token_hash,
        created_by_id=request.current_user.id if request.current_user else None,
    )

    try:
        item = heartbeats_repo.create_heartbeat(data)
    except IntegrityError:
        return make_error_response(
            "conflict",
            "Heartbeat with this slug or token already exists.",
            409,
        )

    initialize_heartbeat_schedule(item)
    item = heartbeats_repo.get_heartbeat(item.id)

    return jsonify(
        serialize_heartbeat(
            item,
            include_token=True,
            raw_token=raw_token,
            base_url=_base_url(),
        )
    ), 201


@heartbeats_bp.route("/<int:heartbeat_id>", methods=["GET"])
def get_heartbeat(heartbeat_id):
    item = heartbeats_repo.get_heartbeat(heartbeat_id)
    error = require_team_read(item.team_id)
    if error:
        return error

    pings = heartbeats_repo.list_pings(item.id, limit=50)
    return jsonify(serialize_heartbeat(item, pings=pings))


@heartbeats_bp.route("/<int:heartbeat_id>", methods=["PUT"])
def update_heartbeat(heartbeat_id):
    item = heartbeats_repo.get_heartbeat(heartbeat_id)
    error = require_team_or_group_resource_access(item.team_id, write_required=True)
    if error:
        return error

    payload, error = validate_body(HeartbeatUpdateSchema)
    if error:
        return error

    _, _, _, error = _validate_heartbeat_scope(payload)
    if error:
        return error

    existing = heartbeats_repo.get_heartbeat_by_slug(payload.team_id, payload.slug, include_deleted=True)
    if existing and existing.id != item.id and not existing.deleted:
        return make_error_response(
            "conflict",
            "Heartbeat slug must be unique within the team.",
            409,
        )

    data = _heartbeat_data(payload)
    if payload.status:
        data["status"] = payload.status

    item = heartbeats_repo.update_heartbeat(item, data)
    initialize_heartbeat_schedule(item)
    item = heartbeats_repo.get_heartbeat(item.id)
    return jsonify(serialize_heartbeat(item))


@heartbeats_bp.route("/<int:heartbeat_id>", methods=["DELETE"])
def delete_heartbeat(heartbeat_id):
    item = heartbeats_repo.get_heartbeat(heartbeat_id)
    error = require_team_or_group_resource_access(item.team_id, write_required=True)
    if error:
        return error

    heartbeats_repo.soft_delete_heartbeat(item)
    return jsonify({"deleted": True})


@heartbeats_bp.route("/<int:heartbeat_id>/pings", methods=["GET"])
def list_heartbeat_pings(heartbeat_id):
    item = heartbeats_repo.get_heartbeat(heartbeat_id)
    error = require_team_read(item.team_id)
    if error:
        return error

    limit = request.args.get("limit", default=50, type=int)
    limit = max(1, min(200, limit))
    return jsonify([serialize_heartbeat_ping(ping) for ping in heartbeats_repo.list_pings(item.id, limit=limit)])


@heartbeats_bp.route("/<int:heartbeat_id>/regenerate-token", methods=["POST"])
def regenerate_heartbeat_token(heartbeat_id):
    item = heartbeats_repo.get_heartbeat(heartbeat_id)
    error = require_team_or_group_resource_access(item.team_id, write_required=True)
    if error:
        return error

    raw_token, token_prefix, token_hash = generate_heartbeat_token()
    item = heartbeats_repo.update_heartbeat(item, {
        "token_prefix": token_prefix,
        "token_hash": token_hash,
    })
    return jsonify(
        serialize_heartbeat(
            item,
            include_token=True,
            raw_token=raw_token,
            base_url=_base_url(),
        )
    )


@heartbeats_bp.route("/<int:heartbeat_id>/pause", methods=["POST"])
def pause_heartbeat_endpoint(heartbeat_id):
    item = heartbeats_repo.get_heartbeat(heartbeat_id)
    error = require_team_or_group_resource_access(item.team_id, write_required=True)
    if error:
        return error

    return jsonify(serialize_heartbeat(pause_heartbeat(item)))


@heartbeats_bp.route("/<int:heartbeat_id>/resume", methods=["POST"])
def resume_heartbeat_endpoint(heartbeat_id):
    item = heartbeats_repo.get_heartbeat(heartbeat_id)
    error = require_team_or_group_resource_access(item.team_id, write_required=True)
    if error:
        return error

    return jsonify(serialize_heartbeat(resume_heartbeat(item)))


@heartbeats_bp.route("/check-overdue", methods=["POST"])
def check_overdue_heartbeats_endpoint():
    team_ids = get_allowed_team_ids(write_required=True, use_active_group=False)
    if not team_ids and not (request.current_user and request.current_user.is_admin):
        return make_error_response(
            "team_write_required",
            "Team manager or group editor role is required.",
            403,
        )

    team_scope = None if request.current_user and request.current_user.is_admin else team_ids
    return jsonify(process_overdue_heartbeats(team_ids=team_scope))


@heartbeats_bp.route("/ping/<token>", methods=["GET", "POST", "HEAD"])
def heartbeat_ping(token):
    if request.method == "HEAD":
        payload_data = {}
    else:
        body = _request_payload_or_empty()
        if body:
            payload, error = validate_body(HeartbeatPingSchema)
            if error:
                return error
            payload_data = payload.model_dump()
        else:
            payload_data = {"status": "completed", "payload": {}}

    item, error = receive_heartbeat_ping(
        token,
        payload=payload_data,
        remote_addr=request.headers.get("X-Forwarded-For", request.remote_addr),
        user_agent=request.headers.get("User-Agent"),
    )

    if error:
        return make_error_response(
            error["error"],
            error["message"],
            404,
        )

    if request.method == "HEAD":
        return "", 204

    return jsonify({
        "ok": True,
        "heartbeat": serialize_heartbeat(item),
    })
