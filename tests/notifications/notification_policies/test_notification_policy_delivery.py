from app.modules.db.models import AlertNotification
from app.services.alerts.lifecycle import upsert_alert
from app.services.notifications.delivery import (
    has_matching_notification_channel,
    notify_alert,
    update_alert_messages,
)
from tests.factories import (
    create_channel,
    create_group,
    create_notification_policy,
    create_notification_policy_rule,
    create_route,
    create_service,
    create_team,
    attach_channel,
)


class FakeNotifier:
    def __init__(self, supports_update=False):
        self.supports_update = supports_update
        self.sent = []
        self.updated = []

    def can_update(self, channel, delivery=None):
        return self.supports_update

    def send(self, channel, alert_group, text, event_type="notification"):
        self.sent.append((channel.id, alert_group.id, event_type))

        return {
            "provider": "fake",
            "external_message_id": f"message-{alert_group.id}",
            "external_channel_id": f"channel-{channel.id}",
            "provider_status": "sent",
        }

    def update(
        self,
        channel,
        alert_group,
        text,
        delivery,
        event_type="resolved",
    ):
        self.updated.append(
            (channel.id, alert_group.id, event_type, delivery.id)
        )

        return {
            "provider": "fake",
            "external_message_id": delivery.external_message_id,
            "external_channel_id": delivery.external_channel_id,
            "provider_status": "updated",
        }


def _create_alert_group(route):
    result = upsert_alert({
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": "policy-delivery-external",
        "dedup_key": "policy-delivery-dedup",
        "title": "DiskFull",
        "message": "/var is full",
        "severity": "critical",
        "labels": {
            "alertname": "DiskFull",
            "severity": "critical",
            "instance": "host1",
        },
        "payload": {},
        "status": "firing",
    })

    return result.group


def _create_policy_route(event_types=None):
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    channel = create_channel(group, team, channel_type="fake")

    policy = create_notification_policy(team)
    create_notification_policy_rule(
        policy,
        event_types=event_types or ["notification"],
        channels=[channel],
    )

    service.notification_policy = policy
    service.save()

    route = create_route(
        team,
        service=service,
        notification_channel_mode="service_policy",
    )

    return group, team, service, route, channel


def test_notify_alert_uses_service_policy_channel(monkeypatch, db):
    _, _, _, route, channel = _create_policy_route()
    alert_group = _create_alert_group(route)
    notifier = FakeNotifier()

    monkeypatch.setattr(
        "app.services.notifications.delivery.get_notifier",
        lambda channel_type: notifier,
    )

    assert notify_alert(alert_group, event_type="notification") == 1
    assert notifier.sent == [
        (channel.id, alert_group.id, "notification"),
    ]

    delivery = AlertNotification.get()
    assert delivery.channel_id == channel.id


def test_update_event_uses_notification_policy_rules(monkeypatch, db):
    _, _, _, route, channel = _create_policy_route(
        event_types=["notification"]
    )
    alert_group = _create_alert_group(route)
    notifier = FakeNotifier()

    monkeypatch.setattr(
        "app.services.notifications.delivery.get_notifier",
        lambda channel_type: notifier,
    )

    assert notify_alert(alert_group, event_type="update") == 1
    assert notifier.sent == [
        (channel.id, alert_group.id, "update"),
    ]


def test_channel_check_uses_requested_event_type(db):
    _, _, _, route, _ = _create_policy_route(event_types=["reminder"])
    alert_group = _create_alert_group(route)

    assert has_matching_notification_channel(alert_group) is False
    assert (
        has_matching_notification_channel(
            alert_group,
            event_type="reminder",
        )
        is True
    )


def test_existing_delivery_updates_after_policy_is_removed(
    monkeypatch,
    db,
):
    _, _, service, route, channel = _create_policy_route()
    alert_group = _create_alert_group(route)

    delivery = AlertNotification.create(
        group=alert_group,
        channel=channel,
        provider="fake",
        external_message_id="message-1",
        external_channel_id="channel-1",
        last_event_type="notification",
    )

    service.notification_policy = None
    service.save()

    notifier = FakeNotifier(supports_update=True)

    monkeypatch.setattr(
        "app.services.notifications.delivery.get_notifier",
        lambda channel_type: notifier,
    )

    assert update_alert_messages(alert_group, "resolved") == 1
    assert notifier.updated == [
        (
            channel.id,
            alert_group.id,
            "resolved",
            delivery.id,
        ),
    ]


def test_route_only_preserves_route_channel_delivery(monkeypatch, db):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    route_channel = create_channel(group, team, channel_type="fake")
    policy_channel = create_channel(group, team, channel_type="fake")

    policy = create_notification_policy(team)
    create_notification_policy_rule(policy, channels=[policy_channel])

    service.notification_policy = policy
    service.save()

    route = create_route(
        team,
        service=service,
        notification_channel_mode="route_only",
    )
    attach_channel(route, route_channel)

    alert_group = _create_alert_group(route)
    notifier = FakeNotifier()

    monkeypatch.setattr(
        "app.services.notifications.delivery.get_notifier",
        lambda channel_type: notifier,
    )

    assert notify_alert(alert_group, event_type="notification") == 1
    assert notifier.sent == [
        (route_channel.id, alert_group.id, "notification"),
    ]

    deliveries = list(AlertNotification.select())
    assert len(deliveries) == 1
    assert deliveries[0].channel_id == route_channel.id


def test_service_policy_plus_route_delivers_to_both_sources(monkeypatch, db):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    route_channel = create_channel(group, team, channel_type="fake")
    policy_channel = create_channel(group, team, channel_type="fake")

    policy = create_notification_policy(team)
    create_notification_policy_rule(policy, channels=[policy_channel])

    service.notification_policy = policy
    service.save()

    route = create_route(
        team,
        service=service,
        notification_channel_mode="service_policy_plus_route",
    )
    attach_channel(route, route_channel)

    alert_group = _create_alert_group(route)
    notifier = FakeNotifier()

    monkeypatch.setattr(
        "app.services.notifications.delivery.get_notifier",
        lambda channel_type: notifier,
    )

    assert notify_alert(alert_group, event_type="notification") == 2

    assert notifier.sent == [
        (policy_channel.id, alert_group.id, "notification"),
        (route_channel.id, alert_group.id, "notification"),
    ]

    delivery_channel_ids = {
        delivery.channel_id
        for delivery in AlertNotification.select()
    }

    assert delivery_channel_ids == {
        policy_channel.id,
        route_channel.id,
    }


def test_service_policy_plus_route_deduplicates_channel(monkeypatch, db):
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    channel = create_channel(group, team, channel_type="fake")

    policy = create_notification_policy(team)
    create_notification_policy_rule(policy, channels=[channel])

    service.notification_policy = policy
    service.save()

    route = create_route(
        team,
        service=service,
        notification_channel_mode="service_policy_plus_route",
    )
    attach_channel(route, channel)

    alert_group = _create_alert_group(route)
    notifier = FakeNotifier()

    monkeypatch.setattr(
        "app.services.notifications.delivery.get_notifier",
        lambda channel_type: notifier,
    )

    assert notify_alert(alert_group, event_type="notification") == 1
    assert notifier.sent == [
        (channel.id, alert_group.id, "notification"),
    ]
    assert AlertNotification.select().count() == 1


def test_service_policy_does_not_fallback_to_route_channels(monkeypatch, db):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    route_channel = create_channel(group, team, channel_type="fake")
    reminder_channel = create_channel(group, team, channel_type="fake")

    policy = create_notification_policy(team)
    create_notification_policy_rule(
        policy,
        event_types=["reminder"],
        channels=[reminder_channel],
    )

    service.notification_policy = policy
    service.save()

    route = create_route(
        team,
        service=service,
        notification_channel_mode="service_policy",
    )
    attach_channel(route, route_channel)

    alert_group = _create_alert_group(route)
    notifier = FakeNotifier()

    monkeypatch.setattr(
        "app.services.notifications.delivery.get_notifier",
        lambda channel_type: notifier,
    )

    assert notify_alert(alert_group, event_type="notification") == 0
    assert notifier.sent == []
    assert AlertNotification.select().count() == 0


def test_plus_route_uses_route_when_policy_does_not_match(monkeypatch, db):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    route_channel = create_channel(group, team, channel_type="fake")
    reminder_channel = create_channel(group, team, channel_type="fake")

    policy = create_notification_policy(team)
    create_notification_policy_rule(
        policy,
        event_types=["reminder"],
        channels=[reminder_channel],
    )

    service.notification_policy = policy
    service.save()

    route = create_route(
        team,
        service=service,
        notification_channel_mode="service_policy_plus_route",
    )
    attach_channel(route, route_channel)

    alert_group = _create_alert_group(route)
    notifier = FakeNotifier()

    monkeypatch.setattr(
        "app.services.notifications.delivery.get_notifier",
        lambda channel_type: notifier,
    )

    assert notify_alert(alert_group, event_type="notification") == 1
    assert notifier.sent == [
        (route_channel.id, alert_group.id, "notification"),
    ]


def test_reminder_delivery_uses_reminder_policy_rule(monkeypatch, db):
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    channel = create_channel(group, team, channel_type="fake")

    policy = create_notification_policy(team)
    create_notification_policy_rule(
        policy,
        event_types=["reminder"],
        channels=[channel],
    )

    service.notification_policy = policy
    service.save()

    route = create_route(
        team,
        service=service,
        notification_channel_mode="service_policy",
    )

    alert_group = _create_alert_group(route)
    notifier = FakeNotifier()

    monkeypatch.setattr(
        "app.services.notifications.delivery.get_notifier",
        lambda channel_type: notifier,
    )

    assert notify_alert(alert_group, event_type="reminder") == 1
    assert notifier.sent == [
        (channel.id, alert_group.id, "reminder"),
    ]
