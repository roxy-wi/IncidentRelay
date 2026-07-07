import logging
from collections import defaultdict, deque

from app.modules.db.models import (
    AlertRoute,
    NotificationPolicyRule,
    NotificationPolicyRuleChannel,
    Service,
    ServiceChannel,
    ServiceDependency,
    ServiceMatchRule,
    Team,
)
from app.services.service_catalog.readiness import evaluate_service_readiness

logger = logging.getLogger("oncall.services.readiness")


def reconcile_service_readiness(service, *, trigger, actor_user=None):
    if service.deleted:
        return None

    return evaluate_service_readiness(
        service,
        trigger=trigger,
        actor_user=actor_user,
    )


def reconcile_services_readiness(services, *, trigger, actor_user=None):
    results = []
    processed_service_ids = set()

    for service in services:
        if service is None or service.id in processed_service_ids:
            continue

        processed_service_ids.add(service.id)
        result = reconcile_service_readiness(
            service,
            trigger=trigger,
            actor_user=actor_user,
        )

        if result is not None:
            results.append(result)

    return results


def list_services_by_ids(service_ids):
    service_ids = {int(service_id) for service_id in service_ids if service_id}

    if not service_ids:
        return []

    return list(
        Service.select()
        .where(Service.id.in_(service_ids), Service.deleted == False)
        .order_by(Service.id)
    )


def list_services_by_rotation(rotation_id):
    if not rotation_id:
        return []

    return list(
        Service.select()
        .where(Service.default_rotation == rotation_id, Service.deleted == False)
        .order_by(Service.id)
    )


def reconcile_rotation_services(rotation_id, *, trigger, actor_user=None):
    return reconcile_services_readiness(
        list_services_by_rotation(rotation_id),
        trigger=trigger,
        actor_user=actor_user,
    )


def list_services_by_escalation_policy(policy_id):
    if not policy_id:
        return []

    return list(
        Service.select()
        .where(
            Service.default_escalation_policy == policy_id,
            Service.deleted == False,
        )
        .order_by(Service.id)
    )


def reconcile_escalation_policy_services(policy_id, *, trigger, actor_user=None):
    return reconcile_services_readiness(
        list_services_by_escalation_policy(policy_id),
        trigger=trigger,
        actor_user=actor_user,
    )


def list_services_by_notification_policy(policy_id):
    if not policy_id:
        return []

    return list(
        Service.select()
        .where(Service.notification_policy == policy_id, Service.deleted == False)
        .order_by(Service.id)
    )


def reconcile_notification_policy_services(policy_id, *, trigger, actor_user=None):
    return reconcile_services_readiness(
        list_services_by_notification_policy(policy_id),
        trigger=trigger,
        actor_user=actor_user,
    )


def list_services_by_route(route_id, extra_service_ids=None):
    service_ids = {
        int(service_id)
        for service_id in extra_service_ids or []
        if service_id
    }

    route = AlertRoute.get_or_none(AlertRoute.id == route_id)

    if route and route.service_id:
        service_ids.add(route.service_id)

    rule_service_ids = (
        ServiceMatchRule.select(ServiceMatchRule.service)
        .where(
            ServiceMatchRule.route == route_id,
            ServiceMatchRule.enabled == True,
            ServiceMatchRule.deleted == False,
        )
        .tuples()
    )

    service_ids.update(service_id for service_id, in rule_service_ids)

    return list_services_by_ids(service_ids)


def reconcile_route_services(
    route_id,
    *,
    trigger,
    actor_user=None,
    extra_service_ids=None,
):
    return reconcile_services_readiness(
        list_services_by_route(route_id, extra_service_ids=extra_service_ids),
        trigger=trigger,
        actor_user=actor_user,
    )


def list_services_by_channel(channel_id):
    service_ids = {
        service_id
        for service_id, in (
            ServiceChannel.select(ServiceChannel.service)
            .where(
                ServiceChannel.channel == channel_id,
                ServiceChannel.enabled == True,
            )
            .tuples()
        )
    }

    policy_ids = {
        policy_id
        for policy_id, in (
            NotificationPolicyRule.select(NotificationPolicyRule.policy)
            .join(NotificationPolicyRuleChannel)
            .where(
                NotificationPolicyRuleChannel.channel == channel_id,
                NotificationPolicyRule.enabled == True,
                NotificationPolicyRule.deleted == False,
            )
            .distinct()
            .tuples()
        )
    }

    if policy_ids:
        policy_service_ids = (
            Service.select(Service.id)
            .where(
                Service.notification_policy.in_(policy_ids),
                Service.deleted == False,
            )
            .tuples()
        )
        service_ids.update(service_id for service_id, in policy_service_ids)

    return list_services_by_ids(service_ids)


def reconcile_channel_services(channel_id, *, trigger, actor_user=None):
    return reconcile_services_readiness(
        list_services_by_channel(channel_id),
        trigger=trigger,
        actor_user=actor_user,
    )


def list_dependency_component_services(service_ids):
    seed_ids = {int(service_id) for service_id in service_ids if service_id}

    if not seed_ids:
        return []

    graph = defaultdict(set)
    dependencies = ServiceDependency.select().where(
        ServiceDependency.enabled == True,
        ServiceDependency.deleted == False,
    )

    for dependency in dependencies:
        graph[dependency.service_id].add(dependency.depends_on_service_id)
        graph[dependency.depends_on_service_id].add(dependency.service_id)

    reachable_ids = set(seed_ids)
    pending_ids = deque(seed_ids)

    while pending_ids:
        service_id = pending_ids.popleft()

        for related_service_id in graph.get(service_id, set()):
            if related_service_id in reachable_ids:
                continue

            reachable_ids.add(related_service_id)
            pending_ids.append(related_service_id)

    return list(
        Service.select()
        .where(
            Service.id.in_(reachable_ids),
            Service.deleted == False,
        )
        .order_by(Service.id)
    )


def reconcile_dependency_component(service_ids, *, trigger, actor_user=None):
    services = list_dependency_component_services(service_ids)

    return reconcile_services_readiness(
        services,
        trigger=trigger,
        actor_user=actor_user,
    )


def list_services_for_route(route_id):
    if not route_id:
        return []

    service_ids = set()

    direct_services = Service.select(Service.id).where(
        Service.deleted == False,
        Service.id.in_(
            AlertRoute.select(AlertRoute.service).where(
                AlertRoute.id == route_id,
                AlertRoute.service.is_null(False),
            )
        ),
    )

    service_ids.update(service.id for service in direct_services)

    matched_services = Service.select(Service.id).where(
        Service.deleted == False,
        Service.id.in_(
            ServiceMatchRule.select(ServiceMatchRule.service).where(
                ServiceMatchRule.route == route_id,
                ServiceMatchRule.deleted == False,
            )
        ),
    )

    service_ids.update(service.id for service in matched_services)

    if not service_ids:
        return []

    return list(
        Service.select()
        .where(Service.id.in_(service_ids))
        .order_by(Service.id)
    )


def list_group_services(group_id):
    return list(
        Service.select()
        .join(Team)
        .where(
            ((Service.group == group_id) | (Team.group == group_id)),
            Service.deleted == False,
        )
        .order_by(Service.id)
    )


def reconcile_group_readiness(group_id, *, trigger, actor_user=None):
    results = []

    for service in list_group_services(group_id):
        result = reconcile_service_readiness(
            service,
            trigger=trigger,
            actor_user=actor_user,
        )

        if result is not None:
            results.append(result)

    return results
