import logging

from app.modules.db import alerts_repo, business_services_repo
from app.services.business_services.status import (
    calculate_business_service_status,
    impacted_service_ids_for_technical_service,
)

logger = logging.getLogger("oncall.business_services")

ACTIVE_GROUP_STATUSES = {"firing", "acknowledged"}


def _business_service_label(business_service):
    return (
        getattr(business_service, "public_name", None)
        or getattr(business_service, "name", None)
        or getattr(business_service, "slug", None)
        or f"Business service #{business_service.id}"
    )


def _service_label(service):
    if not service:
        return "-"

    return (
        getattr(service, "name", None)
        or getattr(service, "slug", None)
        or f"Service #{service.id}"
    )


def _impact_message(impact, action):
    business_service = impact.business_service
    service = impact.service if getattr(impact, "service_id", None) else None

    return (
        f"Business impact {action}: "
        f"{_business_service_label(business_service)} "
        f"{impact.impact_status}, score={impact.impact_score}, "
        f"via {_service_label(service)}"
    )


def _record_business_impact_event(group_id, event_type, message):
    alerts_repo.create_alert_event(
        group_id=group_id,
        event_type=event_type,
        message=message,
        user_id=None,
    )


def _record_business_impact_detected(impact):
    _record_business_impact_event(
        impact.group_id,
        "business_impact_detected",
        _impact_message(impact, "detected"),
    )


def _record_business_impact_updated(impact, old_status=None, old_score=None):
    message = _impact_message(impact, "updated")

    if old_status is not None or old_score is not None:
        message = (
            f"{message} "
            f"(previous: {old_status or '-'}, score={old_score if old_score is not None else '-'})"
        )

    _record_business_impact_event(
        impact.group_id,
        "business_impact_updated",
        message,
    )


def _record_business_impact_deactivated(impact):
    _record_business_impact_event(
        impact.group_id,
        "business_impact_deactivated",
        _impact_message(impact, "deactivated"),
    )


def _deactivate_business_impacts_for_group(group):
    active_impacts = business_services_repo.list_active_incident_impacts(group.id)

    if not active_impacts:
        return []

    business_services_repo.deactivate_incident_impacts_for_group(group.id)

    for impact in active_impacts:
        impact.active = False
        _record_business_impact_deactivated(impact)

    return active_impacts


def _should_record_impact_update(existing, impact_status, impact_score):
    if not existing:
        return False

    if not existing.active:
        return False

    return (
        existing.impact_status != impact_status
        or int(existing.impact_score or 0) != int(impact_score or 0)
    )


def _upsert_business_impact(group, business_service, service, status_result, relation="component_alert"):
    impact_status = status_result["status"]
    impact_score = status_result["impact_score"]
    component_snapshot = status_result["component_snapshot"]

    existing = business_services_repo.get_incident_impact(
        business_service.id,
        group.id,
        relation=relation,
    )

    was_inactive = bool(existing and not existing.active)
    old_status = existing.impact_status if existing else None
    old_score = existing.impact_score if existing else None
    should_update_event = _should_record_impact_update(existing, impact_status, impact_score)

    relation_label = "upstream dependency" if relation == "dependency_upstream_alert" else "component"
    reason = (
        f"Alert group #{group.id} affects business service "
        f"{business_service.name} through {relation_label} {service.name}."
    )

    impact = business_services_repo.upsert_incident_impact(
        business_service,
        group,
        service=service,
        impact_status=impact_status,
        impact_score=impact_score,
        relation=relation,
        reason=reason,
        component_snapshot=component_snapshot,
    )

    if not existing or was_inactive:
        _record_business_impact_detected(impact)
    elif should_update_event:
        _record_business_impact_updated(impact, old_status=old_status, old_score=old_score)

    return impact


def refresh_business_impacts_for_group(group):
    if getattr(group, "status", None) not in ACTIVE_GROUP_STATUSES:
        return _deactivate_business_impacts_for_group(group)

    service = group.service if getattr(group, "service_id", None) else None

    if not service:
        return _deactivate_business_impacts_for_group(group)

    service_ids = impacted_service_ids_for_technical_service(service.id)
    impacts = []
    seen = set()

    for impacted_service_id in service_ids:
        components = business_services_repo.list_components_for_service(impacted_service_id)
        relation = "component_alert" if impacted_service_id == service.id else "dependency_upstream_alert"

        for component in components:
            business_service = component.business_service

            if not business_service.enabled or business_service.deleted:
                continue

            key = (business_service.id, relation)

            if key in seen:
                continue

            status_result = calculate_business_service_status(business_service)

            impacts.append(
                _upsert_business_impact(
                    group,
                    business_service,
                    component.service,
                    status_result,
                    relation=relation,
                )
            )
            seen.add(key)

    if not impacts:
        return _deactivate_business_impacts_for_group(group)

    return impacts


def refresh_business_impacts_safely_for_group(group, reason=None):
    try:
        return refresh_business_impacts_for_group(group)
    except Exception:
        logger.exception(
            "business impact refresh failed",
            extra={
                "extra": {
                    "group_id": getattr(group, "id", None),
                    "service_id": getattr(group, "service_id", None),
                    "reason": reason,
                }
            },
        )

    return []
