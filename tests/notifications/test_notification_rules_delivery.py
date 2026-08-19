from datetime import timedelta

from app.modules.db.models import UserNotificationDelivery
from app.services.alerts.lifecycle import upsert_alert
from app.services.notifications import rules
from tests.factories import create_group, create_route, create_team, create_user
from app.modules.common import utc_now


class FakeDirectNotifier:
    def __init__(self, result=None, error=None):
        self.result = result or {}
        self.error = error
        self.calls = []

    def send(self, channel, alert_group, text, event_type="notification"):
        self.calls.append({
            "channel_id": channel.id,
            "group_id": alert_group.id,
            "text": text,
            "event_type": event_type,
            "config": channel.config,
        })
        if self.error:
            raise self.error
        return self.result


def _create_assigned_group(username, *, status="firing"):
    group = create_group()
    team = create_team(group)
    user = create_user(username, group)
    route = create_route(team, group_by=["alertname", "severity", "instance"])
    result = upsert_alert({
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": f"external-{username}",
        "dedup_key": f"dedup-{username}",
        "title": "DiskFull",
        "message": "/var is 95% full",
        "severity": "critical",
        "labels": {
            "alertname": "DiskFull",
            "severity": "critical",
            "instance": "host1",
        },
        "payload": {"source": "notification-rule-test"},
        "status": "firing",
    })

    alert_group = result.group
    assert result.created_group is True

    alert_group.assignee = user
    alert_group.status = status
    alert_group.save()

    return user, alert_group


def _create_due_delivery(user, alert_group, rule, *, event_type="notification"):
    return UserNotificationDelivery.create(
        group=alert_group.id,
        user=user.id,
        rule=rule.id if rule else None,
        method=rule.method if rule else rules.NOTIFICATION_METHOD_EMAIL,
        event_type=event_type,
        status="pending",
        scheduled_at=utc_now() - timedelta(seconds=1),
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def test_process_due_user_notifications_sends_due_email_delivery(db, monkeypatch):
    user, alert_group = _create_assigned_group("release-email-user")
    rule = rules.create_user_rule(
        user,
        method=rules.NOTIFICATION_METHOD_EMAIL,
        delay_seconds=60,
        severities=["critical"],
        event_types=["notification"],
    )
    delivery = _create_due_delivery(user, alert_group, rule)
    notifier = FakeDirectNotifier({
        "provider": "email",
        "external_message_id": "message-1",
        "external_channel_id": "mailbox-1",
        "provider_status": "sent",
        "provider_payload": {"accepted": 1},
    })

    monkeypatch.setitem(
        rules.DIRECT_NOTIFIERS, rules.NOTIFICATION_METHOD_EMAIL, notifier
    )

    assert rules.process_due_user_notifications() == 1

    delivery = UserNotificationDelivery.get_by_id(delivery.id)
    assert delivery.status == "sent"
    assert delivery.sent_at is not None
    assert delivery.provider == "email"
    assert delivery.external_message_id == "message-1"
    assert delivery.external_channel_id == "mailbox-1"
    assert delivery.provider_status == "sent"
    assert delivery.provider_payload == {"accepted": 1}
    assert delivery.last_error is None

    assert len(notifier.calls) == 1
    assert notifier.calls[0]["group_id"] == alert_group.id
    assert notifier.calls[0]["event_type"] == "notification"
    assert "NOTIFICATION: " in notifier.calls[0]["text"]
    assert "DiskFull" in notifier.calls[0]["text"]


def test_direct_notifier_failure_marks_delivery_failed(db, monkeypatch):
    user, alert_group = _create_assigned_group("release-email-fail-user")
    rule = rules.create_user_rule(
        user,
        method=rules.NOTIFICATION_METHOD_EMAIL,
        delay_seconds=60,
        severities=["critical"],
        event_types=["notification"],
    )
    delivery = _create_due_delivery(user, alert_group, rule)
    notifier = FakeDirectNotifier(error=RuntimeError("smtp unavailable"))

    monkeypatch.setitem(
        rules.DIRECT_NOTIFIERS, rules.NOTIFICATION_METHOD_EMAIL, notifier
    )

    assert rules.process_due_user_notifications() == 0

    delivery = UserNotificationDelivery.get_by_id(delivery.id)
    assert delivery.status == "failed"
    assert delivery.sent_at is None
    assert delivery.last_error == "smtp unavailable"
    assert len(notifier.calls) == 1


def test_unsupported_user_notification_method_is_marked_failed(db):
    user, alert_group = _create_assigned_group("release-unsupported-user")
    delivery = UserNotificationDelivery.create(
        group=alert_group.id,
        user=user.id,
        rule=None,
        method="sms",
        event_type="notification",
        status="pending",
        scheduled_at=utc_now() - timedelta(seconds=1),
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    assert rules.send_delivery(delivery) == 0

    delivery = UserNotificationDelivery.get_by_id(delivery.id)
    assert delivery.status == "failed"
    assert delivery.sent_at is None
    assert delivery.last_error == "unsupported method: sms"


def test_resolved_user_notification_is_sent_for_resolved_group(db, monkeypatch):
    user, alert_group = _create_assigned_group(
        "release-resolved-email-user", status="resolved"
    )
    rule = rules.create_user_rule(
        user,
        method=rules.NOTIFICATION_METHOD_EMAIL,
        delay_seconds=60,
        severities=["critical"],
        event_types=["resolved"],
    )
    delivery = _create_due_delivery(user, alert_group, rule, event_type="resolved")
    notifier = FakeDirectNotifier({
        "provider": "email",
        "provider_status": "sent",
        "provider_payload": {"accepted": 1},
    })

    monkeypatch.setitem(
        rules.DIRECT_NOTIFIERS, rules.NOTIFICATION_METHOD_EMAIL, notifier
    )

    assert rules.process_due_user_notifications() == 1

    delivery = UserNotificationDelivery.get_by_id(delivery.id)
    assert delivery.status == "sent"
    assert delivery.provider == "email"
    assert delivery.provider_status == "sent"
    assert len(notifier.calls) == 1
    assert notifier.calls[0]["event_type"] == "resolved"
    assert "RESOLVED: " in notifier.calls[0]["text"]
