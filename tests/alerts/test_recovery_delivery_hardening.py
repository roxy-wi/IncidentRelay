"""End-to-end persistent recovery retries across independent recipients."""

from datetime import timedelta

from app.modules.common import utc_now
from app.modules.db import notifications_repo
from app.modules.db.models import (
    AlertEvent, AlertGroup, RecoveryNotificationDelivery,
)
from app.services.alerts import lifecycle, notification_queue
from app.services.alerts.lifecycle import upsert_alert
from app.services.orchestration.runtime import RuntimeResult
from app.settings import Config
from tests.factories import (
    create_channel, create_group,
    create_route, create_team, create_user,
)


def signal(route, status="firing"):
    return {
        "source": "alertmanager", "forced_route_id": route.id,
        "external_id": "recovery-hardening",
        "dedup_key": "recovery-hardening",
        "title": "DiskFull", "severity": "critical", "status": status,
        "labels": {"alertname": "DiskFull"}, "payload": {},
    }


def setup_recovery(db, monkeypatch, *, channels=2):
    monkeypatch.setattr(Config, "RECOVERY_NOTIFICATION_DELAY_SECONDS", 60)
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager", group_by=["alertname"])
    monkeypatch.setattr(
        lifecycle, "run_event_orchestration",
        lambda data, trace=None: RuntimeResult(grouping_reopen_window_seconds=120),
    )
    first = upsert_alert(signal(route))
    alert_group = AlertGroup.get_by_id(first.group.id)
    alert_group.last_notification_at = utc_now()
    alert_group.save(only=[AlertGroup.last_notification_at])
    channel_rows = []
    for i in range(channels):
        channel = create_channel(group, team)
        notifications_repo.save_notification(
            group_id=alert_group.id, channel_id=channel.id,
            provider="webhook", event_type="notification",
            external_message_id=f"initial-{i}", provider_status="sent",
        )
        channel_rows.append(channel)
    upsert_alert(signal(route, "resolved"))
    return route, alert_group, channel_rows


def force_due(group):
    at = utc_now() - timedelta(seconds=1)
    AlertGroup.update(notification_due_at=at).where(AlertGroup.id == group.id).execute()
    RecoveryNotificationDelivery.update(next_attempt_at=at).where(
        (RecoveryNotificationDelivery.group == group.id)
        & (RecoveryNotificationDelivery.status == "pending")
    ).execute()


def events(group, kind):
    return AlertEvent.select().where(
        (AlertEvent.group == group.id) & (AlertEvent.event_type == kind)
    ).count()


def attempts(group):
    return list(RecoveryNotificationDelivery.select().where(
        RecoveryNotificationDelivery.group == group.id
    ))


def test_failed_channel_retried_without_resending_success(db, monkeypatch):
    route, group, channels = setup_recovery(db, monkeypatch, channels=2)
    first_id, retry_id = [c.id for c in channels]
    calls = []

    class FakeNotifier:
        @staticmethod
        def can_update(channel, delivery):
            return False
        @staticmethod
        def send(channel, current, message, event_type=None):
            calls.append(channel.id)
            if channel.id == retry_id and calls.count(retry_id) == 1:
                raise RuntimeError("transient provider failure")
            return {"provider": "fake", "provider_status": "sent"}

    monkeypatch.setattr(
        "app.services.notifications.delivery.get_notifier", lambda kind: FakeNotifier(),
    )
    force_due(group)
    result = notification_queue.process_due_alert_group_notifications()
    assert result["failed"] == 1
    assert AlertGroup.get_by_id(group.id).notification_pending
    assert calls.count(first_id) == 1
    assert calls.count(retry_id) == 1
    states = {row.target_id: row.status for row in attempts(group)}
    assert states[first_id] == "sent"
    assert states[retry_id] == "pending"
    assert events(group, "recovery_notification_retry_scheduled") == 1

    # Simulate a scheduler process reconnect before the retry. Successful
    # recipient acknowledgements must survive a new database connection.
    db.close()
    db.connect(reuse_if_open=True)
    force_due(group)
    result = notification_queue.process_due_alert_group_notifications()
    assert result["sent"] == 1
    assert calls.count(first_id) == 1
    assert calls.count(retry_id) == 2
    assert not AlertGroup.get_by_id(group.id).notification_pending
    assert events(group, "recovery_notification_sent") == 1
    assert notification_queue.process_due_alert_group_notifications()["processed"] == 0


def test_recovery_delivery_does_not_fan_out_to_incident_stakeholders(db, monkeypatch):
    """Technical recovery retries must not invoke Incident stakeholder transports."""
    _route, group, _channels = setup_recovery(db, monkeypatch, channels=0)
    force_due(group)
    result = notification_queue.process_due_alert_group_notifications()
    assert result["processed"] == 1
    assert result["sent"] == 0
    assert result["skipped"] == 1
    assert events(group, "recovery_notification_skipped") == 1
    assert attempts(group) == []


def test_all_failed_channels_stop_after_bounded_retries(db, monkeypatch):
    route, group, channels = setup_recovery(db, monkeypatch, channels=1)
    calls = []

    class FailingNotifier:
        @staticmethod
        def can_update(channel, delivery):
            return False
        @staticmethod
        def send(channel, current, message, event_type=None):
            calls.append(channel.id)
            raise RuntimeError("permanent failure")

    monkeypatch.setattr(
        "app.services.notifications.delivery.get_notifier", lambda kind: FailingNotifier(),
    )
    for _i in range(notification_queue.RECOVERY_MAX_ATTEMPTS):
        force_due(group)
        result = notification_queue.process_due_alert_group_notifications()
        assert result["failed"] == 1
    assert calls == [channels[0].id] * notification_queue.RECOVERY_MAX_ATTEMPTS
    final = AlertGroup.get_by_id(group.id)
    assert not final.notification_pending
    assert events(group, "recovery_delivery_exhausted") == 1
    assert events(group, "recovery_notification_failed") == 1
    assert [d.status for d in attempts(group)] == ["failed"]


def test_reopen_cancels_only_old_cycle_retry(db, monkeypatch):
    route, group, channels = setup_recovery(db, monkeypatch, channels=1)
    class FailingNotifier:
        @staticmethod
        def can_update(channel, delivery):
            return False
        @staticmethod
        def send(channel, current, message, event_type=None):
            raise RuntimeError("transient")

    monkeypatch.setattr(
        "app.services.notifications.delivery.get_notifier", lambda kind: FailingNotifier(),
    )
    force_due(group)
    assert notification_queue.process_due_alert_group_notifications()["failed"] == 1
    old_cycle = AlertGroup.get_by_id(group.id).resolved_at
    assert [d.status for d in attempts(group)] == ["pending"]
    assert upsert_alert(signal(route)).outcome == "reopened"
    assert not AlertGroup.get_by_id(group.id).notification_pending or AlertGroup.get_by_id(group.id).notification_reason != "recovery"
    assert [d.status for d in attempts(group)] == ["cancelled"]
    assert attempts(group)[0].resolved_at == old_cycle
    assert notification_queue.process_due_alert_group_notifications()["sent"] == 0
    # Source resolution in a later cycle generates an independent recipient set.
    again = AlertGroup.get_by_id(group.id)
    again.last_notification_at = utc_now()
    again.save(only=[AlertGroup.last_notification_at])
    upsert_alert(signal(route, "resolved"))
    force_due(group)
    monkeypatch.setattr(
        "app.services.notifications.delivery.get_notifier",
        lambda kind: type("Notifier", (), {
            "can_update": staticmethod(lambda *args: False),
            "send": staticmethod(lambda *args, **kwargs: {"provider": "fake"}),
        })(),
    )
    assert notification_queue.process_due_alert_group_notifications()["sent"] == 1
    rows = attempts(group)
    assert len(rows) == 2
    assert sorted(r.status for r in rows) == ["cancelled", "sent"]


def test_user_rule_fanout_is_not_requeued_when_channel_retries(db, monkeypatch):
    route, group, channels = setup_recovery(db, monkeypatch, channels=1)
    user = create_user(group=route.team.group, email="assignee@example.com")
    alert_group = AlertGroup.get_by_id(group.id)
    alert_group.assignee = user
    alert_group.save(only=[AlertGroup.assignee])
    calls = []
    monkeypatch.setattr(
        "app.services.notifications.rules.enqueue_user_notifications",
        lambda current, event_type: calls.append((current.id, event_type)) or 0,
    )

    send_count = []
    class Notifier:
        @staticmethod
        def can_update(channel, delivery):
            return False
        @staticmethod
        def send(channel, current, message, event_type=None):
            send_count.append(channel.id)
            if len(send_count) == 1:
                raise RuntimeError("temporary")
            return {"provider": "fake"}

    monkeypatch.setattr(
        "app.services.notifications.delivery.get_notifier", lambda kind: Notifier(),
    )
    force_due(group)
    assert notification_queue.process_due_alert_group_notifications()["failed"] == 1
    force_due(group)
    assert notification_queue.process_due_alert_group_notifications()["sent"] == 1
    assert calls == [(group.id, "resolved")]
    assert send_count == [channels[0].id, channels[0].id]


def test_recovery_delivery_storage_is_unique_per_occurrence_target(db):
    from peewee import IntegrityError
    import pytest

    assert db.table_exists(RecoveryNotificationDelivery._meta.table_name)
    group = create_group()
    team = create_team(group)
    route = create_route(team)
    first = upsert_alert(signal(route))
    now = utc_now()
    values = dict(
        group=first.group.id, resolved_at=now,
        target_kind="channel", target_id=123, next_attempt_at=now,
    )
    RecoveryNotificationDelivery.create(**values)
    with pytest.raises(IntegrityError):
        RecoveryNotificationDelivery.create(**values)


def test_partial_recovery_completion_is_reported_as_failure(db, monkeypatch):
    route, group, channels = setup_recovery(db, monkeypatch, channels=2)
    ok_id, failed_id = (c.id for c in channels)
    calls = []

    class Notifier:
        @staticmethod
        def can_update(channel, delivery):
            return False
        @staticmethod
        def send(channel, current, message, event_type=None):
            calls.append(channel.id)
            if channel.id == failed_id:
                raise RuntimeError("permanent provider error")
            return {"provider": "fake"}

    monkeypatch.setattr(
        "app.services.notifications.delivery.get_notifier", lambda kind: Notifier(),
    )
    for _ in range(notification_queue.RECOVERY_MAX_ATTEMPTS):
        force_due(group)
        outcome = notification_queue.process_due_alert_group_notifications()
        assert outcome["failed"] == 1

    assert calls.count(ok_id) == 1
    assert calls.count(failed_id) == notification_queue.RECOVERY_MAX_ATTEMPTS
    assert not AlertGroup.get_by_id(group.id).notification_pending
    assert events(group, "recovery_notification_partial") == 1
    assert events(group, "recovery_notification_sent") == 0
