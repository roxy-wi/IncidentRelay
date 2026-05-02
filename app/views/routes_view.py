from flask import Blueprint, jsonify, request

from app.api.schemas.routes import RouteChannelsReplaceSchema, RouteCreateSchema, RouteUpdateSchema
from app.modules.db import routes_repo, channels_repo
from app.services.auth import create_raw_token, hash_token
from app.services.audit import write_audit
from app.services.rbac import get_allowed_team_ids, require_team_read, require_team_write
from app.services.serializers import serialize_route
from app.services.validation import validate_body


routes_bp = Blueprint("routes_api", __name__)


def validate_route_channels(team_id, channel_ids):
    """
    Ensure all route channels belong to the same team as the route.
    """
    for channel_id in channel_ids:
        channel = channels_repo.get_channel(channel_id)

        if channel.team_id != team_id:
            return jsonify({
                "error": "Channel does not belong to route team",
                "channel_id": channel_id,
                "team_id": team_id,
            }), 400

        error = require_team_write(channel.team_id)
        if error:
            return error

    return None


@routes_bp.route("", methods=["GET"])
def list_routes():
    """
    Return alert routes.
    """

    team_id = request.args.get("team_id", type=int)

    if team_id:
        error = require_team_read(team_id)
        if error:
            return error
        routes = routes_repo.list_routes(team_id=team_id)
    else:
        routes = routes_repo.list_routes(team_ids=get_allowed_team_ids())

    return jsonify([serialize_route(route) for route in routes])


@routes_bp.route("/<int:route_id>", methods=["GET"])
def get_route(route_id):
    """
    Return a single route.
    """

    route = routes_repo.get_route(route_id)
    error = require_team_read(route.team_id)

    if error:
        return error

    return jsonify(serialize_route(route))


@routes_bp.route("", methods=["POST"])
def create_route():
    """
    Create an alert route with rotation, channels and route intake token.
    """

    payload, error = validate_body(RouteCreateSchema)
    if error:
        return error

    error = require_team_write(payload.team_id)
    if error:
        return error

    channel_error = validate_route_channels(payload.team_id, payload.channel_ids)
    if channel_error:
        return channel_error

    raw_token = create_raw_token()

    route = routes_repo.create_route(
        team_id=payload.team_id,
        name=payload.name,
        source=payload.source,
        rotation_id=payload.rotation_id,
        matchers=payload.matchers,
        group_by=payload.group_by,
        enabled=payload.enabled,
        intake_token_prefix=raw_token[:12],
        intake_token_hash=hash_token(raw_token),
    )

    for channel_id in payload.channel_ids:
        routes_repo.link_route_channel(route.id, channel_id)

    write_audit(
        "route.create",
        object_type="route",
        object_id=route.id,
        team_id=route.team.id,
        data={**payload.model_dump(), "intake_token": "***"},
    )

    response = serialize_route(route)
    response["intake_token"] = raw_token

    return jsonify(response), 201


@routes_bp.route("/<int:route_id>", methods=["PUT"])
def update_route(route_id):
    """
    Update an alert route and its channel links.
    """

    payload, error = validate_body(RouteUpdateSchema)
    if error:
        return error

    current_route = routes_repo.get_route(route_id)
    error = require_team_write(current_route.team_id)

    if error:
        return error

    if payload.team_id != current_route.team_id:
        error = require_team_write(payload.team_id)
        if error:
            return error

    channel_error = validate_route_channels(payload.team_id, payload.channel_ids)
    if channel_error:
        return channel_error

    route = routes_repo.update_route(
        route_id,
        {
            "team": payload.team_id,
            "name": payload.name,
            "source": payload.source,
            "rotation": payload.rotation_id,
            "matchers": payload.matchers,
            "group_by": payload.group_by,
            "enabled": payload.enabled,
        },
    )

    routes_repo.replace_route_channels(route.id, payload.channel_ids)
    route = routes_repo.get_route(route_id)

    write_audit(
        "route.update",
        object_type="route",
        object_id=route.id,
        team_id=route.team.id,
        data=payload.model_dump(),
    )

    return jsonify(serialize_route(route))


@routes_bp.route("/<int:route_id>", methods=["DELETE"])
def delete_route(route_id):
    """
    Disable an alert route.
    """

    route_before = routes_repo.get_route(route_id)
    error = require_team_write(route_before.team_id)

    if error:
        return error

    route = routes_repo.disable_route(route_id)

    write_audit("route.disable", object_type="route", object_id=route.id, team_id=route.team.id)
    return jsonify(serialize_route(route))


@routes_bp.route("/<int:route_id>/intake-token", methods=["POST"])
def regenerate_route_intake_token(route_id):
    """
    Regenerate the alert intake token for a route.
    """

    route = routes_repo.get_route(route_id)
    error = require_team_write(route.team_id)

    if error:
        return error

    raw_token = create_raw_token()
    route = routes_repo.set_route_intake_token(route_id, raw_token[:12], hash_token(raw_token))

    write_audit(
        "route.intake_token.regenerate",
        object_type="route",
        object_id=route.id,
        team_id=route.team.id,
    )

    response = serialize_route(route)
    response["intake_token"] = raw_token

    return jsonify(response)


@routes_bp.route("/<int:route_id>/channels", methods=["PUT"])
def replace_route_channels(route_id):
    """
    Replace all channels linked to a route.
    """

    payload, error = validate_body(RouteChannelsReplaceSchema)
    if error:
        return error

    route_before = routes_repo.get_route(route_id)
    error = require_team_write(route_before.team_id)

    if error:
        return error

    channel_error = validate_route_channels(route_before.team_id, payload.channel_ids)
    if channel_error:
        return channel_error

    routes_repo.replace_route_channels(route_id, payload.channel_ids)
    route = routes_repo.get_route(route_id)

    write_audit(
        "route.channels.replace",
        object_type="route",
        object_id=route_id,
        team_id=route.team.id,
        data=payload.model_dump(),
    )

    return jsonify(serialize_route(route))


@routes_bp.route("/<int:route_id>/channels/<int:channel_id>", methods=["POST"])
def add_route_channel(route_id, channel_id):
    """
    Link a channel to a route.
    """

    route_before = routes_repo.get_route(route_id)
    error = require_team_write(route_before.team_id)

    if error:
        return error

    channel_error = validate_route_channels(route_before.team_id, [channel_id])
    if channel_error:
        return channel_error

    link = routes_repo.link_route_channel(route_id, channel_id)

    write_audit(
        "route.channel.add",
        object_type="route",
        object_id=route_id,
        team_id=link.route.team.id,
        data={"channel_id": channel_id},
    )

    return jsonify({"id": link.id}), 201


@routes_bp.route("/<int:route_id>/channels/<int:channel_id>", methods=["DELETE"])
def delete_route_channel(route_id, channel_id):
    """
    Remove a channel from a route.
    """

    route_before = routes_repo.get_route(route_id)
    error = require_team_write(route_before.team_id)

    if error:
        return error

    routes_repo.unlink_route_channel(route_id, channel_id)
    return jsonify({"status": "deleted"})
