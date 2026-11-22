"""AlertGroup state transitions, episode lifecycle and business metrics.

This service owns the operation and its transaction; repositories must not
import it. HTTP, worker and import callers use these entry points.
"""

from app.modules.common import utc_now
from app.modules.db import alert_episodes_repo, alerts_repo, incident_core_repo
from app.modules.db.models import (
    Alert,
    AlertGroup,
    AlertGroupMerge,
    AlertGroupShelve,
)
from app.services.metrics import record_alert_group_action
from app.services.alerts import episodes


def create_alert_group(**kwargs):
    """Create alert group."""

    with incident_core_repo.write_transaction():
        group_key = kwargs.get("group_key") or ""
        kwargs["group_key_hash"] = alerts_repo.hash_group_key(group_key)
        group = AlertGroup.create(**kwargs)
        episodes.open_episode(group, started_at=group.first_seen_at)
        # Single hook point for group creation, whatever path created the
        # group: integration intake, manual creation, scheduler-side intakes.
        record_alert_group_action("created")
        return group


def recalculate_alert_group(group, *, event=None):
    """Recalculate persisted state while serializing with lifecycle writers."""
    with incident_core_repo.write_transaction():
        locked = incident_core_repo.lock_alert_group(group.id)
        if locked is None:
            raise AlertGroup.DoesNotExist()
        return _recalculate_alert_group(locked, event=event)


def _recalculate_alert_group(group, *, event=None):
    """Recalculate alert group counters, labels and effective status."""

    if group.merged_into_id or group.status == "merged":
        return group
    now = utc_now()

    alerts = list(
        Alert.select()
        .where(Alert.group == group.id)
        .order_by(Alert.last_seen_at.desc(), Alert.id.desc())
    )

    total = len(alerts)

    firing_count = sum(1 for alert in alerts if alert.status == "firing")
    acknowledged_count = sum(1 for alert in alerts if alert.status == "acknowledged")
    resolved_count = sum(1 for alert in alerts if alert.status == "resolved")
    silenced_count = sum(1 for alert in alerts if alert.status == "silenced")

    previous_status = group.status

    group.alert_count = total
    group.firing_count = firing_count
    group.acknowledged_count = acknowledged_count
    group.resolved_count = resolved_count
    group.silenced_count = silenced_count
    group.silenced = total > 0 and silenced_count == total

    if alerts:
        newest_alert = alerts[0]

        group.title = newest_alert.title
        group.message = newest_alert.message
        group.severity = newest_alert.severity
        group.last_seen_at = newest_alert.last_seen_at or now

        if not group.first_seen_at:
            group.first_seen_at = min(
                alert.first_seen_at for alert in alerts if alert.first_seen_at
            )

        common_labels, label_values = alerts_repo._collect_group_labels(alerts)

        group.common_labels = common_labels
        group.label_values = label_values
        group.payload_summary = {
            "latest_alert_id": newest_alert.id,
            "latest_dedup_key": newest_alert.dedup_key,
            "latest_external_id": newest_alert.external_id,
            "latest_payload": newest_alert.payload or {},
        }

    if total == 0:
        pass

    elif resolved_count == total:
        group.status = "resolved"

        if not group.resolved_at:
            group.resolved_at = now

        alerts_without_resolved_at = [
            alert for alert in alerts if not alert.resolved_at
        ]

        for alert in alerts_without_resolved_at:
            alert.resolved_at = now
            alert.updated_at = now
            alert.save()

    elif firing_count > 0:
        if group.status == "acknowledged":
            group.status = "acknowledged"
        else:
            group.status = "firing"
            group.resolved_at = None
            group.resolved_by = None

    elif silenced_count > 0:
        group.status = "silenced"
        group.resolved_at = None
        group.resolved_by = None

    elif acknowledged_count > 0:
        group.status = "acknowledged"
        group.resolved_at = None
        group.resolved_by = None

    else:
        group.status = previous_status

    if previous_status != group.status:
        group.previous_status = previous_status

    group.updated_at = now
    group.save(only=group.dirty_fields)
    episodes.refresh_context(group, alerts=alerts)
    if group.status == "resolved":
        episodes.close_episode(
            group,
            state="resolved",
            ended_at=group.resolved_at,
            event=event,
        )
    elif previous_status == "resolved":
        episodes.open_episode(
            group,
            started_at=now,
        )

    return group


def acknowledge_alert_group(group_id, user_id=None):
    """Acknowledge alert group."""

    with incident_core_repo.write_transaction():
        group = incident_core_repo.lock_alert_group(group_id)
        if group is None:
            raise AlertGroup.DoesNotExist()
        if (
            group.status in alert_episodes_repo.TERMINAL_STATUSES
            or group.merged_into_id
        ):
            return group
        group.previous_status = group.status
        group.status = "acknowledged"
        group.acknowledged_by = user_id
        group.acknowledged_at = utc_now()
        group.save()
        record_alert_group_action("acknowledged")
        return group


def resolve_alert_group(group_id, user_id=None, *, event=None):
    """Resolve alert group and all child alerts."""

    with incident_core_repo.write_transaction():
        group = incident_core_repo.lock_alert_group(group_id)
        if group is None:
            raise AlertGroup.DoesNotExist()
        if (
            group.status in alert_episodes_repo.TERMINAL_STATUSES
            or group.merged_into_id
        ):
            return group

        now = utc_now()
        (
            Alert.update(status="resolved", resolved_at=now)
            .where((Alert.group == group.id) & (Alert.status != "resolved"))
            .execute()
        )

        group.previous_status = group.status
        group.status = "resolved"
        group.resolved_by = user_id
        group.resolved_at = now
        group.firing_count = 0
        group.acknowledged_count = 0
        group.resolved_count = Alert.select().where(Alert.group == group.id).count()
        group.updated_at = now
        group.save()
        episodes.close_episode(
            group,
            state="resolved",
            ended_at=now,
            event=event,
        )
        record_alert_group_action("resolved")
        return group


def merge_alert_groups(target_group_id, source_group_ids, user_id=None, reason=None):
    """Merge source groups into target group."""

    with incident_core_repo.write_transaction():
        ids = sorted(
            {int(target_group_id), *(int(value) for value in source_group_ids)}
        )
        locked = {
            group_id: incident_core_repo.lock_alert_group(group_id) for group_id in ids
        }
        if any(group is None for group in locked.values()):
            raise AlertGroup.DoesNotExist()
        target = locked[int(target_group_id)]
        if target.merged_into_id or target.status == "merged":
            raise alerts_repo.AlertGroupMergeConflict(
                "Cannot merge into an already merged group."
            )
        now = utc_now()

        for source_id in sorted(set(map(int, source_group_ids))):
            if int(source_id) == int(target_group_id):
                continue

            source = locked[source_id]
            if source.merged_into_id:
                continue

            (
                Alert.update(group=target.id, group_key=target.group_key)
                .where(Alert.group == source.id)
                .execute()
            )

            source.previous_status = source.status
            source.status = "merged"
            source.merged_into = target.id
            source.merged_by = user_id
            source.merged_at = now
            source.merge_reason = reason
            source.updated_at = now
            source.save()

            (
                AlertGroupShelve.update(
                    active=False,
                    unshelved_at=now,
                    unshelved_by=user_id,
                    unshelve_reason="alert_group_merged",
                    updated_at=now,
                )
                .where(
                    (AlertGroupShelve.alert_group == source.id)
                    & (AlertGroupShelve.active == True)  # noqa: E712
                )
                .execute()
            )

            AlertGroupMerge.create(
                source_group=source.id,
                target_group=target.id,
                merged_by=user_id,
                reason=reason,
            )

            event = alerts_repo.create_alert_event(
                group_id=source.id,
                event_type="merged",
                message=f"Merged into group #{target.id}",
                user_id=user_id,
            )

            episodes.close_episode(
                source,
                state="merged",
                ended_at=now,
                event=event,
            )

        target = recalculate_alert_group(target)

        alerts_repo.create_alert_event(
            group_id=target.id,
            event_type="merge_target_updated",
            message="Alert groups merged into this group",
            user_id=user_id,
        )

        return target
