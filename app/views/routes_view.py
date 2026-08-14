from flask import Blueprint, jsonify, request
from peewee import DoesNotExist, IntegrityError

from app.api.schemas.routes import RouteChannelsReplaceSchema, RouteCreateSchema, RouteUpdateSchema
from app.services.db_errors import handle_integrity_error
from app.modules.db import (
    routes_repo,
    channels_repo,
    rotations_repo,
    escalation_policies_repo,
    services_repo,
)
from app.services.integrations.auth import create_raw_token, hash_token
from app.services.audit import write_audit
from app.services.rbac import (
    current_user,
    get_allowed_team_ids,
    require_team_read,
    require_team_or_group_resource_access,
)
from app.services.serializers.routes import serialize_route
from app.services.validation import make_error_response, validate_body
from app.services.routing.matcher import service as matcher_preset_service
from app.services.service_catalog.reconciliation import reconcile_route_services


routes_bp = Blueprint("routes_api", __name__)


def require_route_resource_write(team_id):
    """Require write access to team-owned route resources."""
    return require_team_or_group_resource_access(
        team_id,
        write_required=True,
    )


def validate_route_matcher_preset(team_id, preset_id):
    """Validate route matcher preset assignment."""
    try:
        preset = matcher_preset_service.validate_preset_assignment(preset_id, team_id=team_id)
    except matcher_preset_service.MatcherPresetNotFoundError as exc:
        return None, make_error_response("matcher_preset_not_found", "Matcher preset was not found.", 400)
    except matcher_preset_service.MatcherPresetError as exc:
        return None, make_error_response("matcher_preset_invalid", "Matcher preset is invalid or unavailable.", 400)

    return preset, None


def route_name_conflict_response(name):
    """Return a consistent conflict response for route names."""
    return jsonify(
        {
            "error": "conflict",
            "message": (
                "Route with this name already exists "
                "in this team"
            ),
            "details": [
                {
                    "field": "name",
                    "loc": ["name"],
                    "message": (
                        "Route name must be unique "
                        "within a team"
                    ),
                    "type": "unique",
                    "input": name,
                }
            ],
        }
    ), 409


def mask_route_integration_config(config):
    """Mask provider-specific secrets before audit/API output."""
    config = dict(config or {})

    sentry = dict(config.get("sentry") or {})
    if sentry.get("webhook_secret"):
        sentry["webhook_secret"] = "***"

    if sentry:
        config["sentry"] = sentry

    return config


def clean_route_config_string(value):
    """Normalize optional route integration config string values."""
    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    return value


def clean_sentry_base_url(value):
    """Normalize optional Sentry base URL."""
    value = clean_route_config_string(value)

    if not value:
        return None

    return value.rstrip("/")


def build_route_integration_config(payload, current_route=None):
    """Build provider-specific route integration config."""
    incoming = payload.integration_config or {}

    if payload.source == "sentry":
        incoming_sentry = dict(
            incoming.get("sentry") or {}
        )

        current_config = (
            current_route.integration_config or {}
            if current_route else {}
        )
        current_sentry = dict(
            current_config.get("sentry") or {}
        )

        new_secret = str(
            incoming_sentry.get("webhook_secret") or ""
        ).strip()
        current_secret = current_sentry.get(
            "webhook_secret"
        )

        secret = new_secret or current_secret

        base_url = clean_sentry_base_url(
            incoming_sentry.get("base_url")
        )

        organization_slug = clean_route_config_string(
            incoming_sentry.get("organization_slug")
        )

        sentry_config = {}

        if secret:
            sentry_config["webhook_secret"] = secret

        if base_url:
            sentry_config["base_url"] = base_url

        if organization_slug:
            sentry_config["organization_slug"] = organization_slug

        return {
            "sentry": sentry_config,
        }

    if payload.source == "aws_sns":
        incoming_aws_sns = dict(
            incoming.get("aws_sns") or {}
        )

        topic_arn = str(
            incoming_aws_sns.get("topic_arn") or ""
        ).strip()

        return {
            "aws_sns": {
                "topic_arn": topic_arn,
            },
        }

    return {}


def validate_route_service(team_id, service_id):
    """Ensure selected service exists, is enabled and belongs to the route team."""
    if not service_id:
        return None

    try:
        service = services_repo.get_service(service_id)
    except DoesNotExist:
        return jsonify({
            "error": "service_not_found",
            "message": "Service was not found",
            "service_id": service_id,
        }), 400

    if service.team_id != team_id:
        return jsonify({
            "error": "service_team_mismatch",
            "message": "Service does not belong to route team",
            "service_id": service_id,
            "service_team_id": service.team_id,
            "team_id": team_id,
        }), 400

    if getattr(service, "deleted", False):
        return jsonify({
            "error": "service_deleted",
            "message": "Service was deleted",
            "service_id": service_id,
        }), 400

    if not getattr(service, "enabled", True):
        return jsonify({
            "error": "service_disabled",
            "message": "Service is disabled",
            "service_id": service_id,
        }), 400

    error = require_route_resource_write(service.team_id)
    if error:
        return error

    return None


def validate_route_escalation_policy(team_id, escalation_policy_id):
    """Ensure selected escalation policy exists, is enabled and belongs to the route team."""
    if not escalation_policy_id:
        return None

    try:
        policy = escalation_policies_repo.get_policy(escalation_policy_id)
    except DoesNotExist:
        return jsonify({
            "error": "escalation_policy_not_found",
            "message": "Escalation policy was not found",
            "escalation_policy_id": escalation_policy_id,
        }), 400

    if policy.team_id != team_id:
        return jsonify({
            "error": "escalation_policy_team_mismatch",
            "message": "Escalation policy does not belong to route team",
            "escalation_policy_id": escalation_policy_id,
            "policy_team_id": policy.team_id,
            "team_id": team_id,
        }), 400

    if getattr(policy, "deleted", False):
        return jsonify({
            "error": "escalation_policy_deleted",
            "message": "Escalation policy was deleted",
            "escalation_policy_id": escalation_policy_id,
        }), 400

    if not getattr(policy, "enabled", True):
        return jsonify({
            "error": "escalation_policy_disabled",
            "message": "Escalation policy is disabled",
            "escalation_policy_id": escalation_policy_id,
        }), 400

    error = require_route_resource_write(policy.team_id)
    if error:
        return error

    return None


def validate_route_channels(team_id, channel_ids):
    """Ensure all route channels exist and belong to the same team as the route."""
    for channel_id in channel_ids:
        try:
            channel = channels_repo.get_channel(channel_id)
        except DoesNotExist:
            return jsonify({
                "error": "channel_not_found",
                "message": "Channel was not found",
                "channel_id": channel_id,
            }), 400

        if channel.team_id != team_id:
            return jsonify({
                "error": "channel_team_mismatch",
                "message": "Channel does not belong to route team",
                "channel_id": channel_id,
                "channel_team_id": channel.team_id,
                "team_id": team_id,
            }), 400

        error = require_route_resource_write(channel.team_id)
        if error:
            return error

    return None


def validate_route_rotation(team_id, rotation_id):
    """Ensure selected rotation exists and belongs to the route team."""
    if not rotation_id:
        return None

    try:
        rotation = rotations_repo.get_rotation(rotation_id)
    except DoesNotExist:
        return jsonify({
            "error": "rotation_not_found",
            "message": "Rotation was not found",
            "rotation_id": rotation_id,
        }), 400

    if rotation.team_id != team_id:
        return jsonify({
            "error": "rotation_team_mismatch",
            "message": "Rotation does not belong to route team",
            "rotation_id": rotation_id,
            "rotation_team_id": rotation.team_id,
            "team_id": team_id,
        }), 400

    error = require_route_resource_write(rotation.team_id)
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

    return jsonify([serialize_route(route, current_user=current_user()) for route in routes])


@routes_bp.route("/<int:route_id>", methods=["GET"])
def get_route(route_id):
    """
    Return a single route.
    """

    route = routes_repo.get_route(route_id)
    error = require_team_read(route.team_id)

    if error:
        return error

    return jsonify(serialize_route(route, current_user=current_user()))


@routes_bp.route("", methods=["POST"])
def create_route():
    """
    Create an alert route with rotation, channels and route intake token.
    """

    payload, error = validate_body(RouteCreateSchema)
    if error:
        return error

    error = require_route_resource_write(payload.team_id)
    if error:
        return error

    channel_error = validate_route_channels(payload.team_id, payload.channel_ids)
    if channel_error:
        return channel_error

    rotation_error = validate_route_rotation(payload.team_id, payload.rotation_id)
    if rotation_error:
        return rotation_error

    policy_error = validate_route_escalation_policy(payload.team_id, payload.escalation_policy_id)
    if policy_error:
        return policy_error

    service_error = validate_route_service(payload.team_id, payload.service_id)
    if service_error:
        return service_error

    matcher_preset, matcher_preset_error = validate_route_matcher_preset(payload.team_id, payload.matcher_preset_id)
    if matcher_preset_error:
        return matcher_preset_error

    raw_token = create_raw_token()
    integration_config = build_route_integration_config(payload)
    existing_route = routes_repo.get_route_by_team_and_name(payload.team_id, payload.name)

    if existing_route and not existing_route.deleted:
        return route_name_conflict_response(payload.name)

    try:
        if existing_route:
            route = routes_repo.restore_route(
                existing_route.id,
                team_id=payload.team_id,
                name=payload.name,
                source=payload.source,
                rotation_id=payload.rotation_id,
                escalation_policy_id=payload.escalation_policy_id,
                matcher_preset_id=matcher_preset.id if matcher_preset else None,
                matchers=payload.matchers,
                group_by=payload.group_by,
                enabled=payload.enabled,
                intake_token_prefix=raw_token[:12],
                intake_token_hash=hash_token(raw_token),
                service_id=payload.service_id,
                integration_config=integration_config,
                notification_channel_mode=payload.notification_channel_mode,
            )

            routes_repo.replace_route_channels(route.id, payload.channel_ids)

            audit_action = "route.restore"
        else:
            route = routes_repo.create_route(
                team_id=payload.team_id,
                name=payload.name,
                source=payload.source,
                rotation_id=payload.rotation_id,
                escalation_policy_id=payload.escalation_policy_id,
                matcher_preset_id=matcher_preset.id if matcher_preset else None,
                matchers=payload.matchers,
                group_by=payload.group_by,
                enabled=payload.enabled,
                intake_token_prefix=raw_token[:12],
                intake_token_hash=hash_token(raw_token),
                service_id=payload.service_id,
                integration_config=integration_config,
                notification_channel_mode=payload.notification_channel_mode,
            )

            routes_repo.replace_route_channels(
                route.id,
                payload.channel_ids,
            )

            audit_action = "route.create"
    except IntegrityError as exc:
        conflicting_route = routes_repo.get_route_by_team_and_name(payload.team_id, payload.name)

        if conflicting_route:
            return route_name_conflict_response(payload.name)

        return handle_integrity_error(exc)

    audit_data = payload.model_dump()
    audit_data["integration_config"] = mask_route_integration_config(integration_config)
    audit_data["intake_token"] = "***"

    write_audit(
        audit_action,
        object_type="route",
        object_id=route.id,
        team_id=route.team.id,
        data=audit_data,
    )

    trigger = "route_restored" if audit_action == "route.restore" else "route_created"

    reconcile_route_services(
        route.id,
        trigger=trigger,
        actor_user=current_user(),
    )

    response = serialize_route(route, current_user=current_user())
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
    error = require_route_resource_write(current_route.team_id)
    old_service_id = current_route.service_id

    if error:
        return error

    if payload.team_id != current_route.team_id:
        error = require_route_resource_write(payload.team_id)
        if error:
            return error

    channel_error = validate_route_channels(payload.team_id, payload.channel_ids)
    if channel_error:
        return channel_error

    rotation_error = validate_route_rotation(payload.team_id, payload.rotation_id)
    if rotation_error:
        return rotation_error

    policy_error = validate_route_escalation_policy(
        payload.team_id,
        payload.escalation_policy_id,
    )
    if policy_error:
        return policy_error

    service_error = validate_route_service(payload.team_id, payload.service_id)
    if service_error:
        return service_error

    matcher_preset, matcher_preset_error = validate_route_matcher_preset(payload.team_id, payload.matcher_preset_id)
    if matcher_preset_error:
        return matcher_preset_error

    integration_config = build_route_integration_config(
        payload,
        current_route=current_route,
    )

    conflicting_route = (
        routes_repo.get_route_by_team_and_name(
            payload.team_id,
            payload.name,
            exclude_route_id=route_id,
        )
    )

    if conflicting_route:
        return route_name_conflict_response(payload.name)

    route = routes_repo.update_route(
        route_id,
        {
            "team": payload.team_id,
            "name": payload.name,
            "source": payload.source,
            "rotation": payload.rotation_id,
            "escalation_policy": payload.escalation_policy_id,
            "matcher_preset": matcher_preset.id if matcher_preset else None,
            "matchers": payload.matchers,
            "group_by": payload.group_by,
            "enabled": payload.enabled,
            "service": payload.service_id,
            "integration_config": integration_config,
            "notification_channel_mode": payload.notification_channel_mode,
        },
    )

    routes_repo.replace_route_channels(route.id, payload.channel_ids)
    route = routes_repo.get_route(route_id)

    audit_data = payload.model_dump()
    audit_data["integration_config"] = mask_route_integration_config(integration_config)

    write_audit(
        "route.update",
        object_type="route",
        object_id=route.id,
        team_id=route.team.id,
        data=audit_data,
    )

    reconcile_route_services(
        route.id,
        trigger="route_updated",
        actor_user=current_user(),
        extra_service_ids=[old_service_id],
    )

    return jsonify(serialize_route(route, current_user=current_user()))


@routes_bp.route("/<int:route_id>/disable", methods=["POST"])
def disable_route(route_id):
    """
    Disable an alert route without deleting it.
    """
    route_before = routes_repo.get_route(route_id)

    error = require_route_resource_write(route_before.team_id)
    if error:
        return error

    route = routes_repo.disable_route(route_id)

    write_audit(
        "route.disable",
        object_type="route",
        object_id=route.id,
        team_id=route.team.id,
        data={
            "name": route.name,
            "enabled": False,
        },
    )

    reconcile_route_services(
        route.id,
        trigger="route_enabled",
        actor_user=current_user(),
    )

    return jsonify(serialize_route(route, current_user=current_user()))


@routes_bp.route("/<int:route_id>/enable", methods=["POST"])
def enable_route(route_id):
    """
    Enable a disabled alert route.
    """
    route_before = routes_repo.get_route(route_id)

    error = require_route_resource_write(route_before.team_id)
    if error:
        return error

    route = routes_repo.enable_route(route_id)

    write_audit(
        "route.enable",
        object_type="route",
        object_id=route.id,
        team_id=route.team.id,
        data={
            "name": route.name,
            "enabled": True,
        },
    )

    reconcile_route_services(
        route.id,
        trigger="route_enabled",
        actor_user=current_user(),
    )

    return jsonify(serialize_route(route, current_user=current_user()))


@routes_bp.route("/<int:route_id>", methods=["DELETE"])
def delete_route(route_id):
    """
    Delete an alert route.

    The route is soft-deleted so historical alerts keep their route reference.
    """
    route_before = routes_repo.get_route(route_id)

    error = require_route_resource_write(route_before.team_id)
    if error:
        return error

    route = routes_repo.soft_delete_route(route_id)

    write_audit(
        "route.delete",
        object_type="route",
        object_id=route.id,
        team_id=route.team.id,
        data={
            "name": route.name,
            "source": route.source,
            "deleted": True,
        },
    )

    reconcile_route_services(
        route.id,
        trigger="route_enabled",
        actor_user=current_user(),
    )

    return jsonify({
        "deleted": True,
        "id": route.id,
        "name": route.name,
    })


@routes_bp.route("/<int:route_id>/intake-token", methods=["POST"])
def regenerate_route_intake_token(route_id):
    """
    Regenerate the alert intake token for a route.
    """

    route = routes_repo.get_route(route_id)
    error = require_route_resource_write(route.team_id)

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

    response = serialize_route(route, current_user=current_user())
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
    error = require_route_resource_write(route_before.team_id)

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

    return jsonify(serialize_route(route, current_user=current_user()))


@routes_bp.route("/<int:route_id>/channels/<int:channel_id>", methods=["POST"])
def add_route_channel(route_id, channel_id):
    """
    Link a channel to a route.
    """

    route_before = routes_repo.get_route(route_id)
    error = require_route_resource_write(route_before.team_id)

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
    error = require_route_resource_write(route_before.team_id)

    if error:
        return error

    routes_repo.unlink_route_channel(route_id, channel_id)
    return jsonify({"status": "deleted"})
