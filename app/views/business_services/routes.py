from flask import Blueprint, jsonify, request
from datetime import datetime, timezone

from app.api.schemas.business_services import (
    BusinessServiceComponentCreateSchema,
    BusinessServiceComponentUpdateSchema,
    BusinessServiceCreateSchema,
    BusinessServiceUpdateSchema,
    BusinessServiceManualStatusSchema,
)
from app.modules.db import business_services_repo, services_repo, teams_repo
from app.services.business_services.status import apply_business_service_status
from app.services.service_catalog.impact import build_service_effective_impact_map
from app.services.rbac import (
    can_read_group,
    get_allowed_group_ids,
    require_group_write,
    require_team_or_group_resource_access,
    require_team_read,
)
from app.services.serializers.business_services import (
    serialize_business_service,
    serialize_business_service_component,
)
from app.services.validation import validate_body
from app.modules.common import utc_now


business_services_bp = Blueprint("business_services", __name__, url_prefix="/api/business-services")


def normalize_optional_utc_datetime(value):
    if value is None:
        return None

    if value.tzinfo is None:
        return value

    return value.astimezone(timezone.utc).replace(tzinfo=None)


def require_business_group_read(group_id):
    """Return current user or an error response for business service group read."""
    user = request.current_user

    if not user:
        return None, (jsonify({"error": "Authentication is required"}), 401)

    if user.is_admin or can_read_group(user, group_id):
        return user, None

    return None, (jsonify({"error": "Access to this group is denied"}), 403)


def _component_impact_map(components):
    return build_service_effective_impact_map(
        [component.service_id for component in components],
        max_depth=5,
    )


def _serialize_components(components, current_user=None):
    impact_map = _component_impact_map(components)

    return [
        serialize_business_service_component(
            component,
            current_user=current_user,
            impact_map=impact_map,
        )
        for component in components
    ]


def _business_service_component_scope():
    group_id = request.args.get("group_id", type=int)
    team_id = request.args.get("team_id", type=int)

    if team_id:
        error = require_team_read(team_id)
        if error:
            return None, None, error

        team = teams_repo.get_team(team_id)
        return [team.group_id] if team.group_id else [], request.current_user, None

    if group_id:
        current_user, error = require_business_group_read(group_id)
        if error:
            return None, None, error
        return [group_id], current_user, None

    current_user = request.current_user

    if not current_user:
        return None, None, (jsonify({"error": "Authentication is required"}), 401)

    return get_allowed_group_ids(user=current_user), current_user, None


def _refresh_business_services_for_components(components):
    business_service_ids = sorted({
        component.business_service_id
        for component in components
        if component.business_service_id
    })

    for business_service_id in business_service_ids:
        item = business_services_repo.get_business_service_or_none(business_service_id)
        if item:
            apply_business_service_status(item)


def _business_service_details_payload(item, current_user=None):
    apply_business_service_status(item)

    item = business_services_repo.get_business_service(item.id)
    components = business_services_repo.list_business_service_components(
        item.id,
        active_only=False,
    )
    history = business_services_repo.list_business_service_status_history(
        item.id,
        limit=50,
    )

    return serialize_business_service(
        item,
        current_user=current_user,
        components=components,
        history=history,
    )


def _refresh_business_services_for_list(items):
    refreshed = []

    for item in items:
        apply_business_service_status(item)
        refreshed.append(business_services_repo.get_business_service(item.id))

    return refreshed


@business_services_bp.route("/components", methods=["GET"])
def list_business_service_components_for_graph():
    group_ids, current_user, error = _business_service_component_scope()

    if error:
        return error

    components = business_services_repo.list_business_service_components_for_groups(
        group_ids=group_ids,
        active_only=True,
    )

    _refresh_business_services_for_components(components)

    components = business_services_repo.list_business_service_components_for_groups(
        group_ids=group_ids,
        active_only=True,
    )

    return jsonify(_serialize_components(components, current_user=current_user))


@business_services_bp.route("", methods=["GET"])
def list_business_services():
    group_id = request.args.get("group_id", type=int)
    if not group_id and not request.current_user.is_admin:
        return jsonify({"error": "group_id is required"}), 400
    public_only = request.args.get("public", default=False, type=lambda value: str(value).lower() == "true")

    if group_id:
        current_user, error = require_business_group_read(group_id)
        if error:
            return error
    else:
        current_user = request.current_user

    items = business_services_repo.list_business_services(group_id=group_id, public_only=public_only)
    items = _refresh_business_services_for_list(items)

    component_counts = business_services_repo.count_components_by_business_service_ids(
        [item.id for item in items],
    )

    return jsonify([
        serialize_business_service(
            item,
            current_user=current_user,
            components_count=component_counts.get(item.id, 0),
        )
        for item in items
    ])


@business_services_bp.route("", methods=["POST"])
def create_business_service():
    payload, error = validate_body(BusinessServiceCreateSchema)

    if error:
        return error

    error = require_group_write(payload.group_id)
    if error:
        return error

    current_user = request.current_user

    if payload.owner_team_id:
        error = require_team_or_group_resource_access(payload.owner_team_id, write_required=True)
        if error:
            return error

    item = business_services_repo.create_business_service({
        "group": payload.group_id,
        "owner_team": payload.owner_team_id,
        "slug": payload.slug,
        "name": payload.name,
        "description": payload.description,
        "criticality": payload.criticality,
        "tier": payload.tier,
        "public": payload.public,
        "public_name": payload.public_name,
        "public_description": payload.public_description,
        "public_order": payload.public_order,
        "labels": payload.labels,
        "metadata": payload.metadata,
        "enabled": payload.enabled,
    })

    return jsonify(serialize_business_service(item, current_user=current_user)), 201


@business_services_bp.route("/<int:business_service_id>", methods=["GET"])
def get_business_service(business_service_id):
    item = business_services_repo.get_business_service_or_none(business_service_id)

    if not item:
        return jsonify({"error": "Business service not found"}), 404

    user, error = require_business_group_read(item.group_id)

    if error:
        return error

    return jsonify(_business_service_details_payload(item, current_user=user))


@business_services_bp.route("/<int:business_service_id>", methods=["PUT"])
def update_business_service(business_service_id):
    item = business_services_repo.get_business_service(business_service_id)
    error = require_group_write(item.group_id)
    if error:
        return error

    current_user = request.current_user
    payload, error = validate_body(BusinessServiceUpdateSchema)

    if error:
        return error

    if payload.group_id != item.group_id:
        return jsonify({"error": "group_change_not_allowed"}), 400

    if payload.owner_team_id:
        error = require_team_or_group_resource_access(payload.owner_team_id, write_required=True)
        if error:
            return error

    item = business_services_repo.update_business_service(item.id, {
        "owner_team": payload.owner_team_id,
        "slug": payload.slug,
        "name": payload.name,
        "description": payload.description,
        "criticality": payload.criticality,
        "tier": payload.tier,
        "public": payload.public,
        "public_name": payload.public_name,
        "public_description": payload.public_description,
        "public_order": payload.public_order,
        "labels": payload.labels,
        "metadata": payload.metadata,
        "enabled": payload.enabled,
    })

    return jsonify(serialize_business_service(item, current_user=current_user))


@business_services_bp.route("/<int:business_service_id>", methods=["DELETE"])
def delete_business_service(business_service_id):
    item = business_services_repo.get_business_service(business_service_id)
    error = require_group_write(item.group_id)
    if error:
        return error

    business_services_repo.soft_delete_business_service(item.id)
    return "", 204


@business_services_bp.route("/<int:business_service_id>/components", methods=["GET"])
def list_business_service_components(business_service_id):
    item = business_services_repo.get_business_service(business_service_id)
    current_user, error = require_business_group_read(item.group_id)
    if error:
        return error
    components = business_services_repo.list_business_service_components(item.id, active_only=False)

    return jsonify(_serialize_components(components, current_user=current_user))


@business_services_bp.route("/<int:business_service_id>/components", methods=["POST"])
def create_business_service_component(business_service_id):
    item = business_services_repo.get_business_service(business_service_id)
    error = require_group_write(item.group_id)
    if error:
        return error

    current_user = request.current_user
    payload, error = validate_body(BusinessServiceComponentCreateSchema)

    if error:
        return error

    service = services_repo.get_service(payload.service_id)

    if service.group_id != item.group_id:
        return jsonify({"error": "service_group_mismatch"}), 400

    component = business_services_repo.create_business_service_component(item.id, {
        "service": payload.service_id,
        "component_type": payload.component_type,
        "criticality": payload.criticality,
        "impact_weight": payload.impact_weight,
        "position": payload.position,
        "status_rule": payload.status_rule,
        "description": payload.description,
        "enabled": payload.enabled,
    })

    apply_business_service_status(item)

    return jsonify(_serialize_components([component], current_user=current_user)[0]), 201


@business_services_bp.route("/components/<int:component_id>", methods=["PUT"])
def update_business_service_component(component_id):
    existing = business_services_repo.get_business_service_component(component_id)
    item = existing.business_service
    error = require_group_write(item.group_id)
    if error:
        return error

    current_user = request.current_user
    payload, error = validate_body(BusinessServiceComponentUpdateSchema)

    if error:
        return error

    service = services_repo.get_service(payload.service_id)

    if service.group_id != item.group_id:
        return jsonify({"error": "service_group_mismatch"}), 400

    component = business_services_repo.update_business_service_component(existing.id, {
        "service": payload.service_id,
        "component_type": payload.component_type,
        "criticality": payload.criticality,
        "impact_weight": payload.impact_weight,
        "position": payload.position,
        "status_rule": payload.status_rule,
        "description": payload.description,
        "enabled": payload.enabled,
    })

    apply_business_service_status(item)

    return jsonify(_serialize_components([component], current_user=current_user)[0])


@business_services_bp.route("/components/<int:component_id>", methods=["DELETE"])
def delete_business_service_component(component_id):
    component = business_services_repo.get_business_service_component(component_id)
    item = component.business_service
    error = require_group_write(item.group_id)
    if error:
        return error

    business_services_repo.soft_delete_business_service_component(component.id)
    apply_business_service_status(item)
    return "", 204


@business_services_bp.route("/<int:business_service_id>/recalculate", methods=["POST"])
def recalculate_business_service(business_service_id):
    item = business_services_repo.get_business_service_or_none(business_service_id)

    if not item:
        return jsonify({"error": "Business service not found"}), 404

    error = require_group_write(item.group_id)

    if error:
        return error

    return jsonify(_business_service_details_payload(item, current_user=request.current_user))


@business_services_bp.route("/<int:business_service_id>/manual-status", methods=["POST"])
def set_business_service_manual_status(business_service_id):
    item = business_services_repo.get_business_service_or_none(business_service_id)

    if not item:
        return jsonify({"error": "Business service not found"}), 404

    error = require_group_write(item.group_id)

    if error:
        return error

    payload, error = validate_body(BusinessServiceManualStatusSchema)

    if error:
        return error

    until = normalize_optional_utc_datetime(payload.until)

    if until is not None and until <= utc_now():
        return jsonify({"error": "Manual status expiration must be in the future"}), 400

    item = business_services_repo.set_business_service_manual_status(
        item.id,
        manual_status=payload.status,
        message=payload.message,
        until=until,
        user_id=request.current_user.id if request.current_user else None,
    )

    return jsonify(_business_service_details_payload(item, current_user=request.current_user))


@business_services_bp.route("/<int:business_service_id>/manual-status", methods=["DELETE"])
def clear_business_service_manual_status(business_service_id):
    item = business_services_repo.get_business_service_or_none(business_service_id)

    if not item:
        return jsonify({"error": "Business service not found"}), 404

    error = require_group_write(item.group_id)

    if error:
        return error

    item = business_services_repo.clear_business_service_manual_status(item.id)

    return jsonify(_business_service_details_payload(item, current_user=request.current_user))
