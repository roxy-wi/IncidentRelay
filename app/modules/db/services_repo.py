from datetime import datetime

from app.modules.db.models import (
    Service,
    ServiceDependency,
    ServiceLink,
    ServiceMatchRule,
    ServiceRunbook,
    ServiceStatusHistory,
    Team,
    ServiceOwner,
    User,
)


def list_services(team_id=None, team_ids=None, include_disabled=True):
    """Return services filtered by team visibility."""
    query = (
        Service
        .select(Service, Team)
        .join(Team)
        .where(Service.deleted == False)
    )

    if team_id:
        query = query.where(Service.team == team_id)

    if team_ids is not None:
        team_ids = list(team_ids)
        if not team_ids:
            return []
        query = query.where(Service.team.in_(team_ids))

    if not include_disabled:
        query = query.where(Service.enabled == True)

    return list(query.order_by(Team.slug.asc(), Service.name.asc()))


def get_service(service_id, include_deleted=False):
    """Return a service by id."""
    query = Service.select().where(Service.id == service_id)

    if not include_deleted:
        query = query.where(Service.deleted == False)

    return query.get()


def get_service_or_none(service_id, include_deleted=False):
    """Return a service or None."""
    if not service_id:
        return None

    query = Service.select().where(Service.id == service_id)

    if not include_deleted:
        query = query.where(Service.deleted == False)

    return query.first()


def get_service_by_team_and_slug(team_id, slug, include_deleted=False):
    """Return a service by team and slug."""
    query = Service.select().where(
        Service.team == team_id,
        Service.slug == slug,
    )

    if not include_deleted:
        query = query.where(Service.deleted == False)

    return query.first()


def restore_service(service_id, data):
    """Restore and reconfigure a soft-deleted service."""
    service = get_service(service_id, include_deleted=True)

    if "team" in data:
        team = Team.get_by_id(data["team"])
        data["group"] = team.group_id

    for field, value in data.items():
        setattr(service, field, value)

    service.deleted = False
    service.deleted_at = None
    service.updated_at = datetime.utcnow()
    service.save()

    return service


def is_service_active(service):
    """Return True when service, team and group are usable."""
    if not service:
        return False

    if not service.enabled or service.deleted:
        return False

    if not service.team or not service.team.active or service.team.deleted:
        return False

    if service.team.group and (
        not service.team.group.active or service.team.group.deleted
    ):
        return False

    return True


def service_belongs_to_team(service_id, team_id):
    """Return True when service belongs to team."""
    service = get_service_or_none(service_id)
    return bool(service and service.team_id == team_id)


def create_service(data):
    """Create or restore a service."""
    data = dict(data)
    team = Team.get_by_id(data["team"])

    if not data.get("group"):
        data["group"] = team.group_id

    existing = get_service_by_team_and_slug(
        data["team"],
        data["slug"],
        include_deleted=True,
    )

    if existing and existing.deleted:
        return restore_service(existing.id, data)

    data["updated_at"] = datetime.utcnow()

    return Service.create(**data)


def update_service(service_id, data):
    """Update a service."""
    service = get_service(service_id)

    if "team" in data:
        team = Team.get_by_id(data["team"])
        data["group"] = team.group_id

    for field, value in data.items():
        setattr(service, field, value)

    service.updated_at = datetime.utcnow()
    service.save()

    return service


def soft_delete_service(service_id):
    """Soft-delete a service."""
    service = get_service(service_id)
    service.enabled = False
    service.deleted = True
    service.deleted_at = datetime.utcnow()
    service.updated_at = datetime.utcnow()
    service.save()
    return service


def list_enabled_match_rules(team_id, route_id=None):
    """Return route-specific rules first, then team-level rules."""
    route_rules = []

    if route_id:
        route_rules = list(
            ServiceMatchRule
            .select(ServiceMatchRule, Service)
            .join(Service)
            .where(
                (ServiceMatchRule.team == team_id)
                & (ServiceMatchRule.route == route_id)
                & (ServiceMatchRule.enabled == True)
                & (ServiceMatchRule.deleted == False)
                & (Service.enabled == True)
                & (Service.deleted == False)
                & (Service.team == team_id)
            )
            .order_by(ServiceMatchRule.position.asc(), ServiceMatchRule.id.asc())
        )

    team_rules = list(
        ServiceMatchRule
        .select(ServiceMatchRule, Service)
        .join(Service)
        .where(
            (ServiceMatchRule.team == team_id)
            & (ServiceMatchRule.route.is_null(True))
            & (ServiceMatchRule.enabled == True)
            & (ServiceMatchRule.deleted == False)
            & (Service.enabled == True)
            & (Service.deleted == False)
            & (Service.team == team_id)
        )
        .order_by(ServiceMatchRule.position.asc(), ServiceMatchRule.id.asc())
    )

    return route_rules + team_rules


def list_match_rules(service_id=None, team_id=None, route_id=None):
    """Return service match rules."""
    query = (
        ServiceMatchRule
        .select(ServiceMatchRule, Service)
        .join(Service)
        .where(ServiceMatchRule.deleted == False)
    )

    if service_id:
        query = query.where(ServiceMatchRule.service == service_id)

    if team_id:
        query = query.where(ServiceMatchRule.team == team_id)

    if route_id is not None:
        if route_id:
            query = query.where(ServiceMatchRule.route == route_id)
        else:
            query = query.where(ServiceMatchRule.route.is_null(True))

    return list(query.order_by(ServiceMatchRule.position.asc(), ServiceMatchRule.id.asc()))


def get_match_rule(rule_id):
    """Return one service match rule."""
    return (
        ServiceMatchRule
        .select(ServiceMatchRule, Service)
        .join(Service)
        .where(
            (ServiceMatchRule.id == rule_id)
            & (ServiceMatchRule.deleted == False)
        )
        .get()
    )


def create_match_rule(data):
    """Create a service match rule."""
    data["updated_at"] = datetime.utcnow()
    return ServiceMatchRule.create(**data)


def update_match_rule(rule_id, data):
    """Update a service match rule."""
    rule = get_match_rule(rule_id)

    for field, value in data.items():
        setattr(rule, field, value)

    rule.updated_at = datetime.utcnow()
    rule.save()

    return rule


def soft_delete_match_rule(rule_id):
    """Soft-delete a service match rule."""
    rule = get_match_rule(rule_id)
    rule.enabled = False
    rule.deleted = True
    rule.deleted_at = datetime.utcnow()
    rule.updated_at = datetime.utcnow()
    rule.save()
    return rule


def list_service_links(service_id=None, service_ids=None):
    """Return service links."""
    query = (
        ServiceLink
        .select(ServiceLink, Service, Team)
        .join(Service)
        .switch(Service)
        .join(Team)
        .where(ServiceLink.deleted == False)
    )

    if service_id is not None:
        query = query.where(ServiceLink.service == service_id)

    if service_ids is not None:
        service_ids = list(service_ids)
        if not service_ids:
            return []
        query = query.where(ServiceLink.service.in_(service_ids))

    return list(
        query.order_by(
            ServiceLink.priority.asc(),
            ServiceLink.id.asc(),
        )
    )


def list_service_runbooks(service_id=None, service_ids=None):
    """Return service runbooks."""
    query = (
        ServiceRunbook
        .select(ServiceRunbook, Service, Team)
        .join(Service)
        .switch(Service)
        .join(Team)
        .where(ServiceRunbook.deleted == False)
    )

    if service_id is not None:
        query = query.where(ServiceRunbook.service == service_id)

    if service_ids is not None:
        service_ids = list(service_ids)
        if not service_ids:
            return []
        query = query.where(ServiceRunbook.service.in_(service_ids))

    return list(
        query.order_by(
            ServiceRunbook.priority.asc(),
            ServiceRunbook.id.asc(),
        )
    )


def list_service_dependencies(service_id=None, service_ids=None):
    """Return service dependencies."""
    query = (
        ServiceDependency
        .select()
        .where(ServiceDependency.deleted == False)
    )

    if service_id is not None:
        query = query.where(ServiceDependency.service == service_id)

    if service_ids is not None:
        service_ids = list(service_ids)
        if not service_ids:
            return []
        query = query.where(ServiceDependency.service.in_(service_ids))

    return list(
        query.order_by(
            ServiceDependency.criticality.asc(),
            ServiceDependency.id.asc(),
        )
    )


def get_service_link(link_id):
    """Return one service link."""
    return (
        ServiceLink
        .select(ServiceLink, Service)
        .join(Service)
        .where(
            (ServiceLink.id == link_id)
            & (ServiceLink.deleted == False)
        )
        .get()
    )


def create_service_link(service_id, data):
    """Create a service link."""
    data["service"] = service_id
    data["updated_at"] = datetime.utcnow()
    return ServiceLink.create(**data)


def update_service_link(link_id, data):
    """Update a service link."""
    link = get_service_link(link_id)

    for field, value in data.items():
        setattr(link, field, value)

    link.updated_at = datetime.utcnow()
    link.save()

    return link


def soft_delete_service_link(link_id):
    """Soft-delete a service link."""
    link = get_service_link(link_id)
    link.enabled = False
    link.deleted = True
    link.deleted_at = datetime.utcnow()
    link.updated_at = datetime.utcnow()
    link.save()
    return link


def get_service_runbook(runbook_id):
    """Return one service runbook."""
    return (
        ServiceRunbook
        .select(ServiceRunbook, Service)
        .join(Service)
        .where(
            (ServiceRunbook.id == runbook_id)
            & (ServiceRunbook.deleted == False)
        )
        .get()
    )


def create_service_runbook(service_id, data):
    """Create a service runbook."""
    data["service"] = service_id
    data["updated_at"] = datetime.utcnow()
    return ServiceRunbook.create(**data)


def update_service_runbook(runbook_id, data):
    """Update a service runbook."""
    runbook = get_service_runbook(runbook_id)

    for field, value in data.items():
        setattr(runbook, field, value)

    runbook.updated_at = datetime.utcnow()
    runbook.save()

    return runbook


def soft_delete_service_runbook(runbook_id):
    """Soft-delete a service runbook."""
    runbook = get_service_runbook(runbook_id)
    runbook.enabled = False
    runbook.deleted = True
    runbook.deleted_at = datetime.utcnow()
    runbook.updated_at = datetime.utcnow()
    runbook.save()
    return runbook


def get_service_dependency(dependency_id):
    """Return one service dependency."""
    return (
        ServiceDependency
        .select()
        .where(
            (ServiceDependency.id == dependency_id)
            & (ServiceDependency.deleted == False)
        )
        .get()
    )


def create_service_dependency(service_id, data):
    """Create a service dependency."""
    data["service"] = service_id
    data["updated_at"] = datetime.utcnow()
    return ServiceDependency.create(**data)


def update_service_dependency(dependency_id, data):
    """Update a service dependency."""
    dependency = get_service_dependency(dependency_id)

    for field, value in data.items():
        setattr(dependency, field, value)

    dependency.updated_at = datetime.utcnow()
    dependency.save()

    return dependency


def soft_delete_service_dependency(dependency_id):
    """Soft-delete a service dependency."""
    dependency = get_service_dependency(dependency_id)
    dependency.enabled = False
    dependency.deleted = True
    dependency.deleted_at = datetime.utcnow()
    dependency.updated_at = datetime.utcnow()
    dependency.save()
    return dependency


def list_downstream_service_dependencies(service_id=None, service_ids=None):
    """Return dependencies where selected services are upstream targets."""
    query = (
        ServiceDependency
        .select()
        .where(ServiceDependency.deleted == False)  # noqa: E712
    )

    if service_id is not None:
        query = query.where(ServiceDependency.depends_on_service == service_id)

    if service_ids is not None:
        service_ids = list(service_ids)

        if not service_ids:
            return []

        query = query.where(ServiceDependency.depends_on_service.in_(service_ids))

    return list(
        query.order_by(
            ServiceDependency.criticality.asc(),
            ServiceDependency.id.asc(),
        )
    )


def list_service_status_history(service_id, *, limit=20):
    """Return recent service status changes."""
    return list(
        ServiceStatusHistory
        .select()
        .where(ServiceStatusHistory.service == service_id)
        .order_by(ServiceStatusHistory.created_at.desc(), ServiceStatusHistory.id.desc())
        .limit(limit)
    )


def list_service_owners(service_id, active_only=True):
    """Return service owners for a service."""
    query = (
        ServiceOwner
        .select(ServiceOwner, User)
        .join(User)
        .where(ServiceOwner.service == service_id)
        .order_by(ServiceOwner.role, User.username, ServiceOwner.id)
    )

    if active_only:
        query = query.where(ServiceOwner.active == True)  # noqa: E712

    return list(query)


def get_service_owner(owner_id):
    """Return one service owner."""
    return ServiceOwner.get_by_id(owner_id)


def get_service_owner_for_service(service_id, owner_id):
    """Return one service owner belonging to a service."""
    return ServiceOwner.get_or_none(
        ServiceOwner.id == owner_id,
        ServiceOwner.service == service_id,
    )


def find_service_owner(service_id, user_id, role):
    """Return existing service owner for user/role."""
    return ServiceOwner.get_or_none(
        ServiceOwner.service == service_id,
        ServiceOwner.user == user_id,
        ServiceOwner.role == role,
    )


def create_service_owner(service_id, data):
    """Create or reactivate a service owner."""
    User.get_by_id(data["user"])

    existing = find_service_owner(
        service_id,
        data["user"],
        data.get("role") or "owner",
    )

    if existing:
        existing.active = data.get("active", True)
        existing.notify_on_created = data.get("notify_on_created", True)
        existing.notify_on_priority_change = data.get(
            "notify_on_priority_change",
            True,
        )
        existing.notify_on_status_change = data.get(
            "notify_on_status_change",
            True,
        )
        existing.notify_on_resolved = data.get("notify_on_resolved", True)
        existing.save()

        return existing, False

    owner = ServiceOwner.create(
        service=service_id,
        user=data["user"],
        role=data.get("role") or "owner",
        active=data.get("active", True),
        notify_on_created=data.get("notify_on_created", True),
        notify_on_priority_change=data.get("notify_on_priority_change", True),
        notify_on_status_change=data.get("notify_on_status_change", True),
        notify_on_resolved=data.get("notify_on_resolved", True),
        notify_on_comment=data.get("notify_on_comment", True),
    )

    return owner, True


def update_service_owner(owner_id, data):
    """Update a service owner."""
    owner = get_service_owner(owner_id)

    User.get_by_id(data["user"])

    owner.user = data["user"]
    owner.role = data.get("role") or "owner"
    owner.active = data.get("active", True)
    owner.notify_on_created = data.get("notify_on_created", True)
    owner.notify_on_priority_change = data.get(
        "notify_on_priority_change",
        True,
    )
    owner.notify_on_status_change = data.get(
        "notify_on_status_change",
        True,
    )
    owner.notify_on_resolved = data.get("notify_on_resolved", True)
    if "notify_on_comment" in data:
        owner.notify_on_comment = bool(data.get("notify_on_comment"))
    owner.save()

    return owner


def deactivate_service_owner(owner_id):
    """Deactivate a service owner."""
    owner = get_service_owner(owner_id)
    owner.active = False
    owner.save()

    return owner
