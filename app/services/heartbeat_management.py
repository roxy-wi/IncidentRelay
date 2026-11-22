"""Heartbeat deletion, including termination of its alert lifecycles.

This service owns the operation and its transaction; repositories must not
import it. HTTP, worker and import callers use these entry points.
"""

from app.modules.common import utc_now
from app.modules.db import incident_core_repo
from app.modules.db.models import HeartbeatInstance


def soft_delete_heartbeat(heartbeat):
    """Soft-delete a heartbeat and terminate its current runtime state."""
    from app.services.alerts.resource_deletion import resolve_alert_groups_by_ids

    with incident_core_repo.write_transaction():
        now = utc_now()
        group_ids = {getattr(heartbeat, "current_alert_group_id", None)}
        group_ids.update(
            row.current_alert_group_id
            for row in HeartbeatInstance.select(
                HeartbeatInstance.current_alert_group
            ).where(HeartbeatInstance.heartbeat == heartbeat.id)
            if row.current_alert_group_id
        )
        resolve_alert_groups_by_ids(
            group_ids,
            now=now,
            reason="heartbeat_deleted",
        )
        # Instances are mutable scheduler state. Ping history remains preserved.
        HeartbeatInstance.delete().where(
            HeartbeatInstance.heartbeat == heartbeat.id
        ).execute()

        heartbeat.deleted = True
        heartbeat.deleted_at = now
        heartbeat.enabled = False
        heartbeat.status = "paused"
        heartbeat.next_expected_at = None
        heartbeat.overdue_since = None
        heartbeat.current_alert_group = None
        heartbeat.updated_at = now
        heartbeat.save()
        return heartbeat
