from datetime import datetime

from app.modules.common import utc_now
from app.modules.db import alerts_repo, maintenance_repo
from app.modules.db.models import Alert, AlertGroup
from app.services import escalation_policies as escalation_policy_service

SUPPRESS_NOTIFICATIONS_BEHAVIOR = "suppress_notifications"


def maintenance_create_kwargs(maintenance_decision) -> dict[str, object]:
    if not maintenance_decision or not maintenance_decision.window:
        return {}

    return {
        "maintenance_window": maintenance_decision.window,
        "maintenance_behavior": maintenance_decision.behavior,
        "maintenance_suppressed": maintenance_decision.suppress_notifications,
    }


def apply_maintenance_to_existing_alert(
    alert: Alert,
    maintenance_decision,
) -> None:
    if not maintenance_decision or not maintenance_decision.window:
        return

    alert.maintenance_window = maintenance_decision.window
    alert.maintenance_behavior = maintenance_decision.behavior
    alert.maintenance_suppressed = maintenance_decision.suppress_notifications


def is_notification_lifecycle_suppressed(
    group: AlertGroup,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether maintenance currently suppresses the group lifecycle."""
    if not group:
        return False

    window = getattr(group, "maintenance_window", None)
    behavior = (
        getattr(window, "behavior", None)
        or getattr(group, "maintenance_behavior", None)
    )

    if behavior != SUPPRESS_NOTIFICATIONS_BEHAVIOR:
        return False

    return maintenance_repo.is_window_active_now(window, now=now)


def pause_notification_lifecycle(group: AlertGroup) -> bool:
    """Cancel pending notifications and pause escalation for maintenance."""
    changed = False
    newly_suppressed = not bool(getattr(group, "maintenance_suppressed", False))

    if newly_suppressed:
        group.maintenance_suppressed = True
        changed = True

    if group.notification_pending or group.notification_due_at or group.notification_reason:
        group.notification_pending = False
        group.notification_due_at = None
        group.notification_reason = None
        changed = True

    if group.next_escalation_at is not None:
        group.next_escalation_at = None
        changed = True

    if changed:
        group.updated_at = utc_now()
        group.save()

    if newly_suppressed:
        window = getattr(group, "maintenance_window", None)
        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type="maintenance_notifications_paused",
            message=(
                "Notification, reminder, and escalation processing paused by "
                f"maintenance window: {getattr(window, 'name', 'Maintenance')}"
            ),
        )

    return changed


def resume_notification_lifecycle(
    group: AlertGroup,
    *,
    now: datetime | None = None,
) -> bool:
    """Release an expired maintenance suppression without replaying missed work."""
    if not group or not bool(getattr(group, "maintenance_suppressed", False)):
        return False

    if is_notification_lifecycle_suppressed(group, now=now):
        return False

    now = now or utc_now()

    if (
        group.status == "firing"
        and group.escalation_policy_id
        and group.escalation_rule_id
    ):
        next_escalation_at = escalation_policy_service.get_next_escalation_at(
            group.escalation_rule,
            now,
        )
    else:
        next_escalation_at = None

    updated = (
        AlertGroup
        .update(
            maintenance_suppressed=False,
            reminder_count=0,
            next_escalation_at=next_escalation_at,
            updated_at=now,
        )
        .where(
            AlertGroup.id == group.id,
            AlertGroup.maintenance_suppressed == True,  # noqa: E712
        )
        .execute()
    )

    if not updated:
        return False

    group.maintenance_suppressed = False
    group.reminder_count = 0
    group.next_escalation_at = next_escalation_at
    group.updated_at = now

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type="maintenance_notifications_resumed",
        message="Maintenance ended; notification and escalation processing resumed",
    )

    return True


def maybe_apply_maintenance_to_group(group: AlertGroup, maintenance_decision) -> None:
    if not maintenance_decision or not maintenance_decision.window:
        return

    was_suppressed = bool(getattr(group, "maintenance_suppressed", False))

    group.maintenance_window = maintenance_decision.window
    group.maintenance_behavior = maintenance_decision.behavior
    group.maintenance_suppressed = maintenance_decision.suppress_notifications

    if maintenance_decision.suppress_notifications:
        group.notification_pending = False
        group.notification_due_at = None
        group.notification_reason = None
        group.next_escalation_at = None

    group.save()

    if maintenance_decision.suppress_notifications and not was_suppressed:
        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type="maintenance_notifications_paused",
            message=(
                "Notification, reminder, and escalation processing paused by "
                f"maintenance window: {maintenance_decision.window.name}"
            ),
        )


def record_maintenance_match(
    group: AlertGroup,
    maintenance_decision,
    *,
    alert_id: int | None = None,
) -> None:
    """Write timeline event when an alert/incident matched maintenance."""
    if not group or not maintenance_decision or not maintenance_decision.matched:
        return

    window = maintenance_decision.window

    alerts_repo.create_alert_event(
        alert_id=alert_id,
        group_id=group.id,
        event_type="maintenance_matched",
        message=(
            f"Matched maintenance window: {window.name}"
            if window
            else "Matched maintenance window"
        ),
    )
