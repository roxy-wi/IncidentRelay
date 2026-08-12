import logging
from datetime import datetime

from app.modules.db import alerts_repo, notifications_repo
from app.notifiers.registry import get_notifier
from app.services.links import build_alert_web_url, build_source_event_url
from app.services.severity import normalize_severity, normalize_severity_list
from app.services.routing.service_context import format_service_context_plain, service_display_name
from app.services.notifications import rules
from app.services.alerts.priority import alert_priority_label, format_alert_title_with_priority
from app.services.alerts.maintenance_state import is_notification_lifecycle_suppressed
from app.services.notifications.policies.resolver import resolve_notification_channels
from app.services.alerts.correlation import format_correlation_plain
from app.modules.common import utc_now

EDITABLE_EVENTS = {"acknowledged", "resolved"}

logger = logging.getLogger("oncall.notifications")


def _ensure_alert_group(group):
    if group.__class__.__name__ != "AlertGroup":
        raise TypeError(
            "notification_service expects AlertGroup, not Alert. "
            "Use alert.group or alerts_repo.get_alert_group(...)."
        )

    return group


def _group_log_id(group):
    return getattr(group, "id", None)


def _team_display_name(alert):
    """Return team display name using name first, then slug."""
    team = getattr(alert, "team", None)
    if not team:
        return "unknown"

    return team.name or team.slug or "unknown"


def format_alert_message(alert, event_type="notification"):
    """Format a plain text alert notification."""
    assignee = (
        alert.assignee.display_name or alert.assignee.username
        if alert.assignee
        else "unknown"
    )
    team = _team_display_name(alert)
    service = service_display_name(alert)
    alert_url = build_alert_web_url(alert)
    source_event_url = build_source_event_url(alert)

    lines = [
        f"{event_type.upper()}: {format_alert_title_with_priority(alert)}",
        f"Team: {team}",
        f"Service: {service}",
        f"Status: {alert.status}",
        f"Severity: {alert.severity or '-'}",
        f"Priority: {alert_priority_label(alert)}",
        f"Assignee: {assignee}",
        f"Source: {alert.source}",
        f"Message: {alert.message or '-'}",
    ]

    if alert_url:
        lines.append(f"Alert URL: {alert_url}")

    if source_event_url:
        lines.append(f"Source event: {source_event_url}")

    service_context = format_service_context_plain(alert)
    if service_context:
        lines.append("")
        lines.extend(service_context)

    correlation_context = format_correlation_plain(alert)
    if correlation_context:
        lines.append("")
        lines.extend(correlation_context)

    return "\n".join(lines)


def notification_log_extra(channel, group, event_type, result=None, error=None, **extra_fields):
    """Build a consistent structured log payload for group notification events."""

    result = result or {}
    data = {
        "alert_group_id": _group_log_id(group),
        "channel_id": getattr(channel, "id", None),
        "channel_name": getattr(channel, "name", None),
        "channel_type": getattr(channel, "channel_type", None),
        "event_type": event_type,
        "provider": result.get("provider") or getattr(channel, "channel_type", None),
    }

    external_message_id = result.get("external_message_id")
    if external_message_id:
        data["external_message_id"] = external_message_id

    external_channel_id = result.get("external_channel_id")
    if external_channel_id:
        data["external_channel_id"] = external_channel_id

    provider_status = result.get("provider_status")
    if provider_status:
        data["provider_status"] = provider_status

    if error is not None:
        data["error"] = str(error)

    data.update(extra_fields)
    return {"extra": data}


def get_channel_notify_on_severities(channel):
    """Return normalized channel-level severity filter.

    Empty list means that the channel accepts all severities.
    """
    config = channel.config or {}
    raw_severities = config.get("notify_on_severities")

    try:
        return set(normalize_severity_list(raw_severities))
    except ValueError as exc:
        logger.warning(
            "invalid channel severity filter, ignoring it",
            extra={
                "extra": {
                    "channel_id": channel.id,
                    "channel_name": getattr(channel, "name", None),
                    "channel_type": channel.channel_type,
                    "error": str(exc),
                }
            },
        )
        return set()


def channel_matches_alert_severity(channel, alert):
    """Return True when the channel should receive this alert severity."""
    allowed_severities = get_channel_notify_on_severities(channel)
    if not allowed_severities:
        return True

    alert_severity = normalize_severity(getattr(alert, "severity", None))
    return alert_severity in allowed_severities


def has_matching_notification_channel(alert, event_type="notification"):
    """Return True if the alert has at least one delivery target.

    Browser push and other user-level rules are independent from shared
    notification channels.
    """
    resolution = resolve_notification_channels(alert, event_type)

    for channel in resolution.channels:
        if channel_matches_alert_severity(channel, alert):
            return True

    return rules.has_deliverable_user_notification(alert, event_type)


def _notification_targets(group, event_type):
    """Return channel and existing delivery pairs for an event."""
    if event_type in EDITABLE_EVENTS:
        return [
            (delivery.channel, delivery)
            for delivery in notifications_repo.list_notifications_for_group(
                group.id
            )
        ]

    resolution = resolve_notification_channels(group, event_type)

    return [
        (
            channel,
            notifications_repo.get_notification(
                group_id=group.id,
                channel_id=channel.id,
            ),
        )
        for channel in resolution.channels
    ]


def notify_alert(group, event_type="notification"):
    """Send or update alert group notifications for route channels and user rules."""

    group = _ensure_alert_group(group)

    if (
        event_type in {"notification", "update", "reminder", "escalation"}
        and is_notification_lifecycle_suppressed(group)
    ):
        logger.info(
            "notification skipped during maintenance",
            extra={
                "extra": {
                    "alert_group_id": group.id,
                    "event_type": event_type,
                    "maintenance_window_id": group.maintenance_window_id,
                }
            },
        )
        return 0

    text = format_alert_message(group, event_type)
    sent_count = 0

    for channel, delivery in _notification_targets(group, event_type):
        if not channel.enabled:
            continue

        try:
            notifier = get_notifier(channel.channel_type)
        except RuntimeError as exc:
            logger.exception(
                "unsupported notification channel type",
                extra=notification_log_extra(channel, group, event_type, error=exc),
            )
            continue

        if not channel_matches_alert_severity(channel, group):
            can_update_existing_message = (
                event_type in EDITABLE_EVENTS
                and delivery
                and notifier.can_update(channel, delivery)
            )

            if not can_update_existing_message:
                logger.info(
                    "notification skipped by channel severity filter",
                    extra=notification_log_extra(
                        channel,
                        group,
                        event_type,
                        alert_severity=group.severity,
                        allowed_severities=sorted(
                            get_channel_notify_on_severities(channel)
                        ),
                    ),
                )
                continue

        try:
            if event_type in EDITABLE_EVENTS and delivery and notifier.can_update(channel, delivery):
                result = notifier.update(
                    channel,
                    group,
                    text,
                    delivery,
                    event_type=event_type,
                ) or {}

                notifications_repo.save_notification(
                    group_id=group.id,
                    channel_id=channel.id,
                    provider=result.get("provider") or channel.channel_type,
                    external_message_id=result.get("external_message_id"),
                    external_channel_id=result.get("external_channel_id"),
                    event_type=event_type,
                    provider_status=result.get("provider_status"),
                    provider_payload=result.get("provider_payload"),
                )

                alerts_repo.create_alert_event(
                    group_id=group.id,
                    event_type=f"{event_type}_message_updated",
                    message=f"Updated {channel.channel_type}:{channel.name}",
                )

                logger.info(
                    "notification message updated",
                    extra=notification_log_extra(
                        channel,
                        group,
                        event_type,
                        result=result,
                    ),
                )

                sent_count += 1
                continue

            result = notifier.send(
                channel,
                group,
                text,
                event_type=event_type,
            ) or {}

            if result.get("skipped"):
                logger.info(
                    "notification skipped",
                    extra=notification_log_extra(
                        channel,
                        group,
                        event_type,
                        result=result,
                        reason=result.get("skip_reason"),
                    ),
                )
                continue

            notifications_repo.save_notification(
                group_id=group.id,
                channel_id=channel.id,
                provider=result.get("provider") or channel.channel_type,
                external_message_id=result.get("external_message_id"),
                external_channel_id=result.get("external_channel_id"),
                event_type=event_type,
                provider_status=result.get("provider_status"),
                provider_payload=result.get("provider_payload"),
            )

            alerts_repo.create_alert_event(
                group_id=group.id,
                event_type=f"{event_type}_sent",
                message=f"Sent to {channel.channel_type}:{channel.name}",
            )

            logger.info(
                "notification sent",
                extra=notification_log_extra(
                    channel,
                    group,
                    event_type,
                    result=result,
                ),
            )

            sent_count += 1

        except Exception as exc:
            notifications_repo.mark_notification_error(
                group_id=group.id,
                channel_id=channel.id,
                provider=channel.channel_type,
                event_type=event_type,
                error=exc,
            )

            alerts_repo.create_alert_event(
                group_id=group.id,
                event_type=f"{event_type}_failed",
                message=f"{channel.channel_type}:{channel.name}: {exc}",
            )

            logger.warning(
                "notification failed",
                extra=notification_log_extra(
                    channel,
                    group,
                    event_type,
                    error=exc,
                ),
            )

    try:
        user_sent_count = rules.enqueue_user_notifications(
            group,
            event_type=event_type,
        )

        sent_count += user_sent_count

        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type=f"{event_type}_user_notifications_processed",
            message=f"User-level notifications processed: {user_sent_count}",
        )

    except Exception as exc:
        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type=f"{event_type}_user_notifications_failed",
            message=f"User-level notification failed: {exc}",
        )

        logger.exception(
            "user-level notification failed",
            extra={
                "extra": {
                    "alert_group_id": group.id,
                    "event_type": event_type,
                    "error": str(exc),
                }
            },
        )

    if sent_count:
        alerts_repo.record_group_notification_time(group, utc_now())

    return sent_count


def update_alert_messages(group, event_type):
    """Update previously sent editable group messages."""
    group = _ensure_alert_group(group)
    text = format_alert_message(group, event_type)
    updated_count = 0

    deliveries = notifications_repo.list_notifications_for_group(group.id)

    for delivery in deliveries:
        channel = delivery.channel

        if not channel.enabled or getattr(channel, "deleted", False):
            continue

        try:
            notifier = get_notifier(channel.channel_type)
        except RuntimeError as exc:
            logger.exception(
                "unsupported notification channel type",
                extra=notification_log_extra(
                    channel,
                    group,
                    event_type,
                    error=exc,
                ),
            )
            continue

        if not notifier.can_update(channel, delivery):
            continue

        try:
            result = notifier.update(
                channel,
                group,
                text,
                delivery,
                event_type=event_type,
            ) or {}

            notifications_repo.save_notification(
                group_id=group.id,
                channel_id=channel.id,
                provider=result.get("provider") or channel.channel_type,
                external_message_id=result.get("external_message_id"),
                external_channel_id=result.get("external_channel_id"),
                event_type=event_type,
                provider_status=result.get("provider_status"),
                provider_payload=result.get("provider_payload"),
            )

            alerts_repo.create_alert_event(
                group_id=group.id,
                event_type=f"{event_type}_message_updated",
                message=f"Updated {channel.channel_type}:{channel.name}",
            )

            logger.info(
                "notification message updated",
                extra=notification_log_extra(
                    channel,
                    group,
                    event_type,
                    result=result,
                ),
            )

            updated_count += 1
        except Exception as exc:
            notifications_repo.mark_notification_error(
                group_id=group.id,
                channel_id=channel.id,
                provider=channel.channel_type,
                event_type=event_type,
                error=exc,
            )

            alerts_repo.create_alert_event(
                group_id=group.id,
                event_type=f"{event_type}_update_failed",
                message=f"{channel.channel_type}:{channel.name}: {exc}",
            )

            logger.warning(
                "notification update failed",
                extra=notification_log_extra(
                    channel,
                    group,
                    event_type,
                    error=exc,
                ),
            )

    return updated_count
