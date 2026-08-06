import logging
from datetime import datetime, timedelta

from app.modules.db import alerts_repo
from app.services import escalation_policies as escalation_policy_service
from app.services.notifications.delivery import has_matching_notification_channel, notify_alert
from app.services.alerts.maintenance_state import (
    is_escalation_lifecycle_paused,
    is_notification_lifecycle_suppressed,
    pause_notification_lifecycle,
    resume_notification_lifecycle,
)
from app.services.oncall import get_current_oncall_user, get_next_rotation_user
from app.modules.common import utc_now

logger = logging.getLogger("oncall.alerts")


def _deliver_escalation_notification(group):
    """Attempt escalation delivery without affecting the state transition."""
    has_target = False
    resolution_error = None

    try:
        has_target = has_matching_notification_channel(
            group,
            event_type="escalation",
        )
    except Exception as exc:
        resolution_error = exc
        logger.exception(
            "escalation notification target resolution failed",
            extra={
                "extra": {
                    "alert_group_id": group.id,
                    "route_id": group.route.id if group.route else None,
                }
            },
        )

    try:
        sent_count = notify_alert(group, event_type="escalation")
    except Exception as exc:
        sent_count = 0
        resolution_error = resolution_error or exc
        logger.exception(
            "escalation notification delivery failed",
            extra={
                "extra": {
                    "alert_group_id": group.id,
                    "route_id": group.route.id if group.route else None,
                }
            },
        )

    if sent_count:
        return sent_count

    if has_target or resolution_error is not None:
        event_type = "escalation_notification_failed"
        message = "Escalation completed, but notification delivery did not succeed."
    else:
        event_type = "escalation_notification_skipped"
        message = (
            "Escalation completed, but no matching notification target was found."
        )

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type=event_type,
        message=message,
    )

    return 0


def apply_initial_escalation_policy_assignment(
    policy,
    fallback_rotation,
    *,
    now: datetime | None = None,
):
    """Return initial policy rule, rotation, assignee and next escalation time."""
    policy_rule = None
    rotation = fallback_rotation
    assignee = get_current_oncall_user(rotation) if rotation else None
    next_escalation_at = None

    if not policy:
        return policy_rule, rotation, assignee, next_escalation_at

    policy_rule = escalation_policy_service.get_first_enabled_rule(policy)

    if not policy_rule:
        return policy_rule, rotation, assignee, next_escalation_at

    policy_target_user = escalation_policy_service.resolve_rule_user(policy_rule)

    if policy_rule.target_type == "rotation" and policy_rule.target_rotation:
        rotation = policy_rule.target_rotation
    else:
        rotation = None

    assignee = policy_target_user

    delay_seconds = escalation_policy_service.get_rule_delay_seconds(policy_rule)

    if delay_seconds:
        next_escalation_at = (now or utc_now()) + timedelta(seconds=delay_seconds)

    return policy_rule, rotation, assignee, next_escalation_at


def maybe_escalate_alert(group):
    """Escalate an alert group according to route escalation mode."""

    if is_notification_lifecycle_suppressed(group):
        pause_notification_lifecycle(group)
        return False

    if is_escalation_lifecycle_paused(group):
        group.next_escalation_at = None
        group.save(only=[group.__class__.next_escalation_at])
        return False

    if resume_notification_lifecycle(group):
        return False

    if group.escalation_policy_id:
        return maybe_escalate_alert_by_policy(group)

    if not group.team or not group.team.escalation_enabled:
        return False

    if group.reminder_count < group.team.escalation_after_reminders:
        return False

    next_user = get_next_rotation_user(group.rotation, group.assignee)

    if not next_user or (group.assignee and next_user.id == group.assignee.id):
        return False

    now = utc_now()

    group.assignee = next_user.id
    group.escalation_level = (group.escalation_level or 0) + 1
    group.reminder_count = 0
    group.last_escalated_at = now
    group.updated_at = now
    group.save()

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type="escalated",
        message=f"Escalated to {next_user.username}",
    )

    _deliver_escalation_notification(group)

    return True


def maybe_escalate_alert_by_policy(group):
    """Escalate an alert group according to its escalation policy."""

    if is_notification_lifecycle_suppressed(group):
        pause_notification_lifecycle(group)
        return False

    if is_escalation_lifecycle_paused(group):
        group.next_escalation_at = None
        group.save(only=[group.__class__.next_escalation_at])
        return False

    if resume_notification_lifecycle(group):
        return False

    if not group.escalation_policy_id:
        return False

    now = utc_now()

    if not group.next_escalation_at:
        return False

    if group.next_escalation_at > now:
        return False

    next_rule, repeat_count = escalation_policy_service.get_next_rule_for_alert(group)

    if not next_rule:
        group.next_escalation_at = None
        group.updated_at = now
        group.save()

        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type="escalation_stopped",
            message="Escalation policy has no next rule",
        )

        return False

    next_user = escalation_policy_service.resolve_rule_user(next_rule)

    if next_rule.target_type == "rotation" and next_rule.target_rotation:
        group.rotation = next_rule.target_rotation
    else:
        group.rotation = None

    group.assignee = next_user
    group.escalation_rule = next_rule
    group.escalation_level = (group.escalation_level or 0) + 1
    group.escalation_repeat_count = repeat_count
    group.reminder_count = 0
    group.last_escalated_at = now
    group.next_escalation_at = escalation_policy_service.get_next_escalation_at(
        next_rule,
        now,
    )
    group.updated_at = now
    group.save()

    target = next_user.username if next_user else "no assignee"

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type="escalated",
        message=f"Escalated by policy rule #{next_rule.position} to {target}",
    )

    _deliver_escalation_notification(group)

    return True
