import logging
from datetime import timedelta
from types import SimpleNamespace

from app.modules.db.models import (
    AlertGroup,
    User,
    UserNotificationDelivery,
    UserNotificationRule,
)
from app.notifiers.browser_push import service as browser_push
from app.notifiers.email.notifier import EmailNotifier
from app.notifiers.voice.notifier import VoiceCallNotifier
from app.services.severity import normalize_severity, normalize_severity_list
from app.modules.db import alerts_repo
from app.modules.common import utc_now
from app.services.alerts.maintenance_state import is_notification_lifecycle_suppressed


logger = logging.getLogger("oncall.notification_rules")

NOTIFICATION_METHOD_BROWSER_PUSH = "browser_push"
NOTIFICATION_METHOD_EMAIL = "email"
NOTIFICATION_METHOD_VOICE_CALL = "voice_call"

NOTIFICATION_RULE_METHODS = {
    NOTIFICATION_METHOD_BROWSER_PUSH,
    NOTIFICATION_METHOD_EMAIL,
    NOTIFICATION_METHOD_VOICE_CALL,
}

DEFAULT_RULE_EVENT_TYPES = {
    "notification",
    "reminder",
    "escalation",
}

DIRECT_NOTIFIERS = {
    NOTIFICATION_METHOD_EMAIL: EmailNotifier(),
    NOTIFICATION_METHOD_VOICE_CALL: VoiceCallNotifier(),
}

SKIP_IF_NOT_FIRING_EVENT_TYPES = {
    "notification",
    "reminder",
    "escalation",
}


def _ensure_alert_group(group):
    if group.__class__.__name__ != "AlertGroup":
        raise TypeError(
            "notification_rules expects AlertGroup, not Alert. "
            "Use group-level notifications only."
        )

    return group


def should_skip_delivery_for_group_status(delivery):
    """Return True when delayed delivery is no longer relevant."""

    if delivery.event_type not in SKIP_IF_NOT_FIRING_EVENT_TYPES:
        return False

    group = AlertGroup.get_by_id(delivery.group_id)

    if is_notification_lifecycle_suppressed(group):
        return True

    return group.status != "firing"


def serialize_rule(rule):
    return {
        "id": rule.id,
        "position": rule.position,
        "method": rule.method,
        "delay_seconds": rule.delay_seconds,
        "enabled": rule.enabled,
        "severities": rule.severities or [],
        "event_types": rule.event_types or [],
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


def list_user_rules(user):
    rows = (
        UserNotificationRule
        .select()
        .where(
            (UserNotificationRule.user == user.id)
            & (UserNotificationRule.deleted == False)
        )
        .order_by(UserNotificationRule.position.asc(), UserNotificationRule.id.asc())
    )

    return [serialize_rule(row) for row in rows]


def create_user_rule(
    user,
    *,
    method,
    delay_seconds=0,
    severities=None,
    event_types=None,
    enabled=True,
):
    validate_rule_payload(method, delay_seconds, severities, event_types)

    max_position = (
        UserNotificationRule
        .select()
        .where(
            (UserNotificationRule.user == user.id)
            & (UserNotificationRule.deleted == False)
        )
        .count()
    )

    return UserNotificationRule.create(
        user=user.id,
        position=max_position + 1,
        method=method,
        delay_seconds=delay_seconds or 0,
        severities=severities or [],
        event_types=event_types or [],
        enabled=enabled,
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def update_user_rule(user, rule_id, payload):
    rule = get_user_rule(user, rule_id)

    method = payload.get("method", rule.method)
    delay_seconds = payload.get("delay_seconds", rule.delay_seconds)
    severities = payload.get("severities", rule.severities or [])
    event_types = payload.get("event_types", rule.event_types or [])

    validate_rule_payload(method, delay_seconds, severities, event_types)

    rule.method = method
    rule.delay_seconds = delay_seconds or 0
    rule.severities = severities or []
    rule.event_types = event_types or []
    rule.enabled = bool(payload.get("enabled", rule.enabled))
    rule.updated_at = utc_now()
    rule.save()

    return rule


def delete_user_rule(user, rule_id):
    rule = get_user_rule(user, rule_id)

    rule.deleted = True
    rule.deleted_at = utc_now()
    rule.enabled = False
    rule.updated_at = utc_now()
    rule.save()

    return rule


def get_user_rule(user, rule_id):
    rule = UserNotificationRule.get_or_none(
        (UserNotificationRule.id == rule_id)
        & (UserNotificationRule.user == user.id)
        & (UserNotificationRule.deleted == False)
    )

    if not rule:
        raise ValueError("notification rule was not found")

    return rule


def validate_rule_payload(method, delay_seconds, severities, event_types):
    if method not in NOTIFICATION_RULE_METHODS:
        raise ValueError("unsupported notification rule method")

    if delay_seconds is None:
        delay_seconds = 0

    if int(delay_seconds) < 0:
        raise ValueError("delay_seconds must be greater than or equal to 0")

    if severities:
        normalize_severity_list(severities)

    if event_types:
        invalid = set(event_types) - {
            "notification",
            "reminder",
            "escalation",
            "acknowledged",
            "resolved",
        }

        if invalid:
            raise ValueError(
                "unsupported notification rule event type: "
                + ", ".join(sorted(invalid))
            )


def has_custom_user_rules(user_id):
    """Return True when user has at least one non-deleted notification rule."""

    if not user_id:
        return False

    return (
        UserNotificationRule
        .select(UserNotificationRule.id)
        .where(
            (UserNotificationRule.user == user_id)
            & (UserNotificationRule.deleted == False)
        )
        .exists()
    )


def list_matching_rules(group, event_type="notification"):
    """Return enabled rules matching alert group severity and event type."""

    group = _ensure_alert_group(group)

    user_id = getattr(group, "assignee_id", None)

    if not user_id:
        return []

    rules = (
        UserNotificationRule
        .select()
        .where(
            (UserNotificationRule.user == user_id)
            & (UserNotificationRule.enabled == True)
            & (UserNotificationRule.deleted == False)
        )
        .order_by(UserNotificationRule.position.asc(), UserNotificationRule.id.asc())
    )

    return [
        rule
        for rule in rules
        if rule_matches_group(rule, group, event_type)
    ]


def rule_matches_group(rule, group, event_type):
    rule_event_types = set(rule.event_types or [])

    if rule_event_types:
        if event_type not in rule_event_types:
            return False
    elif event_type not in DEFAULT_RULE_EVENT_TYPES:
        return False

    allowed_severities = set(normalize_severity_list(rule.severities or []))

    if allowed_severities:
        group_severity = normalize_severity(getattr(group, "severity", None))

        if group_severity not in allowed_severities:
            return False

    return True


def has_deliverable_user_notification(group, event_type="notification"):
    """Return True if alert group assignee can receive user-level notification."""

    group = _ensure_alert_group(group)

    user_id = getattr(group, "assignee_id", None)

    if not user_id:
        return False

    if not has_custom_user_rules(user_id):
        return browser_push.can_send_alert_push(group)

    return bool(list_matching_rules(group, event_type=event_type))


def enqueue_user_notifications(group, event_type="notification"):
    """Create/send user-level notifications for alert group assignee."""

    group = _ensure_alert_group(group)

    if (
        event_type in SKIP_IF_NOT_FIRING_EVENT_TYPES
        and is_notification_lifecycle_suppressed(group)
    ):
        return 0

    assignee = getattr(group, "assignee", None)
    assignee_id = getattr(group, "assignee_id", None)

    if not assignee_id:
        return 0

    if not assignee:
        try:
            assignee = User.get_by_id(assignee_id)
        except User.DoesNotExist:
            return 0

    now = utc_now()

    # Default profile browser push when the user has no custom rules.
    if not has_custom_user_rules(assignee.id):
        if event_type not in DEFAULT_RULE_EVENT_TYPES:
            return 0

        delivery = create_delivery(
            group=group,
            user=assignee,
            rule=None,
            method=NOTIFICATION_METHOD_BROWSER_PUSH,
            event_type=event_type,
            scheduled_at=now,
        )

        return send_delivery(delivery)

    sent_count = 0

    for rule in list_matching_rules(group, event_type=event_type):
        scheduled_at = now + timedelta(
            seconds=max(int(rule.delay_seconds or 0), 0)
        )

        delivery = create_delivery(
            group=group,
            user=assignee,
            rule=rule,
            method=rule.method,
            event_type=event_type,
            scheduled_at=scheduled_at,
        )

        if rule.delay_seconds and rule.delay_seconds > 0:
            continue

        sent_count += send_delivery(delivery)

    return sent_count


def create_delivery(group, user, rule, method, event_type, scheduled_at):
    group = _ensure_alert_group(group)

    return UserNotificationDelivery.create(
        group=group.id,
        user=user.id,
        rule=rule.id if rule else None,
        method=method,
        event_type=event_type,
        status="pending",
        scheduled_at=scheduled_at,
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def process_due_user_notifications(limit=100):
    """Process due user notification deliveries and return sent count."""
    now = utc_now()
    processed = 0

    due_deliveries = (
        UserNotificationDelivery
        .select()
        .where(
            (UserNotificationDelivery.status == "pending")
            & (UserNotificationDelivery.scheduled_at <= now)
        )
        .order_by(UserNotificationDelivery.scheduled_at.asc())
        .limit(limit)
    )

    for due_delivery in due_deliveries:
        claimed = (
            UserNotificationDelivery
            .update(
                status="processing",
                updated_at=utc_now(),
            )
            .where(
                (UserNotificationDelivery.id == due_delivery.id)
                & (UserNotificationDelivery.status == "pending")
            )
            .execute()
        )

        if not claimed:
            continue

        delivery = UserNotificationDelivery.get_by_id(due_delivery.id)

        group = AlertGroup.get_by_id(delivery.group_id)

        if (
            delivery.event_type in SKIP_IF_NOT_FIRING_EVENT_TYPES
            and is_notification_lifecycle_suppressed(group)
        ):
            mark_delivery_skipped(
                delivery,
                "maintenance_suppressed",
            )
            continue

        if should_skip_delivery_for_group_status(delivery):
            mark_delivery_skipped(
                delivery,
                "alert_not_firing",
            )
            continue

        processed += send_delivery(delivery)

    return processed


def send_browser_push_delivery(delivery):
    """Send browser push delivery and update delivery history."""
    now = utc_now()
    group = delivery.group

    try:
        sent = browser_push.send_alert_push_to_user(
            delivery.user,
            group,
            event_type=delivery.event_type,
        )
    except Exception as exc:
        mark_delivery_failed(delivery, exc)

        alerts_repo.create_alert_event(
            group_id=group.id,
            event_type=f"{delivery.event_type}_browser_push_failed",
            message=f"browser_push: {exc}",
        )

        return 0

    if not sent:
        mark_delivery_skipped(
            delivery,
            "no_active_push_subscriptions",
        )
        return 0

    (
        UserNotificationDelivery
        .update(
            status="sent",
            sent_at=now,
            provider="browser_push",
            provider_status="sent",
            provider_payload={
                "sent": sent,
            },
            last_error=None,
            updated_at=now,
        )
        .where(UserNotificationDelivery.id == delivery.id)
        .execute()
    )

    alerts_repo.create_alert_event(
        group_id=group.id,
        event_type=f"{delivery.event_type}_browser_push_sent",
        message=f"Sent browser push to {sent} device(s)",
    )

    return 1


def send_delivery(delivery):
    """Send pending user notification delivery."""

    group = AlertGroup.get_or_none(AlertGroup.id == delivery.group_id)

    if not group:
        mark_delivery_skipped(delivery, "alert_group_not_found")
        return 0

    if delivery.event_type in SKIP_IF_NOT_FIRING_EVENT_TYPES:
        if is_notification_lifecycle_suppressed(group):
            mark_delivery_skipped(delivery, "maintenance_suppressed")
            return 0

        if group.status != "firing":
            mark_delivery_skipped(delivery, "alert_not_firing")
            return 0

    try:
        if delivery.method == NOTIFICATION_METHOD_BROWSER_PUSH:
            return send_browser_push_delivery(delivery)

        if delivery.method in DIRECT_NOTIFIERS:
            result = send_direct_notifier_delivery(delivery, group)
        else:
            mark_delivery_failed(
                delivery,
                f"unsupported method: {delivery.method}",
            )
            return 0

    except Exception as exc:
        mark_delivery_failed(delivery, str(exc))
        return 0

    delivery.status = "sent"
    delivery.sent_at = utc_now()
    delivery.provider = result.get("provider") or delivery.method
    delivery.external_message_id = result.get("external_message_id")
    delivery.external_channel_id = result.get("external_channel_id")
    delivery.provider_status = result.get("provider_status")
    delivery.provider_payload = result.get("provider_payload")
    delivery.last_error = None
    delivery.updated_at = utc_now()
    delivery.save()

    return 1


def send_direct_notifier_delivery(delivery, group):
    from app.services.notifications.delivery import format_alert_message

    notifier = DIRECT_NOTIFIERS[delivery.method]

    channel = SimpleNamespace(
        id=delivery.id,
        name=f"Notification rule #{delivery.rule_id or 'default'}",
        channel_type=delivery.method,
        config=build_direct_channel_config(delivery),
    )

    text = format_alert_message(group, delivery.event_type)

    result = notifier.send(
        channel,
        group,
        text,
        event_type=delivery.event_type,
    ) or {}

    return result


def build_direct_channel_config(delivery):
    config = {}

    if delivery.method == NOTIFICATION_METHOD_VOICE_CALL:
        config["callback_url"] = build_voice_rule_callback_url(delivery)

    return config


def build_voice_rule_callback_url(delivery):
    from app.settings import Config

    if not getattr(Config, "VOICE_CALLBACK_SECRET", ""):
        return None

    return (
        f"{Config.PUBLIC_BASE_URL.rstrip()}"
        f"/api/integrations/voice/rule-callback/{delivery.id}"
    )


def mark_delivery_skipped(delivery, reason):
    """Mark user notification delivery as skipped."""
    now = utc_now()

    (
        UserNotificationDelivery
        .update(
            status="skipped",
            provider_status="skipped",
            last_error=reason,
            updated_at=now,
        )
        .where(UserNotificationDelivery.id == delivery.id)
        .execute()
    )


def mark_delivery_failed(delivery, error):
    delivery.status = "failed"
    delivery.last_error = str(error)
    delivery.updated_at = utc_now()
    delivery.save()
