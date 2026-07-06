from datetime import datetime

from peewee import fn

from app.modules.db.models import (
    BusinessService,
    BusinessServiceComponent,
    BusinessServiceIncidentImpact,
    BusinessServiceStatusHistory,
)


def set_business_service_manual_status(
    business_service_id,
    manual_status,
    message=None,
    until=None,
    user_id=None,
):
    now = datetime.utcnow()

    BusinessService.update(
        manual_status=manual_status,
        manual_status_message=message,
        manual_status_until=until,
        manual_status_set_by=user_id,
        manual_status_set_at=now,
        updated_at=now,
    ).where(BusinessService.id == business_service_id).execute()

    return get_business_service(business_service_id)


def clear_business_service_manual_status(business_service_id):
    now = datetime.utcnow()

    BusinessService.update(
        manual_status=None,
        manual_status_message=None,
        manual_status_until=None,
        manual_status_set_by=None,
        manual_status_set_at=None,
        updated_at=now,
    ).where(BusinessService.id == business_service_id).execute()

    return get_business_service(business_service_id)


def get_business_service(business_service_id):
    return BusinessService.get_by_id(business_service_id)


def get_business_service_or_none(business_service_id):
    if not business_service_id:
        return None

    return BusinessService.get_or_none(
        (BusinessService.id == business_service_id)
        & (BusinessService.deleted == False)  # noqa: E712
    )


def get_business_service_by_slug(group_id, slug):
    return BusinessService.get_or_none(
        (BusinessService.group == group_id)
        & (BusinessService.slug == slug)
        & (BusinessService.deleted == False)  # noqa: E712
    )


def list_business_services(group_id=None, public_only=False, active_only=True):
    query = BusinessService.select().where(BusinessService.deleted == False)  # noqa: E712

    if group_id:
        query = query.where(BusinessService.group == group_id)

    if public_only:
        query = query.where(BusinessService.public == True)  # noqa: E712

    if active_only:
        query = query.where(BusinessService.enabled == True)  # noqa: E712

    return list(query.order_by(BusinessService.public_order.asc(), BusinessService.name.asc()))


def create_business_service(data):
    data = dict(data)
    now = datetime.utcnow()
    data.setdefault("status", "unknown")
    data.setdefault("status_source", "calculated")
    data.setdefault("created_at", now)
    data["updated_at"] = now
    return BusinessService.create(**data)


def update_business_service(business_service_id, data):
    business_service = get_business_service(business_service_id)

    for field, value in data.items():
        setattr(business_service, field, value)

    business_service.updated_at = datetime.utcnow()
    business_service.save()

    return business_service


def soft_delete_business_service(business_service_id):
    business_service = get_business_service(business_service_id)
    now = datetime.utcnow()
    business_service.deleted = True
    business_service.deleted_at = now
    business_service.enabled = False
    business_service.updated_at = now
    business_service.save()

    BusinessServiceComponent.update(
        deleted=True,
        deleted_at=now,
        enabled=False,
        updated_at=now,
    ).where(BusinessServiceComponent.business_service == business_service.id).execute()

    return business_service


def list_business_service_components(business_service_id, active_only=True):
    query = BusinessServiceComponent.select().where(
        (BusinessServiceComponent.business_service == business_service_id)
        & (BusinessServiceComponent.deleted == False)  # noqa: E712
    )

    if active_only:
        query = query.where(BusinessServiceComponent.enabled == True)  # noqa: E712

    return list(query.order_by(BusinessServiceComponent.position.asc(), BusinessServiceComponent.id.asc()))


def list_business_service_components_for_groups(group_ids=None, active_only=True):
    query = (
        BusinessServiceComponent
        .select(BusinessServiceComponent, BusinessService)
        .join(BusinessService)
        .where(
            (BusinessService.deleted == False)  # noqa: E712
            & (BusinessServiceComponent.deleted == False)  # noqa: E712
        )
    )

    if group_ids is not None:
        group_ids = list(group_ids or [])
        if not group_ids:
            return []
        query = query.where(BusinessService.group.in_(group_ids))

    if active_only:
        query = query.where(
            (BusinessService.enabled == True)  # noqa: E712
            & (BusinessServiceComponent.enabled == True)  # noqa: E712
        )

    return list(
        query.order_by(
            BusinessService.public_order.asc(),
            BusinessService.name.asc(),
            BusinessServiceComponent.position.asc(),
            BusinessServiceComponent.id.asc(),
        )
    )


def list_components_for_service(service_id, active_only=True):
    query = BusinessServiceComponent.select().where(
        (BusinessServiceComponent.service == service_id)
        & (BusinessServiceComponent.deleted == False)  # noqa: E712
    )

    if active_only:
        query = query.where(BusinessServiceComponent.enabled == True)  # noqa: E712

    return list(query)


def create_business_service_component(business_service_id, data):
    data = dict(data)
    now = datetime.utcnow()
    data["business_service"] = business_service_id
    data.setdefault("created_at", now)
    data["updated_at"] = now
    return BusinessServiceComponent.create(**data)


def update_business_service_component(component_id, data):
    component = BusinessServiceComponent.get_by_id(component_id)

    for field, value in data.items():
        setattr(component, field, value)

    component.updated_at = datetime.utcnow()
    component.save()

    return component


def count_business_service_components(business_service_id, active_only=True):
    query = BusinessServiceComponent.select().where(
        (BusinessServiceComponent.business_service == business_service_id)
        & (BusinessServiceComponent.deleted == False)  # noqa: E712
    )

    if active_only:
        query = query.where(BusinessServiceComponent.enabled == True)  # noqa: E712

    return query.count()


def count_components_by_business_service_ids(business_service_ids, active_only=True):
    business_service_ids = list(business_service_ids or [])

    if not business_service_ids:
        return {}

    query = (
        BusinessServiceComponent
        .select(
            BusinessServiceComponent.business_service,
            fn.COUNT(BusinessServiceComponent.id).alias("components_count"),
        )
        .where(
            (BusinessServiceComponent.business_service.in_(business_service_ids))
            & (BusinessServiceComponent.deleted == False)  # noqa: E712
        )
        .group_by(BusinessServiceComponent.business_service)
    )

    if active_only:
        query = query.where(BusinessServiceComponent.enabled == True)  # noqa: E712

    return {
        item.business_service_id: item.components_count
        for item in query
    }


def soft_delete_business_service_component(component_id):
    component = BusinessServiceComponent.get_by_id(component_id)
    now = datetime.utcnow()
    component.deleted = True
    component.deleted_at = now
    component.enabled = False
    component.updated_at = now
    component.save()
    return component


def create_business_service_status_history(
    business_service,
    old_status,
    new_status,
    *,
    status_source="calculated",
    message=None,
    impact_score=0,
    component_snapshot=None,
):
    return BusinessServiceStatusHistory.create(
        business_service=business_service,
        old_status=old_status,
        new_status=new_status,
        status_source=status_source,
        message=message,
        impact_score=impact_score,
        component_snapshot=component_snapshot or [],
    )


def list_business_service_status_history(business_service_id, limit=50):
    return list(
        BusinessServiceStatusHistory
        .select()
        .where(BusinessServiceStatusHistory.business_service == business_service_id)
        .order_by(BusinessServiceStatusHistory.created_at.desc())
        .limit(limit)
    )


def get_incident_impact(business_service_id, group_id, relation="component_alert"):
    return BusinessServiceIncidentImpact.get_or_none(
        (BusinessServiceIncidentImpact.business_service == business_service_id)
        & (BusinessServiceIncidentImpact.group == group_id)
        & (BusinessServiceIncidentImpact.relation == relation)
    )


def upsert_incident_impact(
    business_service,
    group,
    *,
    service=None,
    impact_status,
    impact_score=0,
    relation="component_alert",
    reason=None,
    component_snapshot=None,
):
    now = datetime.utcnow()

    impact, created = BusinessServiceIncidentImpact.get_or_create(
        business_service=business_service.id,
        group=group.id,
        relation=relation,
        defaults={
            "service": getattr(service, "id", None),
            "impact_status": impact_status,
            "impact_score": impact_score,
            "reason": reason,
            "active": True,
            "component_snapshot": component_snapshot or [],
            "first_seen_at": now,
            "last_seen_at": now,
            "updated_at": now,
        },
    )

    if created:
        return impact

    impact.service = getattr(service, "id", None)
    impact.impact_status = impact_status
    impact.impact_score = impact_score
    impact.reason = reason
    impact.active = True
    impact.component_snapshot = component_snapshot or []
    impact.last_seen_at = now
    impact.updated_at = now
    impact.save()

    return impact


def deactivate_incident_impacts_for_group(group_id):
    now = datetime.utcnow()

    return (
        BusinessServiceIncidentImpact
        .update(active=False, updated_at=now, last_seen_at=now)
        .where(
            (BusinessServiceIncidentImpact.group == group_id)
            & (BusinessServiceIncidentImpact.active == True)  # noqa: E712
        )
        .execute()
    )


def list_active_incident_impacts(group_id):
    return list(
        BusinessServiceIncidentImpact
        .select()
        .where(
            (BusinessServiceIncidentImpact.group == group_id)
            & (BusinessServiceIncidentImpact.active == True)  # noqa: E712
        )
        .order_by(BusinessServiceIncidentImpact.impact_score.desc())
    )


def get_business_service_component(component_id):
    return BusinessServiceComponent.get_by_id(component_id)
