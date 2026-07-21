import logging
from datetime import datetime, timedelta

from app import Config
from app.modules.db import alerts_repo
from app.services.notifications.delivery import notify_alert
from app.modules.common import utc_now

logger = logging.getLogger("oncall.alerts")


def _alert_group_wait_seconds():
    return int(getattr(Config, "ALERT_GROUP_WAIT_SECONDS", 30) or 0)


def _alert_group_interval_seconds():
    return int(getattr(Config, "ALERT_GROUP_INTERVAL_SECONDS", 300) or 0)


def schedule_group_notification(group, reason="notification", now=None):
    """Schedule group notification according to group_wait/group_interval."""

    now = now or utc_now()

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

    for group in groups:
        try:
            group = alerts_repo.recalculate_alert_group(group)

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
