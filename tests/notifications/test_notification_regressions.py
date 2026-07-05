from datetime import datetime, timedelta

from app.db import init_database
from app.modules.db.models import AlertEvent, AlertGroup, UserNotificationDelivery
from app.services.alerts.lifecycle import upsert_alert
import app.services.alerts.notification_queue as notification_queue
import app.services.alerts.reminders as alert_reminders
from app.services.notifications import delivery as notification_service
from app.services.notifications import rules as notification_rules
from app.services.notifications.policies.resolver import resolve_notification_channels
from tests.factories import (
    create_channel,
    create_group,
    create_notification_policy,
    create_notification_policy_rule,
    create_route,
    create_service,
    create_team,
    create_user,
)


def _create_alert_route(*, rotation=None):
    group = create_group()
    team = create_team(group)
    route = create_route(
        team,
        source="alertmanager",
        rotation=rotation,
        group_by=["alertname", "severity", "instance"],
    )
    return group, team, route


def _create_firing_alert_group(route, *, dedup_key, instance="host1"):
    result = upsert_alert(
        {
            "source": "alertmanager",
            "forced_route_id": route.id,
            "external_id": f"external-{dedup_key}",
            "dedup_key": dedup_key,
            "title": "DiskFull",
            "message": f"/var is 95% full on {instance}",
            "severity": "critical",
            "labels": {
                "alertname": "DiskFull",
                "severity": "critical",
                "instance": instance,
            },
            "payload": {},
            "status": "firing",
        }
    )

    alert_group = result.group
    created = result.created_group

    assert alert_group is not None
    assert created is True

    return alert_group


def test_due_group_notification_without_delivery_target_is_skipped(db, monkeypatch):
    group, team, route = _create_alert_route()
    alert_group = _create_firing_alert_group(
        route,
        dedup_key="dedup-due-no-target",
    )

    alert_group.notification_pending = True
    alert_group.notification_due_at = datetime.utcnow() - timedelta(seconds=1)
    alert_group.notification_reason = "notification"
    alert_group.last_notification_at = None
    alert_group.status = "firing"
    alert_group.save()

    monkeypatch.setattr(
        notification_queue.alerts_repo,
        "list_due_alert_group_notifications",
        lambda now=None, limit=100: [AlertGroup.get_by_id(alert_group.id)],
    )

    calls = []
    monkeypatch.setattr(
        notification_queue,
        "notify_alert",
        lambda group, event_type="notification": calls.append(
            (group.id, event_type)
        )
        or 0,
    )

    result = notification_queue.process_due_alert_group_notifications()
    alert_group = AlertGroup.get_by_id(alert_group.id)

    assert result["processed"] == 1
    assert result["sent"] == 0
    assert result["skipped"] == 1
    assert result["failed"] == 0
    assert calls == [(alert_group.id, "notification")]
    assert alert_group.notification_pending is False
    assert alert_group.notification_due_at is None
    assert alert_group.notification_reason is None
    assert alert_group.last_notification_at is None

    event = AlertEvent.get(
        (AlertEvent.group == alert_group.id)
        & (AlertEvent.event_type == "notification_skipped")
    )
    assert event.message == "Due alert group notification skipped: no delivery target"


def test_due_group_update_without_delivery_target_does_not_change_last_notification_at(
    db,
    monkeypatch,
):
    group, team, route = _create_alert_route()
    alert_group = _create_firing_alert_group(
        route,
        dedup_key="dedup-due-update-no-target",
    )

    previous_notification_at = datetime.utcnow() - timedelta(minutes=10)

    alert_group.notification_pending = True
    alert_group.notification_due_at = datetime.utcnow() - timedelta(seconds=1)
    alert_group.notification_reason = "update"
    alert_group.last_notification_at = previous_notification_at
    alert_group.status = "firing"
    alert_group.save()

    monkeypatch.setattr(
        notification_queue.alerts_repo,
        "list_due_alert_group_notifications",
        lambda now=None, limit=100: [AlertGroup.get_by_id(alert_group.id)],
    )

    calls = []
    monkeypatch.setattr(
        notification_queue,
        "notify_alert",
        lambda group, event_type="update": calls.append((group.id, event_type)) or 0,
    )

    result = notification_queue.process_due_alert_group_notifications()
    alert_group = AlertGroup.get_by_id(alert_group.id)

    assert result["processed"] == 1
    assert result["sent"] == 0
    assert result["skipped"] == 1
    assert result["failed"] == 0
    assert calls == [(alert_group.id, "update")]
    assert alert_group.notification_pending is False
    assert alert_group.notification_due_at is None
    assert alert_group.notification_reason is None
    assert alert_group.last_notification_at == previous_notification_at

    event = AlertEvent.get(
        (AlertEvent.group == alert_group.id)
        & (AlertEvent.event_type == "update_skipped")
    )
    assert event.message == "Due alert group notification skipped: no delivery target"


def test_send_unacked_reminders_skips_group_with_pending_notification(db, monkeypatch):
    group, team, route = _create_alert_route()
    alert_group = _create_firing_alert_group(
        route,
        dedup_key="dedup-reminder-pending",
    )

    alert_group.status = "firing"
    alert_group.notification_pending = True
    alert_group.notification_due_at = datetime.utcnow() + timedelta(seconds=30)
    alert_group.notification_reason = "notification"
    alert_group.last_notification_at = datetime.utcnow() - timedelta(minutes=10)
    alert_group.reminder_count = 0
    alert_group.save()

    monkeypatch.setattr(
        alert_reminders.alerts_repo,
        "list_firing_alert_groups",
        lambda: [AlertGroup.get_by_id(alert_group.id)],
    )
    monkeypatch.setattr(
        alert_reminders,
        "notify_alert",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("reminder must not be sent while notification is pending")
        ),
    )

    count = alert_reminders.send_unacked_reminders()
    alert_group = AlertGroup.get_by_id(alert_group.id)

    assert count == 0
    assert alert_group.reminder_count == 0
    assert not (
        AlertEvent.select()
        .where(
            (AlertEvent.group == alert_group.id)
            & (AlertEvent.event_type == "reminder_sent")
        )
        .exists()
    )


def test_send_unacked_reminders_skips_group_without_initial_notification(
    db,
    monkeypatch,
):
    group, team, route = _create_alert_route()
    alert_group = _create_firing_alert_group(
        route,
        dedup_key="dedup-reminder-no-initial-notification",
    )

    alert_group.status = "firing"
    alert_group.notification_pending = False
    alert_group.notification_due_at = None
    alert_group.notification_reason = None
    alert_group.last_notification_at = None
    alert_group.reminder_count = 0
    alert_group.save()

    monkeypatch.setattr(
        alert_reminders.alerts_repo,
        "list_firing_alert_groups",
        lambda: [AlertGroup.get_by_id(alert_group.id)],
    )
    monkeypatch.setattr(
        alert_reminders,
        "notify_alert",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("reminder must not be sent before initial notification")
        ),
    )

    count = alert_reminders.send_unacked_reminders()
    alert_group = AlertGroup.get_by_id(alert_group.id)

    assert count == 0
    assert alert_group.reminder_count == 0
    assert not (
        AlertEvent.select()
        .where(
            (AlertEvent.group == alert_group.id)
            & (AlertEvent.event_type == "reminder_sent")
        )
        .exists()
    )


def test_notify_alert_creates_user_notification_delivery_with_group_id(
    db,
    monkeypatch,
):
    group = create_group()
    team = create_team(group)
    user = create_user("alice", group)
    route = create_route(
        team,
        source="alertmanager",
        group_by=["alertname", "severity", "instance"],
    )
    alert_group = _create_firing_alert_group(
        route,
        dedup_key="dedup-user-delivery-group-id",
    )
    alert_group.assignee = user.id
    alert_group.status = "firing"
    alert_group.save()

    monkeypatch.setattr(
        notification_rules.browser_push,
        "send_alert_push_to_user",
        lambda assignee, group, event_type="notification": 1,
    )

    sent = notification_service.notify_alert(
        alert_group,
        event_type="notification",
    )

    assert sent == 1

    delivery = UserNotificationDelivery.get(
        UserNotificationDelivery.group == alert_group.id
    )

    assert delivery.group_id == alert_group.id
    assert delivery.user_id == user.id
    assert delivery.method == "browser_push"
    assert delivery.event_type == "notification"
    assert delivery.status == "sent"
    assert delivery.provider == "browser_push"
    assert getattr(delivery, "alert_id", None) is None


def test_legacy_alert_id_columns_are_nullable_or_removed(db):
    user_delivery_alert_id = _get_column(
        "user_notification_delivery",
        "alert_id",
    )
    user_delivery_group_id = _get_column(
        "user_notification_delivery",
        "group_id",
    )
    push_token_alert_id = _get_column(
        "browser_push_action_token",
        "alert_id",
    )
    push_token_group_id = _get_column(
        "browser_push_action_token",
        "group_id",
    )

    assert user_delivery_group_id is not None
    assert user_delivery_group_id.null is False
    assert push_token_group_id is not None
    assert push_token_group_id.null is False

    if user_delivery_alert_id is not None:
        assert user_delivery_alert_id.null is True

    if push_token_alert_id is not None:
        assert push_token_alert_id.null is True


def _get_column(table_name, column_name):
    database = init_database()

    if table_name not in database.get_tables():
        return None

    for column in database.get_columns(table_name):
        if column.name == column_name:
            return column

    return None


def test_route_less_group_uses_service_notification_policy(db):
    group = create_group()
    team = create_team(group)

    channel = create_channel(group, team=team)
    policy = create_notification_policy(team)
    create_notification_policy_rule(
        policy,
        event_types=["notification"],
        channels=[channel],
    )

    service = create_service(team)
    service.notification_policy = policy
    service.save()

    alert_group = AlertGroup.create(
        team=team,
        route=None,
        service=service,
        source="manual",
        group_key="manual-route-less-policy",
        group_key_hash="manual-route-less-policy",
        title="Manual incident",
        message="Created by user",
        severity="critical",
        status="firing",
        alert_count=1,
        firing_count=1,
    )

    resolution = resolve_notification_channels(
        alert_group,
        event_type="notification",
    )

    assert resolution.mode == "service_policy"
    assert channel in resolution.channels
    assert resolution.service_id == service.id
    assert resolution.policy_id == policy.id
    assert "route_missing" in resolution.notes
    assert "service_policy_without_route" in resolution.notes


def test_due_route_less_group_notification_uses_service_policy(db, monkeypatch):
    group = create_group()
    team = create_team(group)

    channel = create_channel(group, team=team)
    policy = create_notification_policy(team)
    create_notification_policy_rule(
        policy,
        event_types=["notification"],
        channels=[channel],
    )

    service = create_service(team)
    service.notification_policy = policy
    service.save()

    alert_group = AlertGroup.create(
        team=team,
        route=None,
        service=service,
        source="manual",
        group_key="manual-route-less-due",
        group_key_hash="manual-route-less-due",
        title="Manual incident",
        message="Created by user",
        severity="critical",
        status="firing",
        alert_count=1,
        firing_count=1,
        notification_pending=True,
        notification_due_at=datetime.utcnow() - timedelta(seconds=1),
        notification_reason="notification",
        last_notification_at=None,
    )

    monkeypatch.setattr(
        notification_queue.alerts_repo,
        "list_due_alert_group_notifications",
        lambda now=None, limit=100: [AlertGroup.get_by_id(alert_group.id)],
    )

    sent_calls = []

    class DummyNotifier:
        def send(self, channel_arg, group_arg, text, event_type="notification"):
            sent_calls.append({
                "channel_id": channel_arg.id,
                "group_id": group_arg.id,
                "text": text,
                "event_type": event_type,
            })
            return {
                "provider": channel_arg.channel_type,
                "external_message_id": "manual-message-1",
                "external_channel_id": "manual-channel-1",
                "provider_status": "sent",
                "provider_payload": {},
            }

        def can_update(self, channel_arg, delivery):
            return False

    monkeypatch.setattr(
        notification_service,
        "get_notifier",
        lambda channel_type: DummyNotifier(),
    )

    result = notification_queue.process_due_alert_group_notifications()

    assert result["processed"] == 1
    assert result["sent"] == 1
    assert result["skipped"] == 0
    assert sent_calls == [
        {
            "channel_id": channel.id,
            "group_id": alert_group.id,
            "text": sent_calls[0]["text"],
            "event_type": "notification",
        }
    ]
    assert "NOTIFICATION:" in sent_calls[0]["text"]
    assert "Manual incident" in sent_calls[0]["text"]
    assert "Service:" in sent_calls[0]["text"]
    assert "Source: manual" in sent_calls[0]["text"]

    alert_group = AlertGroup.get_by_id(alert_group.id)
    assert alert_group.notification_pending is False
    assert alert_group.last_notification_at is not None
