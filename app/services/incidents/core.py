"""Core business rules for first-class operational Incidents."""

from __future__ import annotations

from app.db import database_proxy as db
from app.modules.common import utc_now
from app.modules.db import audit_repo, incident_core_repo, incidents_repo
from app.modules.db.models import AlertGroup, Incident, Service, Team, User, UserGroup
from app.modules.redaction import redact_secrets


VALID_STATUSES = {
    "declared",
    "investigating",
    "identified",
    "monitoring",
    "resolved",
    "closed",
    "cancelled",
}
TERMINAL_STATUSES = {"closed", "cancelled"}
STATUS_TRANSITIONS = {
    "declared": {"investigating", "cancelled"},
    "investigating": {"identified", "monitoring", "resolved", "cancelled"},
    "identified": {"investigating", "monitoring", "resolved", "cancelled"},
    "monitoring": {"investigating", "resolved", "cancelled"},
    "resolved": {"investigating", "closed"},
    "closed": {"investigating"},
    "cancelled": set(),
}
CORE_RELATION_TYPES = {"primary", "related"}


class IncidentValidationError(ValueError):
    pass


class IncidentConflictError(incident_core_repo.IncidentConflictError):
    pass


def _require_team(team_id) -> Team:
    team = Team.get_or_none(Team.id == int(team_id), Team.active == True, Team.deleted == False)  # noqa: E712
    if not team:
        raise IncidentValidationError("team_id points to missing or inactive team")
    return team


def _require_service(service_id, team: Team) -> Service | None:
    if service_id in (None, ""):
        return None
    service = Service.get_or_none(Service.id == int(service_id), Service.enabled == True, Service.deleted == False)  # noqa: E712
    if not service:
        raise IncidentValidationError("service_id points to missing or disabled service")
    if service.team_id != team.id:
        raise IncidentValidationError("service belongs to another team")
    return service


def _require_user_in_team_group(user_id, team: Team) -> User | None:
    if user_id in (None, ""):
        return None
    user = User.get_or_none(User.id == int(user_id), User.active == True, User.deleted == False)  # noqa: E712
    if not user:
        raise IncidentValidationError("assignee_id points to missing or inactive user")
    if team.group_id and not UserGroup.select().where(
        UserGroup.user == user.id,
        UserGroup.group == team.group_id,
        UserGroup.active == True,  # noqa: E712
    ).exists():
        raise IncidentValidationError("assignee is not a member of the incident group")
    return user


def _audit(action, incident: Incident, *, user_id=None, data=None):
    group_id = incident.team.group_id if incident.team_id and incident.team else None
    return audit_repo.create_audit_log(
        action=action,
        object_type="incident",
        object_id=incident.id,
        group_id=group_id,
        team_id=incident.team_id,
        user_id=user_id,
        data=redact_secrets(data or {}),
    )


def create_incident(*, team_id, title, user_id=None, service_id=None, priority_slug=None, assignee_id=None, description=None):
    team = _require_team(team_id)
    service = _require_service(service_id, team)
    assignee = _require_user_in_team_group(assignee_id, team)
    title = str(title or "").strip()
    if not title:
        raise IncidentValidationError("title is required")
    if len(title) > 255:
        raise IncidentValidationError("title must not exceed 255 characters")
    priority = incidents_repo.get_priority_by_slug(priority_slug) if priority_slug else incidents_repo.get_default_priority()
    if not priority:
        raise IncidentValidationError("priority is not available")
    now = utc_now()
    with db.atomic():
        incident = incident_core_repo.create_incident(
            team=team,
            service=service,
            priority=priority,
            assignee=assignee,
            workflow_status="declared",
            title=title,
            description=(str(description).strip() if description not in (None, "") else None),
            declared_by=user_id,
            declared_at=now,
            created_at=now,
            updated_at=now,
        )
        incident_core_repo.create_event(incident.id, "incident_declared", user_id=user_id, data={"status": "declared"})
        _audit("incident_declared", incident, user_id=user_id, data={"status": "declared"})
    return incident


def update_incident(incident_id, *, expected_version, user_id=None, title=None, description=None, service_id=None, priority_slug=None):
    incident = incident_core_repo.get_incident(incident_id)
    if not incident:
        raise IncidentValidationError("incident not found")
    team = _require_team(incident.team_id)
    changes = {}
    if title is not None:
        value = str(title).strip()
        if not value:
            raise IncidentValidationError("title is required")
        changes["title"] = value
    if description is not None:
        changes["description"] = str(description).strip() or None
    if service_id is not None:
        changes["service"] = _require_service(service_id, team)
    if priority_slug is not None:
        priority = incidents_repo.get_priority_by_slug(priority_slug)
        if not priority:
            raise IncidentValidationError("priority must be an enabled incident priority")
        changes["priority"] = priority
    if not changes:
        return incident
    try:
        with db.atomic():
            updated = incident_core_repo.compare_and_swap(incident.id, expected_version, **changes)
            incident_core_repo.create_event(updated.id, "incident_updated", user_id=user_id, data={"fields": sorted(changes)})
            _audit("incident_updated", updated, user_id=user_id, data={"fields": sorted(changes)})
        return updated
    except incident_core_repo.IncidentConflictError as exc:
        raise IncidentConflictError(str(exc)) from exc


def assign_incident(incident_id, *, assignee_id, expected_version, user_id=None):
    incident = incident_core_repo.get_incident(incident_id)
    if not incident:
        raise IncidentValidationError("incident not found")
    team = _require_team(incident.team_id)
    assignee = _require_user_in_team_group(assignee_id, team)
    old_assignee_id = incident.assignee_id
    try:
        with db.atomic():
            updated = incident_core_repo.compare_and_swap(incident.id, expected_version, assignee=assignee)
            data = {"from_user_id": old_assignee_id, "to_user_id": getattr(assignee, "id", None)}
            incident_core_repo.create_event(updated.id, "incident_assignee_changed", user_id=user_id, data=data)
            _audit("incident_assignee_changed", updated, user_id=user_id, data=data)
        return updated
    except incident_core_repo.IncidentConflictError as exc:
        raise IncidentConflictError(str(exc)) from exc


def transition_incident(incident_id, new_status, *, expected_version, user_id=None):
    incident = incident_core_repo.get_incident(incident_id)
    if not incident:
        raise IncidentValidationError("incident not found")
    new_status = str(new_status or "").strip().lower()
    if new_status not in VALID_STATUSES:
        raise IncidentValidationError("invalid incident workflow status")
    if new_status == incident.workflow_status:
        return incident
    if new_status not in STATUS_TRANSITIONS.get(incident.workflow_status, set()):
        raise IncidentValidationError(f"cannot change incident status from {incident.workflow_status} to {new_status}")
    now = utc_now()
    changes = {"workflow_status": new_status}
    if new_status == "investigating" and not incident.investigation_started_at:
        changes["investigation_started_at"] = now
    if new_status == "identified" and not incident.identified_at:
        changes["identified_at"] = now
    if new_status == "monitoring":
        changes["monitoring_at"] = now
    if new_status == "resolved":
        changes["resolved_at"] = now
    elif incident.workflow_status == "resolved" and new_status == "investigating":
        changes["resolved_at"] = None
    if new_status == "closed":
        changes.update(closed_at=now, closed_by=user_id)
    elif incident.workflow_status == "closed" and new_status == "investigating":
        changes.update(closed_at=None, closed_by=None, resolved_at=None)
    try:
        with db.atomic():
            updated = incident_core_repo.compare_and_swap(incident.id, expected_version, **changes)
            data = {"from": incident.workflow_status, "to": new_status}
            incident_core_repo.create_event(updated.id, "incident_status_changed", user_id=user_id, data=data)
            _audit("incident_status_changed", updated, user_id=user_id, data=data)
        return updated
    except incident_core_repo.IncidentConflictError as exc:
        raise IncidentConflictError(str(exc)) from exc


def link_alert_group(incident_id, alert_group_id, *, relation_type="related", user_id=None):
    incident = incident_core_repo.get_incident(incident_id)
    if not incident:
        raise IncidentValidationError("incident not found")
    if incident.workflow_status in TERMINAL_STATUSES:
        raise IncidentValidationError("cannot link alert groups to a terminal incident")
    relation_type = str(relation_type or "related").strip().lower()
    if relation_type not in CORE_RELATION_TYPES:
        raise IncidentValidationError("relation_type must be primary or related in IncidentRelay 2.3")
    alert_group = AlertGroup.get_or_none(AlertGroup.id == int(alert_group_id))
    if not alert_group:
        raise IncidentValidationError("alert group not found")
    if alert_group.team_id != incident.team_id:
        raise IncidentValidationError("alert group belongs to another team")
    with db.atomic():
        # Lock both rows on PostgreSQL so concurrent workers cannot create
        # two active links for the same AlertGroup or two primary links.
        locked_incident = incident_core_repo.lock_incident(incident.id)
        locked_group = incident_core_repo.lock_alert_group(alert_group.id)
        if not locked_incident or not locked_group:
            raise IncidentValidationError("incident or alert group disappeared during linking")
        existing = incident_core_repo.active_link(incident.id, alert_group.id)
        if existing:
            return existing
        conflicting = incident_core_repo.active_link_for_group(alert_group.id)
        if conflicting and conflicting.incident_id != incident.id:
            raise IncidentConflictError("alert group is already linked to another open incident")
        if relation_type == "primary" and incident_core_repo.active_primary_link(incident.id):
            raise IncidentConflictError("incident already has an active primary alert group")
        link = incident_core_repo.create_link(
            incident=incident,
            alert_group=alert_group,
            relation_type=relation_type,
            linked_by=user_id,
        )
        data = {"alert_group_id": alert_group.id, "relation_type": relation_type}
        incident_core_repo.create_event(incident.id, "incident_group_linked", user_id=user_id, data=data)
        _audit("incident_group_linked", incident, user_id=user_id, data=data)
    return link


def unlink_alert_group(incident_id, alert_group_id, *, user_id=None):
    incident = incident_core_repo.get_incident(incident_id)
    if not incident:
        raise IncidentValidationError("incident not found")
    with db.atomic():
        link = incident_core_repo.active_link(incident.id, alert_group_id)
        if not link:
            return None
        removed = incident_core_repo.remove_link(link.id, user_id=user_id)
        data = {"alert_group_id": int(alert_group_id), "relation_type": link.relation_type}
        incident_core_repo.create_event(incident.id, "incident_group_unlinked", user_id=user_id, data=data)
        _audit("incident_group_unlinked", incident, user_id=user_id, data=data)
    return removed


def create_incident_from_alert_group(
    alert_group_id,
    *,
    user_id=None,
    title=None,
    description=None,
    priority_slug=None,
    assignee_id=None,
):
    """Create a first-class Incident and primary-link one AlertGroup atomically."""
    group = AlertGroup.get_or_none(AlertGroup.id == int(alert_group_id))
    if not group:
        raise IncidentValidationError("alert group not found")
    if not group.team_id:
        raise IncidentValidationError("alert group has no owning team")
    effective_priority = priority_slug or getattr(group, "priority_slug", None)
    with db.atomic():
        incident = create_incident(
            team_id=group.team_id,
            service_id=group.service_id,
            title=(title or group.title),
            description=description,
            priority_slug=effective_priority,
            assignee_id=assignee_id,
            user_id=user_id,
        )
        link_alert_group(
            incident.id,
            group.id,
            relation_type="primary",
            user_id=user_id,
        )
    return incident
