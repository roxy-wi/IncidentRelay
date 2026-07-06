from app.services.serializers.common import attach_group_permissions, serialize_utc_datetime
from app.services.service_catalog.impact import build_service_effective_impact_map


def serialize_business_service_component(component, current_user=None, impact_map=None):
    """Serialize one business service component."""
    business_service = component.business_service
    service = component.service if component.service_id else None
    team = service.team if service and service.team_id else None
    impact_item = impact_map.get(component.service_id) if impact_map else None
    service_status = component.service.status if component.service_id and component.service else "unknown"
    effective_status = (
        impact_item.get("effective_status")
        if impact_item
        else service_status
    )

    data = {
        "id": component.id,
        "business_service_id": business_service.id,
        "business_service_slug": business_service.slug,
        "business_service_name": business_service.name,
        "business_service_status": business_service.status,
        "business_service_status_source": business_service.status_source,
        "business_service_status_message": business_service.status_message,
        "service_id": service.id if service else component.service_id,
        "service_slug": service.slug if service else None,
        "service_name": service.name if service else None,
        "service_status": service_status,
        "effective_status": effective_status,
        "effective_status_reason": impact_item.get("primary_reason") if impact_item else "own_status",
        "alert_impact_status": impact_item.get("alert_impact_status") if impact_item else "operational",
        "dependency_impact_status": impact_item.get("dependency_impact_status") if impact_item else "operational",
        "open_alert_groups": impact_item.get("open_alert_groups") if impact_item else 0,
        "critical_open_alert_groups": impact_item.get("critical_open_alert_groups") if impact_item else 0,
        "upstream_issues_count": impact_item.get("upstream_issues_count") if impact_item else 0,
        "service_criticality": service.criticality if service else None,
        "service_environment": service.environment if service else None,
        "team_id": team.id if team else None,
        "team_slug": team.slug if team else None,
        "team_name": team.name if team else None,
        "component_type": component.component_type,
        "criticality": component.criticality,
        "impact_weight": component.impact_weight,
        "position": component.position,
        "status_rule": component.status_rule,
        "description": component.description,
        "enabled": component.enabled,
        "created_at": serialize_utc_datetime(component.created_at),
        "updated_at": serialize_utc_datetime(component.updated_at),
    }

    return attach_group_permissions(data, business_service.group_id, current_user)


def serialize_business_service_status_history(row):
    """Serialize business service status history row."""
    return {
        "id": row.id,
        "business_service_id": row.business_service_id,
        "old_status": row.old_status,
        "new_status": row.new_status,
        "status_source": row.status_source,
        "message": row.message,
        "impact_score": row.impact_score,
        "component_snapshot": row.component_snapshot or [],
        "created_at": serialize_utc_datetime(row.created_at),
    }


def serialize_business_service_incident_impact(impact):
    """Serialize business impact attached to an alert group."""
    business_service = impact.business_service
    service = impact.service if impact.service_id else None

    return {
        "id": impact.id,
        "business_service_id": business_service.id,
        "business_service_slug": business_service.slug,
        "business_service_name": business_service.name,
        "public_name": business_service.public_name or business_service.name,
        "service_id": service.id if service else None,
        "service_slug": service.slug if service else None,
        "service_name": service.name if service else None,
        "impact_status": impact.impact_status,
        "impact_score": impact.impact_score,
        "relation": impact.relation,
        "reason": impact.reason,
        "active": impact.active,
        "component_snapshot": impact.component_snapshot or [],
        "first_seen_at": serialize_utc_datetime(impact.first_seen_at),
        "last_seen_at": serialize_utc_datetime(impact.last_seen_at),
        "updated_at": serialize_utc_datetime(impact.updated_at),
    }


def serialize_alert_group_business_impact_summary(group):
    """Serialize compact business impact summary for alert list rows."""
    from app.modules.db import business_services_repo

    impacts = business_services_repo.list_active_incident_impacts(group.id)

    if not impacts:
        return {
            "has_business_impact": False,
            "total": 0,
            "highest_status": None,
            "highest_score": 0,
            "services": [],
        }

    status_order = {
        "unknown": 0,
        "operational": 1,
        "maintenance": 2,
        "degraded": 3,
        "partial_outage": 4,
        "major_outage": 5,
    }

    sorted_impacts = sorted(
        impacts,
        key=lambda item: (
            status_order.get(item.impact_status, 0),
            item.impact_score or 0,
        ),
        reverse=True,
    )

    highest = sorted_impacts[0]

    return {
        "has_business_impact": True,
        "total": len(impacts),
        "highest_status": highest.impact_status,
        "highest_score": highest.impact_score,
        "services": [
            {
                "business_service_id": impact.business_service_id,
                "business_service_slug": impact.business_service.slug,
                "business_service_name": impact.business_service.name,
                "public_name": impact.business_service.public_name or impact.business_service.name,
                "impact_status": impact.impact_status,
                "impact_score": impact.impact_score,
            }
            for impact in sorted_impacts[:3]
        ],
    }


def serialize_business_service(
    business_service,
    current_user=None,
    components=None,
    history=None,
    components_count=None,
):
    """Serialize business service."""
    from app.services.business_services.status import is_business_service_manual_status_active

    group = business_service.group if business_service.group_id else None
    owner_team = business_service.owner_team if business_service.owner_team_id else None

    data = {
        "id": business_service.id,
        "group_id": group.id if group else None,
        "group_slug": group.slug if group else None,
        "group_name": group.name if group else None,
        "owner_team_id": owner_team.id if owner_team else None,
        "owner_team_slug": owner_team.slug if owner_team else None,
        "owner_team_name": owner_team.name if owner_team else None,

        "slug": business_service.slug,
        "name": business_service.name,
        "description": business_service.description,

        "status": business_service.status,
        "status_source": business_service.status_source,
        "status_message": business_service.status_message,
        "status_updated_at": serialize_utc_datetime(business_service.status_updated_at),

        "manual_status": business_service.manual_status,
        "manual_status_message": business_service.manual_status_message,
        "manual_status_until": serialize_utc_datetime(business_service.manual_status_until),
        "manual_status_set_by_id": business_service.manual_status_set_by_id,
        "manual_status_set_at": serialize_utc_datetime(business_service.manual_status_set_at),
        "manual_status_active": is_business_service_manual_status_active(business_service),

        "criticality": business_service.criticality,
        "tier": business_service.tier,

        "public": business_service.public,
        "public_name": business_service.public_name,
        "public_description": business_service.public_description,
        "public_order": business_service.public_order,

        "labels": business_service.labels or {},
        "metadata": business_service.metadata or {},

        "enabled": business_service.enabled,
        "components_count": (
            components_count
            if components_count is not None
            else len(components)
            if components is not None
            else None
        ),
        "created_at": serialize_utc_datetime(business_service.created_at),
        "updated_at": serialize_utc_datetime(business_service.updated_at),
    }

    if components is not None:
        component_impact_map = build_service_effective_impact_map(
            [component.service_id for component in components],
            max_depth=5,
        )

        data["components"] = [
            serialize_business_service_component(
                component,
                current_user=current_user,
                impact_map=component_impact_map,
            )
            for component in components
        ]
        data["components_count"] = len(components)

    if history is not None:
        data["status_history"] = [
            serialize_business_service_status_history(row)
            for row in history
        ]

    return attach_group_permissions(data, business_service.group_id, current_user)
