import logging
from datetime import timedelta

from app import Config
from app.db import database_proxy as db
from app.modules.db.models import AlertGroup, RecoveryNotificationDelivery
from app.services.alerts.reopen import lock_grouping_identity
from app.modules.db import alerts_repo, notifications_repo
from app.services.notifications.delivery import notify_alert
from app.services.notifications.retries import delivery_attempt
from app.services.alerts.shelving import is_alert_group_shelved
from app.services.alerts.maintenance_state import (
    is_notification_lifecycle_suppressed,
    pause_notification_lifecycle,
    resume_notification_lifecycle,
)
from app.modules.common import utc_now

logger = logging.getLogger("oncall.alerts")

RECOVERY_NOTIFICATION_REASON = "recovery"
MAX_RECOVERY_DELAY_SECONDS = 86400


def recovery_notification_delay_seconds():
    """Opt-in recovery grace, independent of grouping reopen policy."""
    try:
        configured = int(getattr(Config, "RECOVERY_NOTIFICATION_DELAY_SECONDS", 0) or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(configured, MAX_RECOVERY_DELAY_SECONDS))


def schedule_recovery_notification(group, *, now=None):
    """Persist one delayed recovery after a real technical resolution.

    The conditional UPDATE cannot resurrect a group reopened by another intake
    or move an already queued recovery deadline after repeated resolved events.
    """
    delay = recovery_notification_delay_seconds()
    if not delay or group.status != "resolved" or not group.resolved_at:
        return False

    now = now or utc_now()
    due_at = now + timedelta(seconds=delay)

    updated = (
        AlertGroup
        .update(
            notification_pending=True,
            notification_due_at=due_at,
            notification_reason=RECOVERY_NOTIFICATION_REASON,
            updated_at=now,
        )
        .where(
            (AlertGroup.id == group.id)
            & (AlertGroup.status == "resolved")
            & (AlertGroup.resolved_at == group.resolved_at)
            & (AlertGroup.merged_into.is_null(True))
            & (
                (AlertGroup.notification_pending == False)  # noqa: E712
                | AlertGroup.notification_reason.is_null(True)
                | (AlertGroup.notification_reason != RECOVERY_NOTIFICATION_REASON)
            )
        )
        .execute()
    )
    if not updated:
        return False

    group.notification_pending = True
    group.notification_due_at = due_at
    group.notification_reason = RECOVERY_NOTIFICATION_REASON
    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type="recovery_notification_scheduled",
        message=(
            f"Recovery notification deferred for {delay}s "
            f"until {due_at.isoformat()} UTC"
        ),
    )
    return True


RECOVERY_MAX_ATTEMPTS = 5
RECOVERY_RETRY_BASE_SECONDS = 30
RECOVERY_RETRY_MAX_SECONDS = 3600


def _recovery_cycle_query(group):
    return RecoveryNotificationDelivery.select().where(
        (RecoveryNotificationDelivery.group == group.id)
        & (RecoveryNotificationDelivery.resolved_at == group.resolved_at)
    )


def _snapshot_recovery_targets(group, *, now):
    """Freeze delivery target identities once at first due time.

    All writes occur under the same grouping + AlertGroup lock as reopen.
    A retry must not pick up new recipients or requeue successful recipients.
    """
    if _recovery_cycle_query(group).exists():
        return

    targets = []
    if group.last_notification_at:
        targets.extend(
            ("channel", row.channel_id)
            for row in notifications_repo.list_notifications_for_group(group.id)
            if row.channel_id is not None
        )

    # Preserve the existing behavior: don't send a resolved user notification
    # if no firing notification was ever issued for this lifecycle cycle.
    if group.last_notification_at and group.assignee_id:
        targets.append(("user_rules", group.assignee_id))

    for kind, recipient_id in sorted(set(targets)):
        RecoveryNotificationDelivery.create(
            group=group.id,
            resolved_at=group.resolved_at,
            target_kind=kind,
            target_id=recipient_id,
            next_attempt_at=now,
        )


def _deliver_recovery_target(group, delivery):
    """Return (status, successful sends) or raise on a retryable failure."""
    kind = delivery.target_kind

    if kind == "channel":
        report = notify_alert(
            group, event_type="resolved",
            channel_ids={delivery.target_id},
            enqueue_rules=False, report_channels=True,
        )
        outcome = report["channels"].get(delivery.target_id)
        if not outcome:
            return "skipped", 0
        if outcome["status"] == "failed":
            raise RuntimeError(outcome.get("error") or "provider delivery failed")
        if outcome["status"] == "skipped":
            return "skipped", 0
        return "sent", 1

    if kind == "user_rules":
        # The user notification subsystem has its own durable delivery rows.
        # Enqueue exactly once per recovery cycle, independently of retries to
        # shared channels and stakeholders.
        from app.services.notifications import rules
        if not group.assignee_id or group.assignee_id != delivery.target_id:
            return "skipped", 0
        return "sent", rules.enqueue_user_notifications(group, event_type="resolved")

    return "skipped", 0



def _try_recovery_target(group, delivery, *, now):
    """Persist each target's result before processing the next target."""
    values = delivery_attempt(
        lambda: _deliver_recovery_target(group, delivery),
        attempt=delivery.attempts + 1, now=now,
        max_attempts=RECOVERY_MAX_ATTEMPTS,
        base_seconds=RECOVERY_RETRY_BASE_SECONDS,
        max_seconds=RECOVERY_RETRY_MAX_SECONDS,
    )
    for name, value in values.items():
        setattr(delivery, name, value)
    if delivery.last_error is not None:
        if delivery.status == "failed":
            alerts_repo.create_alert_event(
                group_id=group.id,
                event_type="recovery_delivery_exhausted",
                message=(
                    f"Recovery delivery {delivery.target_kind}:{delivery.target_id} "
                    f"exhausted {delivery.attempts} attempts"
                ),
            )
        logger.warning(
            "recovery target delivery failed",
            extra={"extra": {
                "alert_group_id": group.id,
                "target_kind": delivery.target_kind,
                "target_id": delivery.target_id,
                "attempt": delivery.attempts,
                "error": delivery.last_error,
            }},
        )
    delivery.save()


def _process_due_recovery(selected_group, *, now):
    """Deliver due recovery recipients with durable individual retries.

    Grouping and row locks serialize delivery with opt-in reopen. External
    sends remain at-least-once around network/DB commit failures; no provider
    offers an atomic two-phase commit with our database.
    """
    database = db.obj
    transaction = (
        db.atomic(lock_type="IMMEDIATE")
        if database.__class__.__name__ == "SqliteDatabase"
        else db.atomic()
    )

    with transaction:
        lock_grouping_identity(
            source=selected_group.source,
            group_key=selected_group.group_key,
            team_id=selected_group.team_id,
            route_id=selected_group.route_id,
            service_id=selected_group.service_id,
        )
        query = AlertGroup.select().where(AlertGroup.id == selected_group.id)
        if database.__class__.__name__ != "SqliteDatabase":
            query = query.for_update()
        group = query.first()

        if (
            group is None
            or group.merged_into_id is not None
            or group.status != "resolved"
            or not group.notification_pending
            or group.notification_reason != RECOVERY_NOTIFICATION_REASON
            or group.notification_due_at is None
            or group.notification_due_at > now
            or group.notification_due_at != selected_group.notification_due_at
        ):
            return "skipped"

        _snapshot_recovery_targets(group, now=now)
        for delivery in _recovery_cycle_query(group).order_by(
            RecoveryNotificationDelivery.id.asc()
        ):
            if delivery.status == "pending" and delivery.next_attempt_at <= now:
                _try_recovery_target(group, delivery, now=now)

        deliveries = list(_recovery_cycle_query(group))
        pending = [row for row in deliveries if row.status == "pending"]
        if pending:
            next_due = min(row.next_attempt_at for row in pending)
            group.notification_due_at = next_due
            group.updated_at = now
            group.save(only=[AlertGroup.notification_due_at, AlertGroup.updated_at])
            alerts_repo.create_alert_event(
                group_id=group.id,
                event_type="recovery_notification_retry_scheduled",
                message=f"Recovery recipient retry scheduled for {next_due.isoformat()} UTC",
            )
            return "retrying"

        sent = sum(row.delivered_count for row in deliveries)
        failures = sum(row.status == "failed" for row in deliveries)
        skipped = sum(row.status == "skipped" for row in deliveries)
        alerts_repo.clear_alert_group_notification(group)
        if failures:
            event_type = (
                "recovery_notification_partial" if sent else "recovery_notification_failed"
            )
        else:
            event_type = "recovery_notification_sent" if sent else "recovery_notification_skipped"
        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type=event_type,
            message=(
                f"Delayed recovery completed: deliveries={sent}, "
                f"exhausted={failures}, skipped={skipped}"
            ),
        )
        if failures:
            return "partial" if sent else "failed"
        return "sent" if sent else "skipped"


def _alert_group_wait_seconds():
    return int(getattr(Config, "ALERT_GROUP_WAIT_SECONDS", 30) or 0)


def _alert_group_interval_seconds():
    return int(getattr(Config, "ALERT_GROUP_INTERVAL_SECONDS", 300) or 0)


def schedule_group_notification(group, reason="notification", now=None):
    """Schedule group notification according to group_wait/group_interval."""

    now = now or utc_now()

    if is_alert_group_shelved(group, now=now):
        alerts_repo.clear_alert_group_notification(group)
        if group.next_escalation_at is not None:
            group.next_escalation_at = None
            group.updated_at = now
            group.save(only=[AlertGroup.next_escalation_at, AlertGroup.updated_at])
        return group

    if is_notification_lifecycle_suppressed(group, now=now):
        pause_notification_lifecycle(group)
        return group

    resume_notification_lifecycle(group, now=now)

    if group.status != "firing":
        alerts_repo.clear_alert_group_notification(group)
        return group

    if not group.last_notification_at:
        due_at = now + timedelta(seconds=_alert_group_wait_seconds())
    else:
        next_allowed_at = (
            group.last_notification_at
            + timedelta(seconds=_alert_group_interval_seconds())
        )

        due_at = now if next_allowed_at <= now else next_allowed_at

    return alerts_repo.schedule_alert_group_notification(
        group,
        due_at=due_at,
        reason=reason,
    )


def process_due_alert_group_notifications(limit=100):
    """Send due alert group notifications."""

    now = utc_now()
    sent = 0
    skipped = 0
    failed = 0

    groups = alerts_repo.list_due_alert_group_notifications(
        now=now,
        limit=limit,
    )

    for selected_group in groups:
        group = selected_group

        try:
            if selected_group.notification_reason == RECOVERY_NOTIFICATION_REASON:
                outcome = _process_due_recovery(selected_group, now=now)
                if outcome == "sent":
                    sent += 1
                elif outcome in {"retrying", "failed", "partial"}:
                    failed += 1
                else:
                    skipped += 1
                continue

            # The due-list query can race with an ACK handled by another
            # worker. Reload before recalculation so a stale firing object does
            # not overwrite the persisted acknowledged state.
            group = alerts_repo.get_alert_group(selected_group.id)

            if (
                not group.notification_pending
                or group.status != "firing"
                or group.notification_due_at is None
                or group.notification_due_at > now
                or group.notification_due_at != selected_group.notification_due_at
                or group.notification_reason != selected_group.notification_reason
            ):
                if (
                    group.notification_pending
                    and group.status != "firing"
                    and group.notification_reason == selected_group.notification_reason
                    and group.notification_reason != RECOVERY_NOTIFICATION_REASON
                ):
                    alerts_repo.clear_alert_group_notification(group)
                skipped += 1
                continue

            group = alerts_repo.recalculate_alert_group(group)

            if is_alert_group_shelved(group, now=now):
                alerts_repo.clear_alert_group_notification(group)
                skipped += 1
                continue

            if is_notification_lifecycle_suppressed(group, now=now):
                pause_notification_lifecycle(group)
                skipped += 1
                continue

            resume_notification_lifecycle(group, now=now)

            if group.status != "firing":
                alerts_repo.clear_alert_group_notification(group)
                skipped += 1
                continue

            event_type = (
                "notification"
                if not group.last_notification_at
                else "update"
            )

            sent_count = notify_alert(group, event_type=event_type)

            if not sent_count:
                alerts_repo.clear_alert_group_notification(group)

                alerts_repo.create_alert_event(
                    group_id=group.id,
                    event_type=f"{event_type}_skipped",
                    message="Due alert group notification skipped: no delivery target",
                )

                skipped += 1
                continue

            alerts_repo.mark_alert_group_notification_sent(group, now=now)

            alerts_repo.create_alert_event(
                group_id=group.id,
                event_type=f"{event_type}_sent",
                message="Due alert group notification sent",
            )

            sent += 1

        except Exception as exc:
            failed += 1

            logger.exception(
                "failed to send due alert group notification",
                extra={
                    "extra": {
                        "alert_group_id": getattr(group, "id", None),
                        "error": str(exc),
                    }
                },
            )

    return {
        "processed": len(groups),
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
    }
