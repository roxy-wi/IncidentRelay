import logging
from datetime import datetime

from app.db import database_proxy
from app.modules.db import business_services_repo
from app.modules.db.models import ServiceDependency
from app.services.service_catalog.impact import build_service_effective_impact_map
from app.services.service_catalog.impact_scoring import (
    COMPONENT_CRITICALITY_MULTIPLIER,
    clamp_impact_score,
    combined_impact_score,
    status_from_impact_score,
)
from app.modules.common import utc_now

logger = logging.getLogger("oncall.business_services")

BUSINESS_STATUS_ORDER = {
    "operational": 0,
    "unknown": 10,
    "degraded": 30,
    "partial_outage": 60,
    "major_outage": 100,
    "maintenance": 20,
}

TECHNICAL_STATUS_SCORE = {
    "operational": 0,
    "ok": 0,
    "healthy": 0,
    "unknown": 20,
    "warning": 30,
    "degraded": 40,
    "maintenance": 20,
    "partial_outage": 65,
    "major_outage": 100,
    "down": 100,
    "critical": 100,
    "firing": 100,
}

CRITICALITY_MULTIPLIER = COMPONENT_CRITICALITY_MULTIPLIER


def is_business_service_manual_status_active(business_service, now=None):
    if not getattr(business_service, "manual_status", None):
        return False

    until = getattr(business_service, "manual_status_until", None)

    if until is None:
        return True

    now = now or utc_now()

    return until > now


def clear_expired_business_service_manual_status(business_service, now=None):
    if not getattr(business_service, "manual_status", None):
        return False

    until = getattr(business_service, "manual_status_until", None)

    if until is None:
        return False

    now = now or utc_now()

    if until > now:
        return False

    business_service.manual_status = None
    business_service.manual_status_message = None
    business_service.manual_status_until = None
    business_service.manual_status_set_by = None
    business_service.manual_status_set_at = None
    business_service.updated_at = now
    business_service.save()

    return True


def apply_business_service_manual_override(business_service, calculated_result):
    clear_expired_business_service_manual_status(business_service)

    if not is_business_service_manual_status_active(business_service):
        calculated_result["status_source"] = "calculated"
        calculated_result["manual_status_active"] = False
        return calculated_result

    result = dict(calculated_result)
    result["status"] = business_service.manual_status
    result["status_source"] = "manual"
    result["status_message"] = business_service.manual_status_message
    result["manual_status_active"] = True
    result["calculated_status"] = calculated_result.get("status")
    result["calculated_impact_score"] = calculated_result.get("impact_score", 0)

    return result


def normalize_technical_status(status):
    value = str(status or "unknown").strip().lower()
    return value or "unknown"


def technical_status_score(status):
    return TECHNICAL_STATUS_SCORE.get(normalize_technical_status(status), 20)


def component_service_effective_impact_score(component, impact_map=None):
    impact_item = component_service_impact_item(component, impact_map=impact_map)

    if impact_item:
        return clamp_impact_score(
            impact_item.get("effective_impact_score")
            or impact_item.get("impact_score")
            or technical_status_score(impact_item.get("effective_status"))
        )

    return clamp_impact_score(technical_status_score(component_service_raw_status(component)))


def component_criticality_multiplier(component):
    return CRITICALITY_MULTIPLIER.get(component.criticality, 1.0)


def component_impact_score(component, impact_map=None):
    base_score = component_service_effective_impact_score(component, impact_map=impact_map)
    multiplier = component_criticality_multiplier(component)
    weight = clamp_impact_score(component.impact_weight or 0)

    return clamp_impact_score(base_score * multiplier * weight / 100)


def component_service_raw_status(component):
    service = component.service if getattr(component, "service_id", None) else None

    if not service:
        return "unknown"

    return normalize_technical_status(service.status)


def component_service_impact_item(component, impact_map=None):
    if not impact_map or not getattr(component, "service_id", None):
        return None

    return impact_map.get(component.service_id)


def component_service_effective_status(component, impact_map=None):
    impact_item = component_service_impact_item(component, impact_map=impact_map)

    if impact_item:
        return normalize_technical_status(
            impact_item.get("effective_status")
            or impact_item.get("own_status")
            or component_service_raw_status(component)
        )

    return component_service_raw_status(component)


def component_service_effective_reason(component, impact_map=None):
    impact_item = component_service_impact_item(component, impact_map=impact_map)

    if not impact_item:
        return "own_status"

    return impact_item.get("primary_reason") or "none"


def status_from_score(score, has_required_major=False):
    if has_required_major:
        return "major_outage"

    return status_from_impact_score(score)


def component_snapshot_row(component, impact_score, impact_map=None):
    service = component.service
    impact_item = component_service_impact_item(component, impact_map=impact_map)

    return {
        "component_id": component.id,
        "service_id": service.id,
        "service_slug": service.slug,
        "service_name": service.name,
        "team_id": service.team_id,
        "team_slug": service.team.slug if service.team_id and service.team else None,
        "team_name": service.team.name if service.team_id and service.team else None,
        "service_status": component_service_raw_status(component),
        "effective_status": component_service_effective_status(component, impact_map=impact_map),
        "effective_status_reason": component_service_effective_reason(component, impact_map=impact_map),
        "alert_impact_status": impact_item.get("alert_impact_status") if impact_item else "operational",
        "dependency_impact_status": impact_item.get("dependency_impact_status") if impact_item else "operational",
        "own_impact_score": impact_item.get("own_impact_score") if impact_item else technical_status_score(component_service_raw_status(component)),
        "alert_impact_score": impact_item.get("alert_impact_score") if impact_item else 0,
        "dependency_impact_score": impact_item.get("dependency_impact_score") if impact_item else 0,
        "effective_impact_score": component_service_effective_impact_score(component, impact_map=impact_map),
        "service_impact_score": component_service_effective_impact_score(component, impact_map=impact_map),
        "component_multiplier": component_criticality_multiplier(component),
        "weighted_impact_score": impact_score,
        "open_alert_groups": impact_item.get("open_alert_groups") if impact_item else 0,
        "critical_open_alert_groups": impact_item.get("critical_open_alert_groups") if impact_item else 0,
        "upstream_issues_count": impact_item.get("upstream_issues_count") if impact_item else 0,
        "criticality": component.criticality,
        "impact_weight": component.impact_weight,
        "impact_score": impact_score,
    }


def calculate_business_service_status(business_service):
    components = business_services_repo.list_business_service_components(
        business_service.id,
        active_only=True,
    )

    if not components:
        return {
            "status": "unknown",
            "status_source": "calculated",
            "status_message": "Calculated status: no enabled components",
            "impact_score": 0,
            "component_snapshot": [],
        }

    impact_map = build_service_effective_impact_map(
        [component.service_id for component in components],
        max_depth=5,
    )

    component_snapshot = []
    component_scores = []

    for component in components:
        score = component_impact_score(component, impact_map=impact_map)
        component_scores.append(score)

        component_snapshot.append(
            component_snapshot_row(
                component,
                score,
                impact_map=impact_map,
            )
        )

    impact_score = combined_impact_score(component_scores)
    status = status_from_score(impact_score)

    return {
        "status": status,
        "status_source": "calculated",
        "status_message": calculated_business_service_status_message({
            "status": status,
            "impact_score": impact_score,
            "component_snapshot": component_snapshot,
        }),
        "impact_score": impact_score,
        "component_snapshot": component_snapshot,
    }

def calculated_business_service_status_message(result):
    """Build stable human-readable message for calculated business status."""
    message = result.get("status_message") or result.get("message")

    if message:
        return message

    status = result.get("status") or "unknown"
    impact_score = int(result.get("impact_score") or 0)
    component_snapshot = result.get("component_snapshot") or []

    if not component_snapshot:
        return "Calculated status: no enabled components"

    affected = []

    for item in component_snapshot:
        service_status = (
            item.get("effective_status")
            or item.get("status")
            or item.get("service_status")
            or item.get("technical_status")
        )

        if service_status in ("operational", "unknown", None, ""):
            continue

        affected.append(
            item.get("service_name")
            or item.get("service_slug")
            or item.get("name")
            or str(item.get("service_id") or "service")
        )

    if affected:
        return (
            "Affected components: "
            + ", ".join(affected[:3])
            + f". Calculated status: {status}, impact score={impact_score}"
        )

    return f"Calculated status: {status}, impact score={impact_score}"


def apply_business_service_status(business_service):
    """Calculate and persist current business service status."""
    # Reload because callers may pass a stale model instance after repo.update().
    business_service = type(business_service).get_by_id(business_service.id)

    calculated_result = calculate_business_service_status(business_service)
    result = apply_business_service_manual_override(business_service, calculated_result)

    old_status = business_service.status
    old_source = business_service.status_source
    old_message = business_service.status_message

    new_status = result["status"]
    new_source = result.get("status_source", "calculated")

    if new_source == "manual":
        new_message = result.get("status_message")
    else:
        new_message = calculated_business_service_status_message(result)

    changed = (
        old_status != new_status
        or old_source != new_source
        or old_message != new_message
    )

    now = utc_now()

    business_service.status = new_status
    business_service.status_source = new_source
    business_service.status_message = new_message
    business_service.status_updated_at = now
    business_service.updated_at = now
    business_service.save()

    if changed:
        business_services_repo.create_business_service_status_history(
            business_service=business_service,
            old_status=old_status,
            new_status=new_status,
            status_source=new_source,
            message=new_message,
            impact_score=result.get("impact_score", 0),
            component_snapshot=result.get("component_snapshot", []),
        )

    result["status"] = new_status
    result["status_source"] = new_source
    result["status_message"] = new_message
    result["changed"] = changed
    result["old_status"] = old_status
    result["old_status_source"] = old_source
    result["old_status_message"] = old_message

    return result

def impacted_service_ids_for_technical_service(service_id, max_depth=5):
    """Return the alert service and downstream services affected through dependencies."""
    if not service_id:
        return set()

    service_id = int(service_id)
    seen = {service_id}
    frontier = {service_id}
    depth = 0

    while frontier and depth < int(max_depth or 5):
        dependencies = list(
            ServiceDependency
            .select()
            .where(
                (ServiceDependency.deleted == False)  # noqa: E712
                & (ServiceDependency.enabled == True)  # noqa: E712
                & (ServiceDependency.depends_on_service.in_(frontier))
            )
        )

        next_frontier = set()

        for dependency in dependencies:
            downstream_id = dependency.service_id

            if downstream_id in seen:
                continue

            seen.add(downstream_id)
            next_frontier.add(downstream_id)

        frontier = next_frontier
        depth += 1

    return seen


def refresh_business_services_for_technical_service(service_id):
    service_ids = impacted_service_ids_for_technical_service(service_id)
    refreshed = []
    refreshed_business_service_ids = set()

    with database_proxy.atomic():
        for impacted_service_id in service_ids:
            components = business_services_repo.list_components_for_service(impacted_service_id)

            for component in components:
                business_service = component.business_service

                if business_service.id in refreshed_business_service_ids:
                    continue

                if not business_service.enabled or business_service.deleted:
                    continue

                result = apply_business_service_status(business_service)
                refreshed.append((business_service, result))
                refreshed_business_service_ids.add(business_service.id)

    return refreshed


def refresh_business_services_safely_for_technical_service(service_id, reason=None):
    try:
        return refresh_business_services_for_technical_service(service_id)
    except Exception:
        logger.exception(
            "business service refresh failed",
            extra={"extra": {"service_id": service_id, "reason": reason}},
        )

    return []
