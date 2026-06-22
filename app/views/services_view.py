from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from peewee import DoesNotExist, IntegrityError

from app.modules.db.models import AlertGroup
from app.api.schemas.services import (
    ServiceCreateSchema,
    ServiceDependencyCreateSchema,
    ServiceDependencyUpdateSchema,
    ServiceImpactQuerySchema,
    ServiceImpactServiceQuerySchema,
    ServiceLinkCreateSchema,
    ServiceLinkUpdateSchema,
    ServiceMatchRuleCreateSchema,
    ServiceMatchRuleUpdateSchema,
    ServiceRunbookCreateSchema,
    ServiceRunbookUpdateSchema,
    ServiceUpdateSchema,
    ServiceAnalyticsQuerySchema,
    ServiceOwnerCreateSchema,
    ServiceOwnerUpdateSchema,
)
from app.modules.db import (
    escalation_policies_repo,
    maintenance_repo,
    rotations_repo,
    routes_repo,
    services_repo,
)
from app.modules.db.common import integrity_conflict, unique_field_conflict
from app.services.audit import write_audit
from app.services.rbac import (
    current_user,
    get_allowed_team_ids,
    require_team_read,
    require_team_write,
)
from app.services.serializers import (
    serialize_maintenance_window,
    serialize_service,
    serialize_service_dependency,
    serialize_service_link,
    serialize_service_match_rule,
    serialize_service_runbook,
    serialize_utc_datetime,
    serialize_service_owner,
)
from app.services.service_analytics import build_service_analytics_v2
from app.services.validation import (
    make_error_response,
    validate_body,
    validate_query,
)
from app.services.service_impact import (
    build_service_impact_v2,
    build_single_service_impact_v2,
)

services_bp = Blueprint("services_api", __name__)


SERVICE_DETAILS_DEFAULT_DAYS = 30
SERVICE_DETAILS_MAX_DAYS = 365


class ServiceDetailsImpactQuery:
    include_disabled = True
    include_explanation = True
    include_root_causes = True
    include_blast_radius = True
    include_paths = True
    max_depth = 5


def _service_details_days_from_request():
    days = request.args.get("days", default=SERVICE_DETAILS_DEFAULT_DAYS, type=int)
    return max(1, min(days or SERVICE_DETAILS_DEFAULT_DAYS, SERVICE_DETAILS_MAX_DAYS))


def _service_open_statuses():
    return ("firing", "acknowledged")


def _service_alert_group_query(service_id):
    return AlertGroup.select().where(AlertGroup.service == service_id)


def _count_alert_groups(service_id, *conditions):
    query = _service_alert_group_query(service_id)

    for condition in conditions:
        query = query.where(condition)

    return query.count()


def _service_alert_summary(service_id, *, days):
    since = datetime.utcnow() - timedelta(days=days)

    base_query = _service_alert_group_query(service_id)
    recent_query = base_query.where(AlertGroup.last_seen_at >= since)

    last_group = (
        base_query
        .order_by(AlertGroup.last_seen_at.desc(), AlertGroup.id.desc())
        .first()
    )

    open_statuses = _service_open_statuses()

    by_status = {
        "firing": _count_alert_groups(service_id, AlertGroup.status == "firing"),
        "acknowledged": _count_alert_groups(service_id, AlertGroup.status == "acknowledged"),
        "resolved": _count_alert_groups(service_id, AlertGroup.status == "resolved"),
    }

    by_severity = {}

    for severity in ("critical", "high", "warning", "info", "unknown"):
        if severity == "unknown":
            by_severity[severity] = _count_alert_groups(
                service_id,
                AlertGroup.severity.is_null(True),
            )
        else:
            by_severity[severity] = _count_alert_groups(
                service_id,
                AlertGroup.severity == severity,
            )

    return {
        "window_days": days,
        "total": base_query.count(),
        "recent": recent_query.count(),
        "open": _count_alert_groups(
            service_id,
            AlertGroup.status.in_(open_statuses),
        ),
        "firing": by_status["firing"],
        "acknowledged": by_status["acknowledged"],
        "resolved": by_status["resolved"],
        "critical_open": _count_alert_groups(
            service_id,
            AlertGroup.status.in_(open_statuses),
            AlertGroup.severity == "critical",
        ),
        "last_seen_at": serialize_utc_datetime(last_group.last_seen_at) if last_group else None,
        "by_status": by_status,
        "by_severity": by_severity,
    }


def _serialize_service_status_history_item(item):
    return {
        "id": item.id,
        "old_status": item.old_status,
        "new_status": item.new_status,
        "source": item.source,
        "message": item.message,
        "alert_id": item.alert_id,
        "maintenance_window_id": item.maintenance_window_id,
        "changed_by_id": item.changed_by_id,
        "created_at": serialize_utc_datetime(item.created_at),
    }


def _readable_dependency_rows(dependencies, *, target_side):
    """Filter cross-team dependency rows by read permission.

    target_side=True checks depends_on_service team.
    target_side=False checks source service team.
    """
    rows = []

    for dependency in dependencies:
        target_service = (
            dependency.depends_on_service
            if target_side
            else dependency.service
        )

        if not target_service:
            continue

        error = require_team_read(target_service.team_id)

        if not error:
            rows.append(dependency)

    return rows


def _service_maintenance_windows(service):
    windows = maintenance_repo.list_maintenance_windows(
        group_id=service.group_id,
        team_id=service.team_id,
        service_id=service.id,
        include_deleted=False,
        include_finished=False,
    )

    return [
        serialize_maintenance_window(window)
        for window in windows
    ]


def _service_analytics_payload(
    service,
    *,
    days,
    alert_summary,
    status_history,
    impact=None,
):
    until = datetime.utcnow()
    since = until - timedelta(days=days)

    impact = impact or {}
    blast_radius = impact.get("blast_radius") or {}

    return {
        "version": 1,
        "window": {
            "days": days,
            "since": serialize_utc_datetime(since),
            "until": serialize_utc_datetime(until),
        },
        "widgets": {
            "alert_volume": {
                "total": alert_summary["total"],
                "recent": alert_summary["recent"],
                "open": alert_summary["open"],
                "critical_open": alert_summary["critical_open"],
            },
            "status": {
                "current": service.status,
                "source": service.status_source,
                "updated_at": serialize_utc_datetime(service.status_updated_at),
                "changes": len(status_history),
            },
            "impact": {
                "effective_status": impact.get("effective_status") or service.status,
                "primary_reason": impact.get("primary_reason"),
                "upstream_issues_count": impact.get("upstream_issues_count") or 0,
                "root_causes": len(impact.get("root_causes") or []),
                "blast_radius": {
                    "direct_downstream": blast_radius.get("direct_downstream") or 0,
                    "transitive_downstream": blast_radius.get("transitive_downstream") or 0,
                    "critical_downstream": blast_radius.get("critical_downstream") or 0,
                    "tier_1_downstream": blast_radius.get("tier_1_downstream") or 0,
                },
            },
        },
        "breakdowns": {
            "alerts_by_status": alert_summary["by_status"],
            "alerts_by_severity": alert_summary["by_severity"],
        },
        "series": [],
        "extensions": {},
    }


def _service_details_payload(service, *, days):
    alert_summary = _service_alert_summary(service.id, days=days)
    status_history = services_repo.list_service_status_history(service.id, limit=20)

    upstream_dependencies = _readable_dependency_rows(
        services_repo.list_service_dependencies(service_id=service.id),
        target_side=True,
    )
    downstream_dependencies = _readable_dependency_rows(
        services_repo.list_downstream_service_dependencies(service_id=service.id),
        target_side=False,
    )

    links = services_repo.list_service_links(service_id=service.id)
    runbooks = services_repo.list_service_runbooks(service_id=service.id)

    impact = build_single_service_impact_v2(
        service.id,
        ServiceDetailsImpactQuery(),
        team_ids=[service.team_id],
    )

    return {
        "service": serialize_service(service, current_user()),
        "summary": {
            "alerts": alert_summary,
            "maintenance_windows": len(_service_maintenance_windows(service)),
            "links": len(links),
            "runbooks": len(runbooks),
            "upstream_dependencies": len(upstream_dependencies),
            "downstream_dependencies": len(downstream_dependencies),
            "status_history": len(status_history),
        },
        "maintenance_windows": _service_maintenance_windows(service),
        "links": [
            serialize_service_link(link, current_user())
            for link in links
        ],
        "runbooks": [
            serialize_service_runbook(runbook, current_user())
            for runbook in runbooks
        ],
        "dependencies": {
            "upstream": [
                serialize_service_dependency(dependency, current_user())
                for dependency in upstream_dependencies
            ],
            "downstream": [
                serialize_service_dependency(dependency, current_user())
                for dependency in downstream_dependencies
            ],
        },
        "status_history": [
            _serialize_service_status_history_item(item)
            for item in status_history
        ],
        "analytics": _service_analytics_payload(
            service,
            days=days,
            alert_summary=alert_summary,
            status_history=status_history,
            impact=impact,
        ),
        "impact": impact,
    }


def _json_error(error, message, status=400, **extra):
    payload = {"error": error, "message": message}
    payload.update(extra)
    return jsonify(payload), status


def _readable_services_from_request(*, include_disabled=True):
    """
    Return services visible to the current user for aggregate
    service context endpoints.
    """
    team_id = request.args.get(
        "team_id",
        type=int,
    )
    service_id = request.args.get(
        "service_id",
        type=int,
    )

    if service_id:
        try:
            service = services_repo.get_service(
                service_id
            )
        except DoesNotExist:
            return None, _json_error(
                "service_not_found",
                "Service was not found",
                404,
                service_id=service_id,
            )

        if (
            not include_disabled
            and not services_repo.is_service_active(
                service
            )
        ):
            return None, _json_error(
                "service_not_found",
                "Service was not found",
                404,
                service_id=service_id,
            )

        error = require_team_read(
            service.team_id
        )
        if error:
            return None, error

        return [service], None

    if team_id:
        error = require_team_read(team_id)
        if error:
            return None, error

        return (
            services_repo.list_services(
                team_id=team_id,
                include_disabled=include_disabled,
            ),
            None,
        )

    allowed_team_ids = get_allowed_team_ids(
        active_only=True,
    )

    return (
        services_repo.list_services(
            team_ids=allowed_team_ids,
            include_disabled=include_disabled,
        ),
        None,
    )


def _validate_dependency_service(service, depends_on_service_id):
    """Validate dependency target.

    Cross-team dependencies are allowed.
    User must be able to edit source service and read target service.
    """
    if service.id == depends_on_service_id:
        return make_error_response(
            "dependency_self_reference",
            "Service cannot depend on itself",
            400,
            service_id=service.id,
        )

    try:
        depends_on = services_repo.get_service(depends_on_service_id)
    except DoesNotExist:
        return make_error_response(
            "dependency_service_not_found",
            "Dependency service was not found",
            400,
            depends_on_service_id=depends_on_service_id,
        )

    if not depends_on.enabled:
        return make_error_response(
            "dependency_service_disabled",
            "Dependency service is disabled",
            400,
            depends_on_service_id=depends_on.id,
        )

    error = require_team_read(depends_on.team_id)
    if error:
        return error

    return None


def _validate_rotation(team_id, rotation_id):
    if not rotation_id:
        return None

    try:
        rotation = rotations_repo.get_rotation(rotation_id)
    except DoesNotExist:
        return make_error_response(
            "rotation_not_found",
            "Default rotation was not found",
            400,
            rotation_id=rotation_id,
        )

    if rotation.team_id != team_id:
        return make_error_response(
            "rotation_team_mismatch",
            "Default rotation does not belong to service team",
            400,
            rotation_id=rotation_id,
            rotation_team_id=rotation.team_id,
            team_id=team_id,
        )

    return None


def _validate_escalation_policy(team_id, policy_id):
    if not policy_id:
        return None

    try:
        policy = escalation_policies_repo.get_policy(policy_id)
    except DoesNotExist:
        return make_error_response(
            "escalation_policy_not_found",
            "Default escalation policy was not found",
            400,
            escalation_policy_id=policy_id,
        )

    if policy.team_id != team_id:
        return make_error_response(
            "escalation_policy_team_mismatch",
            "Default escalation policy does not belong to service team",
            400,
            escalation_policy_id=policy_id,
            policy_team_id=policy.team_id,
            team_id=team_id,
        )

    return None


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


def _validate_service_payload(payload):
    rotation_error = _validate_rotation(payload.team_id, payload.default_rotation_id)
    if rotation_error:
        return rotation_error

    policy_error = _validate_escalation_policy(
        payload.team_id,
        payload.default_escalation_policy_id,
    )
    if policy_error:
        return policy_error

    return None


def _service_owner_data_from_payload(payload):
    return {
        "user": payload.user_id,
        "role": payload.role,
        "active": payload.active,
        "notify_on_created": payload.notify_on_created,
        "notify_on_priority_change": payload.notify_on_priority_change,
        "notify_on_status_change": payload.notify_on_status_change,
        "notify_on_resolved": payload.notify_on_resolved,
    }


def _service_data_from_payload(payload):
    return {
        "team": payload.team_id,
        "slug": payload.slug,
        "name": payload.name,
        "description": payload.description,
        "service_type": payload.service_type,
        "environment": payload.environment,
        "criticality": payload.criticality,
        "tier": payload.tier,
        "status": payload.status,
        "status_source": payload.status_source,
        "status_message": payload.status_message,
        "default_rotation": payload.default_rotation_id,
        "default_escalation_policy": payload.default_escalation_policy_id,
        "labels": payload.labels,
        "tags": payload.tags,
        "metadata": payload.metadata,
        "enabled": payload.enabled,
        "public": payload.public,
        "public_name": payload.public_name,
        "public_description": payload.public_description,
        "public_order": payload.public_order,
    }


def _validate_match_rule_payload(payload):
    service_error = _validate_service(payload.team_id, payload.service_id)
    if service_error:
        return service_error

    route_error = _validate_route(payload.team_id, payload.route_id)
    if route_error:
        return route_error

    return None


def _match_rule_data_from_payload(payload):
    return {
        "team": payload.team_id,
        "route": payload.route_id,
        "service": payload.service_id,
        "position": payload.position,
        "name": payload.name,
        "description": payload.description,
        "matchers": payload.matchers,
        "enabled": payload.enabled,
    }


@services_bp.route("", methods=["GET"])
def list_services():
    """Return services visible to current user."""
    team_id = request.args.get("team_id", type=int)

    if team_id:
        error = require_team_read(team_id)
        if error:
            return error

        services = services_repo.list_services(team_id=team_id)
    else:
        services = services_repo.list_services(team_ids=get_allowed_team_ids())

    return jsonify([
        serialize_service(service, current_user())
        for service in services
    ])


@services_bp.route("/<int:service_id>", methods=["GET"])
def get_service(service_id):
    """Return one service."""
    service = services_repo.get_service(service_id)

    error = require_team_read(service.team_id)
    if error:
        return error

    return jsonify(serialize_service(service, current_user()))


@services_bp.route("/<int:service_id>/details", methods=["GET"])
def get_service_details(service_id):
    """Return expanded service details for the service details panel."""
    try:
        service = services_repo.get_service(service_id)
    except DoesNotExist:
        return make_error_response(
            "service_not_found",
            "Service was not found",
            404,
            service_id=service_id,
        )

    error = require_team_read(service.team_id)
    if error:
        return error

    days = _service_details_days_from_request()

    return jsonify(
        _service_details_payload(
            service,
            days=days,
        )
    )


@services_bp.route("", methods=["POST"])
def create_service():
    """Create a service."""
    payload, error = validate_body(ServiceCreateSchema)
    if error:
        return error

    error = require_team_write(payload.team_id)
    if error:
        return error

    validation_error = _validate_service_payload(payload)
    if validation_error:
        return validation_error

    try:
        service = services_repo.create_service(_service_data_from_payload(payload))
    except IntegrityError as exc:
        error_text = str(exc).lower()
        if "slug" in error_text:
            return unique_field_conflict(
                "slug",
                payload.slug,
                "Service with this slug already exists in this team",
            )
        return integrity_conflict(
            "Service could not be saved because it conflicts with existing data"
        )

    write_audit(
        "service.create",
        object_type="service",
        object_id=service.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data=payload.model_dump(),
    )

    return jsonify(serialize_service(service, current_user())), 201


@services_bp.route("/<int:service_id>", methods=["PUT"])
def update_service(service_id):
    """Update a service."""
    service_before = services_repo.get_service(service_id)

    error = require_team_write(service_before.team_id)
    if error:
        return error

    payload, error = validate_body(ServiceUpdateSchema)
    if error:
        return error

    error = require_team_write(payload.team_id)
    if error:
        return error

    validation_error = _validate_service_payload(payload)
    if validation_error:
        return validation_error

    try:
        service = services_repo.update_service(
            service_id,
            _service_data_from_payload(payload),
        )
    except IntegrityError as exc:
        error_text = str(exc).lower()
        if "slug" in error_text:
            return unique_field_conflict(
                "slug",
                payload.slug,
                "Service with this slug already exists in this team",
            )
        return integrity_conflict(
            "Service could not be saved because it conflicts with existing data"
        )

    write_audit(
        "service.update",
        object_type="service",
        object_id=service.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data=payload.model_dump(),
    )

    return jsonify(serialize_service(service, current_user()))


@services_bp.route("/<int:service_id>", methods=["DELETE"])
def delete_service(service_id):
    """Soft-delete a service."""
    service_before = services_repo.get_service(service_id)

    error = require_team_write(service_before.team_id)
    if error:
        return error

    service = services_repo.soft_delete_service(service_id)

    write_audit(
        "service.delete",
        object_type="service",
        object_id=service.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data={"deleted": True},
    )

    return jsonify({"deleted": True, "id": service.id})


@services_bp.route("/<int:service_id>/owners", methods=["GET"])
def list_service_owners(service_id):
    """Return service owners/default stakeholders."""
    service = services_repo.get_service(service_id)

    error = require_team_read(service.team_id)
    if error:
        return error

    include_inactive = request.args.get("include_inactive") == "1"

    return jsonify([
        serialize_service_owner(owner, current_user())
        for owner in services_repo.list_service_owners(
            service_id,
            active_only=not include_inactive,
        )
    ])


@services_bp.route("/<int:service_id>/owners", methods=["POST"])
def create_service_owner(service_id):
    """Create a service owner/default stakeholder."""
    service = services_repo.get_service(service_id)

    error = require_team_write(service.team_id)
    if error:
        return error

    payload, error = validate_body(ServiceOwnerCreateSchema)
    if error:
        return error

    try:
        owner, created = services_repo.create_service_owner(
            service_id,
            _service_owner_data_from_payload(payload),
        )
    except DoesNotExist:
        return make_error_response(
            "user_not_found",
            "User was not found",
            404,
            user_id=payload.user_id,
        )
    except IntegrityError:
        return integrity_conflict(
            "Service owner could not be saved because it conflicts with "
            "existing data"
        )

    write_audit(
        "service_owner.create" if created else "service_owner.update",
        object_type="service_owner",
        object_id=owner.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data=payload.model_dump(),
    )

    return (
        jsonify(serialize_service_owner(owner, current_user())),
        201 if created else 200,
    )


@services_bp.route("/<int:service_id>/owners/<int:owner_id>", methods=["PUT"],)
def update_service_owner(service_id, owner_id):
    """Update a service owner/default stakeholder."""
    service = services_repo.get_service(service_id)

    error = require_team_write(service.team_id)
    if error:
        return error

    owner_before = services_repo.get_service_owner_for_service(
        service_id,
        owner_id,
    )

    if not owner_before:
        return make_error_response(
            "service_owner_not_found",
            "Service owner was not found",
            404,
            owner_id=owner_id,
        )

    payload, error = validate_body(ServiceOwnerUpdateSchema)
    if error:
        return error

    try:
        owner = services_repo.update_service_owner(
            owner_id,
            _service_owner_data_from_payload(payload),
        )
    except DoesNotExist:
        return make_error_response(
            "user_not_found",
            "User was not found",
            404,
            user_id=payload.user_id,
        )
    except IntegrityError:
        return integrity_conflict(
            "Service owner could not be saved because it conflicts with "
            "existing data"
        )

    write_audit(
        "service_owner.update",
        object_type="service_owner",
        object_id=owner.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data=payload.model_dump(),
    )

    return jsonify(serialize_service_owner(owner, current_user()))


@services_bp.route("/<int:service_id>/owners/<int:owner_id>", methods=["DELETE"],)
def delete_service_owner(service_id, owner_id):
    """Deactivate a service owner/default stakeholder."""
    service = services_repo.get_service(service_id)

    error = require_team_write(service.team_id)
    if error:
        return error

    owner_before = services_repo.get_service_owner_for_service(
        service_id,
        owner_id,
    )

    if not owner_before:
        return make_error_response(
            "service_owner_not_found",
            "Service owner was not found",
            404,
            owner_id=owner_id,
        )

    owner = services_repo.deactivate_service_owner(owner_id)

    write_audit(
        "service_owner.delete",
        object_type="service_owner",
        object_id=owner.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data={"active": False},
    )

    return jsonify({"deleted": True, "id": owner.id})


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

    validation_error = _validate_match_rule_payload(payload)
    if validation_error:
        return validation_error

    rule = services_repo.create_match_rule(_match_rule_data_from_payload(payload))

    write_audit(
        "service_match_rule.create",
        object_type="service_match_rule",
        object_id=rule.id,
        team_id=rule.team_id,
        data=payload.model_dump(),
    )

    return jsonify(serialize_service_match_rule(rule, current_user())), 201


@services_bp.route("/match-rules/<int:rule_id>", methods=["PUT"])
def update_service_match_rule(rule_id):
    """Update a service match rule."""
    rule_before = services_repo.get_match_rule(rule_id)

    error = require_team_write(rule_before.team_id)
    if error:
        return error

    payload, error = validate_body(ServiceMatchRuleUpdateSchema)
    if error:
        return error

    error = require_team_write(payload.team_id)
    if error:
        return error

    validation_error = _validate_match_rule_payload(payload)
    if validation_error:
        return validation_error

    rule = services_repo.update_match_rule(
        rule_id,
        _match_rule_data_from_payload(payload),
    )

    write_audit(
        "service_match_rule.update",
        object_type="service_match_rule",
        object_id=rule.id,
        team_id=rule.team_id,
        data=payload.model_dump(),
    )

    return jsonify(serialize_service_match_rule(rule, current_user()))


@services_bp.route("/match-rules/<int:rule_id>", methods=["DELETE"])
def delete_service_match_rule(rule_id):
    """Soft-delete a service match rule."""
    rule_before = services_repo.get_match_rule(rule_id)

    error = require_team_write(rule_before.team_id)
    if error:
        return error

    rule = services_repo.soft_delete_match_rule(rule_id)

    write_audit(
        "service_match_rule.delete",
        object_type="service_match_rule",
        object_id=rule.id,
        team_id=rule.team_id,
        data={"deleted": True},
    )

    return jsonify({"deleted": True, "id": rule.id})


@services_bp.route("/<int:service_id>/links", methods=["GET"])
def list_service_links(service_id):
    """Return service links."""
    service = services_repo.get_service(service_id)

    error = require_team_read(service.team_id)
    if error:
        return error

    return jsonify([
        serialize_service_link(link, current_user())
        for link in services_repo.list_service_links(service_id)
    ])


@services_bp.route("/<int:service_id>/links", methods=["POST"])
def create_service_link(service_id):
    """Create a service link."""
    service = services_repo.get_service(service_id)

    error = require_team_write(service.team_id)
    if error:
        return error

    payload, error = validate_body(ServiceLinkCreateSchema)
    if error:
        return error

    link = services_repo.create_service_link(
        service_id,
        payload.model_dump(),
    )

    write_audit(
        "service_link.create",
        object_type="service_link",
        object_id=link.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data=payload.model_dump(),
    )

    return jsonify(serialize_service_link(link, current_user())), 201


@services_bp.route("/links/<int:link_id>", methods=["PUT"])
def update_service_link(link_id):
    """Update a service link."""
    link_before = services_repo.get_service_link(link_id)

    error = require_team_write(link_before.service.team_id)
    if error:
        return error

    payload, error = validate_body(ServiceLinkUpdateSchema)
    if error:
        return error

    link = services_repo.update_service_link(
        link_id,
        payload.model_dump(),
    )

    write_audit(
        "service_link.update",
        object_type="service_link",
        object_id=link.id,
        group_id=link.service.group_id,
        team_id=link.service.team_id,
        data=payload.model_dump(),
    )

    return jsonify(serialize_service_link(link, current_user()))


@services_bp.route("/links/<int:link_id>", methods=["DELETE"])
def delete_service_link(link_id):
    """Delete a service link."""
    link_before = services_repo.get_service_link(link_id)

    error = require_team_write(link_before.service.team_id)
    if error:
        return error

    link = services_repo.soft_delete_service_link(link_id)

    write_audit(
        "service_link.delete",
        object_type="service_link",
        object_id=link.id,
        group_id=link.service.group_id,
        team_id=link.service.team_id,
        data={"deleted": True},
    )

    return jsonify({"deleted": True, "id": link.id})


@services_bp.route("/<int:service_id>/runbooks", methods=["GET"])
def list_service_runbooks(service_id):
    """Return service runbooks."""
    service = services_repo.get_service(service_id)

    error = require_team_read(service.team_id)
    if error:
        return error

    return jsonify([
        serialize_service_runbook(runbook, current_user())
        for runbook in services_repo.list_service_runbooks(service_id)
    ])


@services_bp.route("/<int:service_id>/runbooks", methods=["POST"])
def create_service_runbook(service_id):
    """Create a service runbook."""
    service = services_repo.get_service(service_id)

    error = require_team_write(service.team_id)
    if error:
        return error

    payload, error = validate_body(ServiceRunbookCreateSchema)
    if error:
        return error

    runbook = services_repo.create_service_runbook(
        service_id,
        payload.model_dump(),
    )

    write_audit(
        "service_runbook.create",
        object_type="service_runbook",
        object_id=runbook.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data=payload.model_dump(),
    )

    return jsonify(serialize_service_runbook(runbook, current_user())), 201


@services_bp.route("/runbooks/<int:runbook_id>", methods=["PUT"])
def update_service_runbook(runbook_id):
    """Update a service runbook."""
    runbook_before = services_repo.get_service_runbook(runbook_id)

    error = require_team_write(runbook_before.service.team_id)
    if error:
        return error

    payload, error = validate_body(ServiceRunbookUpdateSchema)
    if error:
        return error

    runbook = services_repo.update_service_runbook(
        runbook_id,
        payload.model_dump(),
    )

    write_audit(
        "service_runbook.update",
        object_type="service_runbook",
        object_id=runbook.id,
        group_id=runbook.service.group_id,
        team_id=runbook.service.team_id,
        data=payload.model_dump(),
    )

    return jsonify(serialize_service_runbook(runbook, current_user()))


@services_bp.route("/runbooks/<int:runbook_id>", methods=["DELETE"])
def delete_service_runbook(runbook_id):
    """Delete a service runbook."""
    runbook_before = services_repo.get_service_runbook(runbook_id)

    error = require_team_write(runbook_before.service.team_id)
    if error:
        return error

    runbook = services_repo.soft_delete_service_runbook(runbook_id)

    write_audit(
        "service_runbook.delete",
        object_type="service_runbook",
        object_id=runbook.id,
        group_id=runbook.service.group_id,
        team_id=runbook.service.team_id,
        data={"deleted": True},
    )

    return jsonify({"deleted": True, "id": runbook.id})


@services_bp.route("/<int:service_id>/dependencies", methods=["GET"])
def list_service_dependencies(service_id):
    """Return service dependencies."""
    service = services_repo.get_service(service_id)

    error = require_team_read(service.team_id)
    if error:
        return error

    return jsonify([
        serialize_service_dependency(dependency, current_user())
        for dependency in services_repo.list_service_dependencies(service_id)
    ])


@services_bp.route("/<int:service_id>/dependencies", methods=["POST"])
def create_service_dependency(service_id):
    """Create a service dependency."""
    service = services_repo.get_service(service_id)

    error = require_team_write(service.team_id)
    if error:
        return error

    payload, error = validate_body(ServiceDependencyCreateSchema)
    if error:
        return error

    validation_error = _validate_dependency_service(
        service,
        payload.depends_on_service_id,
    )
    if validation_error:
        return validation_error

    dependency = services_repo.create_service_dependency(
        service_id,
        {
            "depends_on_service": payload.depends_on_service_id,
            "dependency_type": payload.dependency_type,
            "criticality": payload.criticality,
            "description": payload.description,
            "enabled": payload.enabled,
        },
    )

    write_audit(
        "service_dependency.create",
        object_type="service_dependency",
        object_id=dependency.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data=payload.model_dump(),
    )

    return jsonify(serialize_service_dependency(dependency, current_user())), 201


@services_bp.route("/dependencies/<int:dependency_id>", methods=["PUT"])
def update_service_dependency(dependency_id):
    """Update a service dependency."""
    dependency_before = services_repo.get_service_dependency(dependency_id)
    service = dependency_before.service

    error = require_team_write(service.team_id)
    if error:
        return error

    payload, error = validate_body(ServiceDependencyUpdateSchema)
    if error:
        return error

    validation_error = _validate_dependency_service(
        service,
        payload.depends_on_service_id,
    )
    if validation_error:
        return validation_error

    dependency = services_repo.update_service_dependency(
        dependency_id,
        {
            "depends_on_service": payload.depends_on_service_id,
            "dependency_type": payload.dependency_type,
            "criticality": payload.criticality,
            "description": payload.description,
            "enabled": payload.enabled,
        },
    )

    write_audit(
        "service_dependency.update",
        object_type="service_dependency",
        object_id=dependency.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data=payload.model_dump(),
    )

    return jsonify(serialize_service_dependency(dependency, current_user()))


@services_bp.route("/dependencies/<int:dependency_id>", methods=["DELETE"])
def delete_service_dependency(dependency_id):
    """Delete a service dependency."""
    dependency_before = services_repo.get_service_dependency(dependency_id)
    service = dependency_before.service

    error = require_team_write(service.team_id)
    if error:
        return error

    dependency = services_repo.soft_delete_service_dependency(dependency_id)

    write_audit(
        "service_dependency.delete",
        object_type="service_dependency",
        object_id=dependency.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data={"deleted": True},
    )

    return jsonify({"deleted": True, "id": dependency.id})


@services_bp.route("/links", methods=["GET"])
def list_all_service_links():
    """Return links for all readable services in current scope."""
    services, error = _readable_services_from_request()
    if error:
        return error

    service_ids = [service.id for service in services]

    return jsonify([
        serialize_service_link(link, current_user())
        for link in services_repo.list_service_links(service_ids=service_ids)
    ])


@services_bp.route("/runbooks", methods=["GET"])
def list_all_service_runbooks():
    """Return runbooks for all readable services in current scope."""
    services, error = _readable_services_from_request()
    if error:
        return error

    service_ids = [service.id for service in services]

    return jsonify([
        serialize_service_runbook(runbook, current_user())
        for runbook in services_repo.list_service_runbooks(service_ids=service_ids)
    ])


@services_bp.route("/dependencies", methods=["GET"])
def list_all_service_dependencies():
    """Return dependencies for all readable services in current scope."""
    services, error = _readable_services_from_request()
    if error:
        return error

    service_ids = [service.id for service in services]

    return jsonify([
        serialize_service_dependency(dependency, current_user())
        for dependency in services_repo.list_service_dependencies(service_ids=service_ids)
    ])


@services_bp.route("/analytics", methods=["GET"])
def service_analytics():
    """Return Service Analytics v2 for readable services."""

    query, error = validate_query(ServiceAnalyticsQuerySchema)

    if error:
        return error

    team_ids = None

    if query.service_id:
        try:
            service = services_repo.get_service(query.service_id)
        except DoesNotExist:
            return make_error_response(
                "service_not_found",
                "Service was not found",
                404,
                service_id=query.service_id,
            )

        if getattr(service, "deleted", False):
            return make_error_response(
                "service_not_found",
                "Service was not found",
                404,
                service_id=query.service_id,
            )

        if not query.include_disabled and not service.enabled:
            return make_error_response(
                "service_not_found",
                "Service was not found",
                404,
                service_id=query.service_id,
            )

        error = require_team_read(service.team_id)

        if error:
            return error

        team_ids = [service.team_id]

    elif query.team_id:
        error = require_team_read(query.team_id)

        if error:
            return error

        team_ids = [query.team_id]

    else:
        team_ids = get_allowed_team_ids()

    payload = build_service_analytics_v2(
        query,
        team_ids=team_ids,
    )

    return jsonify(payload)


@services_bp.route("/impact", methods=["GET"])
def list_service_impact():
    """Return Service Impact v2 for readable services."""

    query, error = validate_query(ServiceImpactQuerySchema)

    if error:
        return error

    team_ids = None

    if query.service_id:
        service = services_repo.get_service(query.service_id)

        error = require_team_read(service.team_id)

        if error:
            return error

        team_ids = [service.team_id]

    elif query.team_id:
        error = require_team_read(query.team_id)

        if error:
            return error

        team_ids = [query.team_id]

    else:
        team_ids = get_allowed_team_ids()

    payload = build_service_impact_v2(
        query,
        team_ids=team_ids,
    )

    return jsonify(payload)


@services_bp.route("/<int:service_id>/impact", methods=["GET"])
def get_service_impact(service_id):
    """Return Service Impact v2 for one service."""

    service = services_repo.get_service(service_id)

    error = require_team_read(service.team_id)

    if error:
        return error

    query, error = validate_query(ServiceImpactServiceQuerySchema)

    if error:
        return error

    payload = build_single_service_impact_v2(
        service_id,
        query,
        team_ids=[service.team_id],
    )

    if not payload:
        return make_error_response(
            "service_not_found",
            "Service was not found",
            404,
            service_id=service_id,
        )

    return jsonify(payload)
