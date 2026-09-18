"""Persistence helpers for first-class Incident records."""

from __future__ import annotations

from app.db import database_proxy as db
from app.modules.common import utc_now
from app.modules.db.models import AlertGroup, Incident, IncidentAlertGroupLink, IncidentEvent


class IncidentConflictError(RuntimeError):
    """Raised when an optimistic-concurrency update loses a race."""


def _select_for_update_if_supported(query):
    database = getattr(db, "obj", None)
    if database is not None and database.__class__.__name__ != "SqliteDatabase":
        return query.for_update()
    return query


def lock_incident(incident_id: int) -> Incident | None:
    return _select_for_update_if_supported(
        Incident.select().where(Incident.id == int(incident_id))
    ).first()


def lock_alert_group(alert_group_id: int) -> AlertGroup | None:
    return _select_for_update_if_supported(
        AlertGroup.select().where(AlertGroup.id == int(alert_group_id))
    ).first()


def get_incident(incident_id: int) -> Incident | None:
    return Incident.get_or_none(Incident.id == int(incident_id))


def list_incidents(*, team_ids=None, statuses=None):
    query = Incident.select().order_by(Incident.updated_at.desc(), Incident.id.desc())
    if team_ids is not None:
        ids = [int(value) for value in team_ids]
        if not ids:
            return []
        query = query.where(Incident.team.in_(ids))
    if statuses:
        query = query.where(Incident.workflow_status.in_(tuple(statuses)))
    return list(query)


def create_incident(**values) -> Incident:
    return Incident.create(**values)


def compare_and_swap(incident_id: int, expected_version: int, **changes) -> Incident:
    """Atomically update an Incident only when row_version still matches."""
    expected_version = int(expected_version)
    changes = dict(changes)
    changes["updated_at"] = utc_now()
    changes["row_version"] = Incident.row_version + 1
    updated = (
        Incident.update(**changes)
        .where(
            Incident.id == int(incident_id),
            Incident.row_version == expected_version,
        )
        .execute()
    )
    if updated != 1:
        raise IncidentConflictError("incident was modified by another request")
    return Incident.get_by_id(int(incident_id))


def active_link_for_group(alert_group_id: int):
    return (
        IncidentAlertGroupLink.select(IncidentAlertGroupLink, Incident)
        .join(Incident)
        .where(
            IncidentAlertGroupLink.alert_group == int(alert_group_id),
            IncidentAlertGroupLink.removed_at.is_null(True),
            ~Incident.workflow_status.in_(("closed", "cancelled")),
        )
        .order_by(IncidentAlertGroupLink.id.desc())
        .first()
    )


def active_primary_link(incident_id: int):
    return (
        IncidentAlertGroupLink.select()
        .where(
            IncidentAlertGroupLink.incident == int(incident_id),
            IncidentAlertGroupLink.relation_type == "primary",
            IncidentAlertGroupLink.removed_at.is_null(True),
        )
        .order_by(IncidentAlertGroupLink.id.desc())
        .first()
    )


def active_link(incident_id: int, alert_group_id: int):
    return (
        IncidentAlertGroupLink.select()
        .where(
            IncidentAlertGroupLink.incident == int(incident_id),
            IncidentAlertGroupLink.alert_group == int(alert_group_id),
            IncidentAlertGroupLink.removed_at.is_null(True),
        )
        .order_by(IncidentAlertGroupLink.id.desc())
        .first()
    )


def create_link(**values) -> IncidentAlertGroupLink:
    return IncidentAlertGroupLink.create(**values)


def remove_link(link_id: int, *, user_id=None, removed_at=None) -> IncidentAlertGroupLink:
    removed_at = removed_at or utc_now()
    (
        IncidentAlertGroupLink.update(removed_by=user_id, removed_at=removed_at)
        .where(
            IncidentAlertGroupLink.id == int(link_id),
            IncidentAlertGroupLink.removed_at.is_null(True),
        )
        .execute()
    )
    return IncidentAlertGroupLink.get_by_id(int(link_id))


def create_event(incident_id: int, event_type: str, *, user_id=None, message=None, data=None):
    return IncidentEvent.create(
        incident=int(incident_id),
        event_type=event_type,
        user=user_id,
        message=message,
        data=data or {},
    )


def list_active_links(incident_id: int):
    return list(
        IncidentAlertGroupLink.select(IncidentAlertGroupLink, AlertGroup)
        .join(AlertGroup)
        .where(
            IncidentAlertGroupLink.incident == int(incident_id),
            IncidentAlertGroupLink.removed_at.is_null(True),
        )
        .order_by(IncidentAlertGroupLink.id.asc())
    )


def list_events(incident_id: int, *, limit: int = 200):
    limit = max(1, min(int(limit), 500))
    return list(
        IncidentEvent.select()
        .where(IncidentEvent.incident == int(incident_id))
        .order_by(IncidentEvent.created_at.desc(), IncidentEvent.id.desc())
        .limit(limit)
    )
