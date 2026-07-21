import logging
from datetime import timedelta, datetime

from app.modules.db import alerts_repo
from app.services import escalation_policies as escalation_policy_service
from app.services.alerts.escalation import maybe_escalate_alert
from app.services.notifications.delivery import has_matching_notification_channel, notify_alert
from app.modules.common import utc_now

logger = logging.getLogger("oncall.alerts")


def get_alert_reminder_interval(group):
    """Return the reminder interval for an alert group."""

    if group.escalation_policy:
        return escalation_policy_service.get_policy_reminder_interval(group)

    if not group.rotation:
        return 0

    return group.rotation.reminder_interval_seconds


def should_send_reminder(group, now):
    """Check whether a reminder should be sent now."""

    reminder_interval = get_alert_reminder_interval(group)

    if reminder_interval == 0:
        return False

    if not group.last_notification_at:
        return False

    return group.last_notification_at <= now - timedelta(seconds=reminder_interval)


def send_unacked_reminders():
    """Send reminder notifications for unacknowledged alert groups.

    Escalation policy checks are intentionally evaluated before reminder gating:
    policy escalation must work even when reminder interval is disabled.
    """

    now = utc_now()
    count = 0

    for group in alerts_repo.list_firing_alert_groups():
        if group.escalation_policy_id:
            if maybe_escalate_alert(group):
                count += 1
                continue

            if not group.next_escalation_at:
                logger.debug(
                    "reminder skipped because escalation policy is exhausted",
                    extra={
                        "extra": {
                            "alert_group_id": group.id,
                            "route_id": group.route.id if group.route else None,
                            "escalation_policy_id": group.escalation_policy_id,
                            "escalation_rule_id": group.escalation_rule_id,
                        }
                    },
                )
                continue

        if group.notification_pending:
            logger.debug(
                "reminder skipped because alert group notification is pending",
                extra={
                    "extra": {
                        "alert_group_id": group.id,
                        "notification_reason": group.notification_reason,
                        "notification_due_at": (
                            group.notification_due_at.isoformat()
                            if group.notification_due_at
                            else None
                        ),
                    }
                },
            )
            continue

        if not group.last_notification_at:
            logger.debug(
                "reminder skipped because initial notification was not sent yet",
                extra={
                    "extra": {
                        "alert_group_id": group.id,
                    }
                },
            )
            continue

        interval = get_alert_reminder_interval(group)

        if interval == 0:
            logger.debug(
                "reminder skipped because reminder interval is disabled",
                extra={
                    "extra": {
                        "alert_group_id": group.id,
                        "team_id": group.team.id if group.team else None,
                        "rotation_id": group.rotation.id if group.rotation else None,
                    }
                },
            )
            continue

        if not has_matching_notification_channel(group, event_type="reminder"):
            logger.debug(
                "reminder skipped because no channel matches alert group severity",
                extra={
                    "extra": {
                        "alert_group_id": group.id,
                        "severity": group.severity,
                        "route_id": group.route.id if group.route else None,
                    }
                },
            )
            continue

        if not should_send_reminder(group, now):
            continue

        if not group.escalation_policy_id and maybe_escalate_alert(group):
            count += 1
            continue

        sent_count = notify_alert(group, event_type="reminder")

        if not sent_count:
            logger.info(
                "reminder skipped because no notification was sent",
                extra={
                    "extra": {
                        "alert_group_id": group.id,
                        "severity": group.severity,
                        "route_id": group.route.id if group.route else None,
                    }
                },
            )
            continue

        alerts_repo.increment_group_reminder(group, now)

        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type="reminder_sent",
            message=f"Reminder count: {group.reminder_count}",
        )

        count += 1

    return count
