"""Close alert lifecycles when an owning operational resource is deleted.

This service owns the operation and its transaction; repositories must not
import it. HTTP, worker and import callers use these entry points.
"""

from app.modules.common import utc_now
from app.modules.db import alert_episodes_repo, incident_core_repo
from app.modules.db.models import (
    Alert,
    AlertEvent,
    AlertGroup,
)
from app.services.alerts import episodes


def resolve_alert_groups_by_ids(group_ids, *, now=None, reason="resource_deleted"):
    """Resolve groups, children, episodes and discovery work atomically."""
    group_ids = sorted({int(value) for value in group_ids or [] if value})
    if not group_ids:
        return 0
    now = now or utc_now()
    changed = 0
    with incident_core_repo.write_transaction():
        for group_id in group_ids:
            group = incident_core_repo.lock_alert_group(group_id)
            if (
                group is None
                or group.status in alert_episodes_repo.TERMINAL_STATUSES
                or group.merged_into_id
            ):
                continue
            # A newer cycle may have started while the group lock was pending.
            closed_at = max(now, utc_now())
            Alert.update(
                previous_status=Alert.status,
                status="resolved",
                resolved_at=closed_at,
                next_escalation_at=None,
            ).where(Alert.group == group.id, Alert.status != "resolved").execute()
            group.previous_status = group.status
            group.status = "resolved"
            group.resolved_at = closed_at
            group.next_escalation_at = None
            group.notification_due_at = None
            group.notification_pending = False
            group.notification_reason = reason
            group.firing_count = 0
            group.acknowledged_count = 0
            group.silenced_count = 0
            group.resolved_count = group.alert_count
            group.updated_at = closed_at
            group.save()
            event = AlertEvent.create(
                group=group.id,
                event_type="resolved",
                message=f"Alert group resolved: {reason}",
                created_at=closed_at,
            )
            episodes.close_episode(
                group,
                state="resolved",
                ended_at=closed_at,
                event=event,
            )
            changed += 1
    return changed


def resolve_team_runtime_alerts(team_id, *, now=None):
    """Terminate a deleted team's current cycles while preserving history."""
    now = now or utc_now()
    with incident_core_repo.write_transaction():
        group_ids = [
            group.id
            for group in AlertGroup.select(AlertGroup.id).where(
                AlertGroup.team == team_id
            )
        ]
        resolve_alert_groups_by_ids(group_ids, now=now, reason="team_deleted")
        # Legacy orphan children have no group/episode to close.
        Alert.update(
            previous_status=Alert.status,
            status="resolved",
            resolved_at=now,
            next_escalation_at=None,
        ).where(
            Alert.team == team_id, Alert.group.is_null(True), Alert.status != "resolved"
        ).execute()
