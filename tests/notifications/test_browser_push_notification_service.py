
from app.modules.db.models import AlertEvent, AlertGroup, BrowserPushSubscription
from app.services.notifications import delivery, rules
from app.services.alerts.lifecycle import upsert_alert
from tests.factories import (
    attach_channel,
    create_channel,
    create_group,
    create_route,
    create_team,
    create_user,
)
from app.modules.common import utc_now


def create_push_subscription(user):
    now = utc_now()

    return BrowserPushSubscription.create(
        user=user.id,
        endpoint=f"https://push.example.test/{user.id}",
        p256dh="test-p256dh",
        auth="test-auth",
        device_name="Test browser",
        user_agent="pytest",
        enabled=True,
        deleted=False,
        created_at=now,
        updated_at=now,
        last_seen_at=now,
    )


def create_assigned_group(user, *, with_regular_channel=False):
    group = create_group()
    team = create_team(group)
    route = create_route(team, group_by=["alertname", "severity"])

    if with_regular_channel:
        channel = create_channel(
            group,
            team,
            channel_type="webhook",
            config={"webhook_url": "https://webhook.example.test"},
        )
        attach_channel(route, channel)

    result = upsert_alert(
        {
            "source": "alertmanager",
            "forced_route_id": route.id,
            "external_id": f"external-{user.id}",
            "dedup_key": f"dedup-{user.id}",
            "title": "DiskFull",
            "message": "/var is 95% full",
            "severity": "critical",
            "labels": {
                "alertname": "DiskFull",
                "severity": "critical",
                "instance": "host1",
            },
            "payload": {"source": "test"},
            "status": "firing",
        }
    )

    alert_group = result.group
    created = result.created_group

    assert alert_group is not None
    assert created is True

    alert_group.assignee = user
    alert_group.save()

    return alert_group


def test_has_matching_notification_channel_returns_true_for_active_push_subscription(db, monkeypatch):
    monkeypatch.setattr(
        rules.browser_push.Config,
        "BROWSER_PUSH_ENABLED",
        True,
        raising=False,
    )

    group = create_group()
    user = create_user("alice", group)

    alert_group = create_assigned_group(user)
    create_push_subscription(user)

    assert delivery.has_matching_notification_channel(alert_group) is True


def test_has_matching_notification_channel_returns_false_without_channels_or_push(db, monkeypatch):
    monkeypatch.setattr(
        rules.browser_push.Config,
        "BROWSER_PUSH_ENABLED",
        True,
        raising=False,
    )

    group = create_group()
    user = create_user("alice", group)

    alert_group = create_assigned_group(user)

    assert delivery.has_matching_notification_channel(alert_group) is False


def test_notify_alert_sends_profile_browser_push_without_route_channels(db, monkeypatch):
    group = create_group()
    user = create_user("alice", group)

    alert_group = create_assigned_group(user)

    calls = []

    def fake_send_alert_push_to_user(assignee, pushed_group, event_type="notification"):
        calls.append(
            {
                "assignee_id": assignee.id,
                "alert_group_id": pushed_group.id,
                "event_type": event_type,
            }
        )
        return 1

    monkeypatch.setattr(
        rules.browser_push,
        "send_alert_push_to_user",
        fake_send_alert_push_to_user,
    )

    sent = delivery.notify_alert(alert_group, event_type="notification")

    assert sent == 1
    assert calls == [
        {
            "assignee_id": user.id,
            "alert_group_id": alert_group.id,
            "event_type": "notification",
        }
    ]

    alert_group = AlertGroup.get_by_id(alert_group.id)

    assert alert_group.last_notification_at is not None

    event = AlertEvent.get(
        (AlertEvent.group == alert_group.id)
        & (AlertEvent.event_type == "notification_browser_push_sent")
    )

    assert "Sent browser push" in event.message


def test_notify_alert_does_not_send_browser_push_without_assignee(db, monkeypatch):
    group = create_group()
    team = create_team(group)
    route = create_route(team, group_by=["alertname", "severity"])

    result = upsert_alert(
        {
            "source": "alertmanager",
            "forced_route_id": route.id,
            "external_id": "external-no-assignee",
            "dedup_key": "dedup-no-assignee",
            "title": "DiskFull",
            "message": "/var is 95% full",
            "severity": "critical",
            "labels": {
                "alertname": "DiskFull",
                "severity": "critical",
                "instance": "host1",
            },
            "payload": {"source": "test"},
            "status": "firing",
        }
    )

    alert_group = result.group
    created = result.created_group

    assert created is True

    calls = []

    def fake_send_alert_push_to_user(assignee, pushed_group, event_type="notification"):
        calls.append((assignee, pushed_group, event_type))
        return 1

    monkeypatch.setattr(
        rules.browser_push,
        "send_alert_push_to_user",
        fake_send_alert_push_to_user,
    )

    sent = delivery.notify_alert(alert_group, event_type="notification")

    assert sent == 0
    assert calls == []


def test_notify_alert_counts_regular_channel_and_browser_push(db, monkeypatch):
    group = create_group()
    user = create_user("alice", group)

    alert_group = create_assigned_group(user, with_regular_channel=True)

    class FakeNotifier:
        supports_update = False

        def send(self, channel, alert_group, text, event_type="notification"):
            return {
                "provider": "webhook",
                "provider_status": "sent",
                "external_message_id": "msg-1",
                "provider_payload": {},
            }

    monkeypatch.setattr(
        delivery,
        "get_notifier",
        lambda channel_type: FakeNotifier(),
    )
    monkeypatch.setattr(
        rules.browser_push,
        "send_alert_push_to_user",
        lambda assignee, alert_group, event_type="notification": 1,
    )

    sent = delivery.notify_alert(alert_group, event_type="notification")

    assert sent == 2

    event_types = {
        row.event_type
        for row in AlertEvent.select().where(AlertEvent.group == alert_group.id)
    }

    assert "notification_sent" in event_types
    assert "notification_browser_push_sent" in event_types
