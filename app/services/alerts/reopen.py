"""Opt-in, concurrency-safe resolved AlertGroup reuse (IncidentRelay 2.4).

The caller must hold a database transaction; never call these helpers from
simulator/shadow-mode evaluation. Source/routing/grouping boundaries are strict
including NULL-valued services. Resolved child Alerts are immutable.
"""

from __future__ import annotations

from datetime import timedelta
import hashlib

from app.db import database_proxy as db
from app.modules.common import utc_now
from app.modules.db import (
    alert_episodes_repo,
    alerts_repo,
    audit_repo,
    incident_core_repo,
)
from app.modules.db.models import AlertGroup, AlertRoute, RecoveryNotificationDelivery
from app.services.notifications.rules import cancel_pending_group_deliveries



def _identity_filter(source, group_key, team_id, route_id, service_id):
    return (
        (AlertGroup.source == source)
        & (AlertGroup.group_key_hash == alerts_repo.hash_group_key(group_key))
        & (AlertGroup.team == team_id)
        & (AlertGroup.route == route_id)
        & (AlertGroup.service == service_id)
        & (AlertGroup.merged_into.is_null(True))
    )


def group_matches_identity(group, *, source, group_key, team_id, route_id, service_id):
    if not group or group.merged_into_id:
        return False
    return (
        group.source == source
        and group.group_key_hash == alerts_repo.hash_group_key(group_key)
        and group.team_id == team_id
        and group.route_id == route_id
        and group.service_id == service_id
    )


def lock_grouping_identity(*, source, group_key, team_id, route_id, service_id):
    """Serialize same-identity intake across Gunicorn/worker processes.

    PostgreSQL's transaction advisory lock needs no schema or persistent rows.
    SQLite's enclosing BEGIN IMMEDIATE serializes writers before the SELECT.
    """
    database = db.obj
    backend = database.__class__.__name__.lower()
    if "mysql" in backend:
        # MySQL has no transaction-scoped advisory locks. Lock the route row
        # through COMMIT; opted-in events on that route serialize safely.
        route = AlertRoute.select().where(AlertRoute.id == route_id).for_update().first()
        if route is None:
            raise RuntimeError("route disappeared while selecting an AlertGroup")
        return
    if "postgres" not in backend:
        return
    identity = "\0".join(str(value) for value in (
        "incidentrelay:reopen:v1", source, group_key,
        team_id, route_id, service_id,
    ))
    key = int.from_bytes(hashlib.sha256(identity.encode("utf-8")).digest()[:8], "big", signed=True)
    db.execute_sql("SELECT pg_advisory_xact_lock(%s)", (key,))


def find_exact_open_group(*, source, group_key, team_id, route_id, service_id):
    return (
        AlertGroup.select()
        .where(
            _identity_filter(source, group_key, team_id, route_id, service_id)
            & AlertGroup.status.not_in(("resolved", "merged"))
        )
        .order_by(AlertGroup.id.desc())
        .first()
    )


def find_resolved_reopen_candidate(
    *, source, group_key, team_id, route_id, service_id,
    now, reopen_window_seconds,
):
    if not reopen_window_seconds:
        return None
    cutoff = now - timedelta(seconds=reopen_window_seconds)
    return (
        AlertGroup.select()
        .where(
            _identity_filter(source, group_key, team_id, route_id, service_id)
            & (AlertGroup.status == "resolved")
            & (AlertGroup.resolved_at >= cutoff)
            & (AlertGroup.resolved_at <= now)
        )
        .order_by(AlertGroup.resolved_at.desc(), AlertGroup.id.desc())
        .first()
    )


def restart_resolved_group(
    group, *, now, policy, policy_rule, rotation, assignee,
    next_escalation_at,
):
    """Reset ONLY technical lifecycle state before inserting a NEW child.

    The caller must insert/recalculate the new occurrence before committing.
    """
    # Respect the lock order used by Incident linking: Incident before
    # AlertGroup. Otherwise concurrent linking can deadlock against reopen.
    linked = incident_core_repo.active_link_for_group(group.id)
    if linked is not None:
        incident_core_repo.lock_incident(linked.incident_id)
    group = incident_core_repo.lock_alert_group(group.id)
    if group is None or group.status != "resolved" or group.merged_into_id:
        raise RuntimeError("resolved AlertGroup changed while reopening")

    recovery_pending = bool(
        group.notification_pending
        and group.notification_reason == "recovery"
    )
    previous_resolved_at = group.resolved_at
    group.previous_status = "resolved"
    group.status = "firing"
    group.acknowledged_by = None
    group.acknowledged_at = None
    group.resolved_by = None
    group.resolved_at = None
    group.escalation_policy = policy
    group.escalation_rule = policy_rule
    group.rotation = rotation
    group.assignee = assignee
    group.next_escalation_at = next_escalation_at
    group.last_escalated_at = None
    group.escalation_level = 0
    group.escalation_repeat_count = 0
    group.reminder_count = 0
    group.last_notification_at = None
    group.notification_pending = False
    group.notification_due_at = None
    group.notification_reason = None
    group.updated_at = now
    group.save()
    alert_episodes_repo.open_episode(group, started_at=now)

    if recovery_pending:
        (
            RecoveryNotificationDelivery.update(
                status="cancelled", updated_at=now,
            )
            .where(
                (RecoveryNotificationDelivery.group == group.id)
                & (RecoveryNotificationDelivery.resolved_at == previous_resolved_at)
                & (RecoveryNotificationDelivery.status == "pending")
            )
            .execute()
        )
        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type="recovery_notification_cancelled",
            message="Pending recovery notification cancelled by AlertGroup reopen",
        )

    # Do not leak old-cycle reminders/resolve notifications into the new cycle.
    cancel_pending_group_deliveries(
        group, event_types={"notification", "reminder", "escalation", "resolved"},
        reason="alert_group_reopened",
    )
    return group


def _resume_linked_incident(group, alert, *, now):
    link = incident_core_repo.active_link_for_group(group.id)
    if link is None:
        return
    incident = incident_core_repo.lock_incident(link.incident_id)
    if incident is None or incident.workflow_status not in {"resolved", "monitoring"}:
        return
    old_status = incident.workflow_status
    changes = {"workflow_status": "investigating", "resolved_at": None}
    if incident.investigation_started_at is None:
        changes["investigation_started_at"] = now
    updated = incident_core_repo.compare_and_swap(
        incident.id, incident.row_version, **changes,
    )
    data = {
        "from": old_status,
        "to": "investigating",
        "alert_group_id": group.id,
        "new_alert_id": alert.id,
        "source": "alert_group_reopen",
    }
    incident_core_repo.create_event(
        updated.id, "incident_reopened_by_alert_group",
        message="Incident investigation resumed after a linked AlertGroup reopened",
        data=data,
    )
    group_id = updated.team.group_id if updated.team_id and updated.team else None
    audit_repo.create_audit_log(
        action="incident.reopen_by_alert_group",
        object_type="incident", object_id=updated.id,
        group_id=group_id, team_id=updated.team_id, data=data,
    )


def record_reopened_occurrence(group, alert):
    """Call in the same transaction, after the new child was persisted."""
    now = utc_now()
    event = alerts_repo.create_alert_event(
        group_id=group.id,
        alert_id=alert.id,
        event_type="reopened",
        message=f"Resolved AlertGroup reopened by new Alert #{alert.id}",
    )
    alert_episodes_repo.open_episode(group, event=event)
    audit_repo.create_audit_log(
        action="alert_group.reopen", object_type="alert_group",
        object_id=group.id,
        group_id=group.team.group_id if group.team_id and group.team else None,
        team_id=group.team_id,
        data={"alert_id": alert.id, "source": "integration", "previous_status": "resolved", "status": group.status},
    )
    _resume_linked_incident(group, alert, now=now)
