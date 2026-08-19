from flask import request, jsonify
from peewee import DoesNotExist

from app.views.services.blueprint import services_bp
from app.api.schemas.services import ServiceMatchRuleCreateSchema, ServiceMatchRuleUpdateSchema
from app.modules.db import routes_repo, services_repo
from app.services.audit import write_audit
from app.services.rbac import require_team_read, current_user, require_team_write
from app.services.routing.matcher import service as matcher_preset_service
from app.services.serializers.services import serialize_service_match_rule
from app.services.service_catalog.events import (
    READINESS_SCOPE_NONE,
    READINESS_SCOPE_SERVICE,
    READINESS_SCOPE_SERVICES,
    emit_service_catalog_event,
)
from app.services.service_catalog.snapshots import service_match_rule_snapshot
from app.services.validation import make_error_response, validate_body


def _validate_route(team_id, route_id):
    if not route_id:
        return None

    try:
        route = routes_repo.get_route(route_id)
    except DoesNotExist:
        return make_error_response(
            "route_not_found",
            "Route was not found",
            400,
            route_id=route_id,
        )

    if route.team_id != team_id:
        return make_error_response(
            "route_team_mismatch",
            "Route does not belong to service match rule team",
            400,
            route_id=route_id,
            route_team_id=route.team_id,
            team_id=team_id,
        )

    return None


def _validate_service(team_id, service_id):
    try:
        service = services_repo.get_service(service_id)
    except DoesNotExist:
        return make_error_response(
            "service_not_found",
            "Service was not found",
            400,
            service_id=service_id,
        )

    if service.team_id != team_id:
        return make_error_response(
            "service_team_mismatch",
            "Service does not belong to match rule team",
            400,
            service_id=service_id,
            service_team_id=service.team_id,
            team_id=team_id,
        )

    if not service.enabled:
        return make_error_response(
            "service_disabled",
            "Service is disabled",
            400,
            service_id=service_id,
        )

    return None


def _validate_match_rule_payload(payload):
    service_error = _validate_service(payload.team_id, payload.service_id)
    if service_error:
        return None, service_error

    route_error = _validate_route(payload.team_id, payload.route_id)
    if route_error:
        return None, route_error

    try:
        preset = matcher_preset_service.validate_preset_assignment(
            payload.matcher_preset_id,
            team_id=payload.team_id,
        )
    except matcher_preset_service.MatcherPresetNotFoundError:
        return None, make_error_response(
            "matcher_preset_not_found",
            "Matcher preset was not found.",
            400,
        )
    except matcher_preset_service.MatcherPresetError:
        return None, make_error_response(
            "matcher_preset_invalid",
            "Matcher preset is invalid or unavailable.",
            400,
        )

    return preset, None


def _match_rule_data_from_payload(payload, preset):
    return {
        "team": payload.team_id,
        "route": payload.route_id,
        "service": payload.service_id,
        "position": payload.position,
        "name": payload.name,
        "description": payload.description,
        "matcher_preset": preset.id if preset else None,
        "matchers": payload.matchers,
        "enabled": payload.enabled,
    }


@services_bp.route("/match-rules", methods=["GET"])
def list_match_rules():
    """Return service match rules filtered by team, route or service."""
    team_id = request.args.get("team_id", type=int)
    route_id = request.args.get("route_id", type=int)
    service_id = request.args.get("service_id", type=int)

    if route_id:
        try:
            route = routes_repo.get_route(route_id)
        except DoesNotExist:
            return make_error_response(
                "route_not_found",
                "Route was not found",
                404,
                route_id=route_id,
            )

        error = require_team_read(route.team_id)
        if error:
            return error

        team_id = route.team_id

    elif service_id:
        service = services_repo.get_service(service_id)

        error = require_team_read(service.team_id)
        if error:
            return error

        team_id = service.team_id

    elif team_id:
        error = require_team_read(team_id)
        if error:
            return error

    else:
        return make_error_response(
            "team_required",
            "team_id, route_id or service_id is required",
            400,
        )

    rules = services_repo.list_match_rules(
        service_id=service_id,
        team_id=team_id,
        route_id=route_id,
    )

    return jsonify([
        serialize_service_match_rule(rule, current_user())
        for rule in rules
    ])


@services_bp.route("/<int:service_id>/match-rules", methods=["GET"])
def list_service_match_rules(service_id):
    """Return match rules for a service."""
    service = services_repo.get_service(service_id)

    error = require_team_read(service.team_id)
    if error:
        return error

    return jsonify([
        serialize_service_match_rule(rule, current_user())
        for rule in services_repo.list_match_rules(service_id=service_id)
    ])


@services_bp.route("/<int:service_id>/match-rules", methods=["POST"])
def create_service_match_rule(service_id):
    """Create a service match rule."""
    payload, error = validate_body(ServiceMatchRuleCreateSchema)
    if error:
        return error

    if payload.service_id != service_id:
        return make_error_response(
            "service_id_mismatch",
            "service_id in URL and body must match",
            400,
            url_service_id=service_id,
            payload_service_id=payload.service_id,
        )

    error = require_team_write(payload.team_id)
    if error:
        return error

    preset, validation_error = _validate_match_rule_payload(payload)
    if validation_error:
        return validation_error

    rule = services_repo.create_match_rule(_match_rule_data_from_payload(payload, preset))

    write_audit(
        "service_match_rule.create",
        object_type="service_match_rule",
        object_id=rule.id,
        team_id=rule.team_id,
        data=payload.model_dump(),
    )

    rule_snapshot = service_match_rule_snapshot(rule)
    emit_service_catalog_event(
        rule.service,
        category="routing",
        event_type="service_match_rule.created",
        title="Service match rule created",
        summary=rule.name or rule_snapshot.get("route_name"),
        source_ref=f"service_match_rule:{rule.id}",
        actor_user=current_user(),
        payload={"match_rule": rule_snapshot},
        readiness_scope=READINESS_SCOPE_SERVICE,
        readiness_trigger="service_match_rule_created",
    )

    return jsonify(serialize_service_match_rule(rule, current_user())), 201


@services_bp.route("/match-rules/<int:rule_id>", methods=["PUT"])
def update_service_match_rule(rule_id):
    """Update a service match rule."""
    rule_before = services_repo.get_match_rule(rule_id)
    old_service = rule_before.service

    error = require_team_write(rule_before.team_id)
    if error:
        return error

    rule_snapshot_before = service_match_rule_snapshot(rule_before)

    payload, error = validate_body(ServiceMatchRuleUpdateSchema)
    if error:
        return error

    error = require_team_write(payload.team_id)
    if error:
        return error

    preset, validation_error = _validate_match_rule_payload(payload)
    if validation_error:
        return validation_error

    rule = services_repo.update_match_rule(rule_id, _match_rule_data_from_payload(payload, preset))

    write_audit(
        "service_match_rule.update",
        object_type="service_match_rule",
        object_id=rule.id,
        team_id=rule.team_id,
        data=payload.model_dump(),
    )

    actor_user = current_user()
    rule_snapshot = service_match_rule_snapshot(rule)

    if old_service.id != rule.service_id:
        emit_service_catalog_event(
            old_service,
            category="routing",
            event_type="service_match_rule.removed",
            title="Service match rule removed",
            summary=rule_snapshot_before.get("name") or rule_snapshot_before.get("route_name"),
            source_ref=f"service_match_rule:{rule.id}",
            actor_user=actor_user,
            before=rule_snapshot_before,
            readiness_scope=READINESS_SCOPE_NONE,
        )

    emit_service_catalog_event(
        rule.service,
        category="routing",
        event_type="service_match_rule.updated",
        title="Service match rule updated",
        summary=rule.name or rule_snapshot.get("route_name"),
        source_ref=f"service_match_rule:{rule.id}",
        actor_user=actor_user,
        before=rule_snapshot_before,
        after=rule_snapshot,
        readiness_scope=READINESS_SCOPE_SERVICES,
        readiness_trigger="service_match_rule_updated",
        affected_service_ids=[old_service.id],
    )

    return jsonify(serialize_service_match_rule(rule, current_user()))


@services_bp.route("/match-rules/<int:rule_id>", methods=["DELETE"])
def delete_service_match_rule(rule_id):
    """Soft-delete a service match rule."""
    rule_before = services_repo.get_match_rule(rule_id)
    service = rule_before.service

    error = require_team_write(rule_before.team_id)
    if error:
        return error

    rule_snapshot_before = service_match_rule_snapshot(rule_before)
    rule = services_repo.soft_delete_match_rule(rule_id)

    write_audit(
        "service_match_rule.delete",
        object_type="service_match_rule",
        object_id=rule.id,
        team_id=rule.team_id,
        data={"deleted": True},
    )

    rule_snapshot = service_match_rule_snapshot(rule)
    emit_service_catalog_event(
        service,
        category="routing",
        event_type="service_match_rule.deleted",
        title="Service match rule deleted",
        summary=rule_snapshot_before.get("name") or rule_snapshot_before.get("route_name"),
        source_ref=f"service_match_rule:{rule.id}",
        actor_user=current_user(),
        before=rule_snapshot_before,
        after=rule_snapshot,
        readiness_scope=READINESS_SCOPE_SERVICE,
        readiness_trigger="service_match_rule_deleted",
    )

    return jsonify({"deleted": True, "id": rule.id})
