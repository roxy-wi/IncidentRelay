from dataclasses import dataclass, field
from typing import Any

from app.services.service_catalog.reconciliation import (
    list_services_by_ids,
    reconcile_dependency_component,
    reconcile_group_readiness,
    reconcile_service_readiness,
    reconcile_services_readiness,
)
from app.services.service_catalog.timeline import publish_service_event


READINESS_SCOPE_NONE = "none"
READINESS_SCOPE_SERVICE = "service"
READINESS_SCOPE_SERVICES = "services"
READINESS_SCOPE_GROUP = "group"
READINESS_SCOPE_DEPENDENCY_COMPONENT = "dependency_component"


@dataclass
class ServiceCatalogEventResult:
    timeline_event: Any | None = None
    readiness_results: list[Any] = field(default_factory=list)


def emit_service_catalog_event(
    service,
    *,
    category,
    event_type,
    title,
    summary=None,
    source="incidentrelay",
    source_ref=None,
    dedup_key=None,
    external_url=None,
    actor_user=None,
    actor_type=None,
    actor_label=None,
    severity=None,
    status=None,
    occurred_at=None,
    payload=None,
    before=None,
    after=None,
    readiness_scope=READINESS_SCOPE_SERVICE,
    readiness_trigger=None,
    affected_service_ids=None,
    group_id=None,
):
    """Emit one service-scoped catalog domain event.

    The event is synchronously materialized into the service timeline and may
    trigger readiness reconciliation. Keep this layer small: views should tell
    it what happened, and this layer decides which catalog projections/reactors
    must be updated.
    """
    event_payload = _event_payload(payload, before=before, after=after)

    timeline_event = publish_service_event(
        service,
        category=category,
        event_type=event_type,
        title=title,
        summary=summary,
        source=source,
        source_ref=source_ref,
        dedup_key=dedup_key,
        external_url=external_url,
        actor_user=actor_user,
        actor_type=actor_type,
        actor_label=actor_label,
        severity=severity,
        status=status,
        occurred_at=occurred_at,
        payload=event_payload,
    )

    readiness_results = _run_readiness_reactor(
        service,
        scope=readiness_scope,
        trigger=readiness_trigger or event_type,
        actor_user=actor_user,
        affected_service_ids=affected_service_ids,
        group_id=group_id,
    )

    return ServiceCatalogEventResult(
        timeline_event=timeline_event,
        readiness_results=readiness_results,
    )


def emit_group_service_catalog_event(
    group_id,
    *,
    category,
    event_type,
    title,
    summary=None,
    source="incidentrelay",
    actor_user=None,
    actor_type=None,
    actor_label=None,
    payload=None,
    before=None,
    after=None,
    readiness_trigger=None,
):
    """Emit one group-scoped catalog domain event.

    Today ServiceEvent is intentionally service-scoped, so group-level changes
    such as standards and checks do not create a separate timeline row by
    themselves. The readiness reactor will still evaluate affected group
    services, and readiness timeline events will be written for services whose
    readiness batch is created or changed.
    """
    _event_payload(payload, before=before, after=after)
    _ = (category, event_type, title, summary, source, actor_type, actor_label)

    readiness_results = reconcile_group_readiness(
        group_id,
        trigger=readiness_trigger or event_type,
        actor_user=actor_user,
    )

    return ServiceCatalogEventResult(
        timeline_event=None,
        readiness_results=readiness_results,
    )


def reconcile_service_catalog_readiness(service, *, trigger, actor_user=None):
    """Run service readiness through the catalog event adapter.

    This does not create an extra timeline row. The readiness evaluator itself
    writes readiness timeline events when the batch is created or changed.
    """
    results = _run_readiness_reactor(
        service,
        scope=READINESS_SCOPE_SERVICE,
        trigger=trigger,
        actor_user=actor_user,
    )

    return results[0] if results else None


def _event_payload(payload, *, before=None, after=None):
    event_payload = dict(payload or {})

    if before is not None:
        event_payload["before"] = before

    if after is not None:
        event_payload["after"] = after

    return event_payload


def _run_readiness_reactor(
    service,
    *,
    scope,
    trigger,
    actor_user=None,
    affected_service_ids=None,
    group_id=None,
):
    if scope == READINESS_SCOPE_NONE:
        return []

    if scope == READINESS_SCOPE_SERVICE:
        result = reconcile_service_readiness(
            service,
            trigger=trigger,
            actor_user=actor_user,
        )
        return [result] if result is not None else []

    if scope == READINESS_SCOPE_SERVICES:
        service_ids = {service.id}
        service_ids.update(
            int(service_id)
            for service_id in affected_service_ids or []
            if service_id
        )
        return reconcile_services_readiness(
            list_services_by_ids(service_ids),
            trigger=trigger,
            actor_user=actor_user,
        )

    if scope == READINESS_SCOPE_DEPENDENCY_COMPONENT:
        service_ids = {service.id}
        service_ids.update(
            int(service_id)
            for service_id in affected_service_ids or []
            if service_id
        )
        return reconcile_dependency_component(
            service_ids,
            trigger=trigger,
            actor_user=actor_user,
        )

    if scope == READINESS_SCOPE_GROUP:
        resolved_group_id = group_id or service.group_id
        return reconcile_group_readiness(
            resolved_group_id,
            trigger=trigger,
            actor_user=actor_user,
        )

    raise ValueError(f"Unsupported readiness scope: {scope}")
