"""Recovery hysteresis: source resolution is immediate; delivery may be delayed."""

from datetime import timedelta

import pytest

from app.modules.common import utc_now
from app.modules.db.models import Alert, AlertEvent, AlertGroup
from app.modules.db import notifications_repo
from app.services.alerts import lifecycle, notification_queue
from app.services.alerts.actions import resolve_alert
from app.services.alerts.lifecycle import upsert_alert
from app.services.orchestration.runtime import RuntimeResult
from app.settings import Config
from tests.factories import (
    create_channel, create_group, create_route, create_team,
    create_user, create_incident_stakeholder,
)


@pytest.fixture
def route(db, monkeypatch):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager", group_by=["alertname"])
    monkeypatch.setattr(
        lifecycle, "run_event_orchestration",
        lambda event, trace=None: RuntimeResult(grouping_reopen_window_seconds=120),
    )
    return route


def signal(route, status="firing"):
    return {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": "hysteresis-unique-id",
        "dedup_key": "hysteresis-unique-id",
        "title": "DiskFull",
        "message": "Root disk is full",
        "severity": "critical",
        "status": status,
        "labels": {"alertname": "DiskFull"},
        "payload": {},
    }


def delivered_channel(group, route):
    channel = create_channel(route.team.group, route.team)
    notifications_repo.save_notification(
        group_id=group.id, channel_id=channel.id,
        provider="webhook", event_type="notification",
        provider_status="sent", external_message_id="initial",
    )
    return channel


def send_channel_success(calls):
    def deliver(current, event_type="resolved", **kwargs):
        ids = set(kwargs.get("channel_ids", []))
        calls.append((current.id, event_type, ids))
        return {"sent": len(ids), "channels": {
            channel_id: {"status": "sent"} for channel_id in ids
        }}
    return deliver


def count_events(group_id, event_type):
    return AlertEvent.select().where(
        AlertEvent.group == group_id,
        AlertEvent.event_type == event_type,
    ).count()


def test_recovery_grace_disabled_preserves_immediate_delivery(route, monkeypatch):
    monkeypatch.setattr(Config, "RECOVERY_NOTIFICATION_DELAY_SECONDS", 0)
    first = upsert_alert(signal(route))
    current = AlertGroup.get_by_id(first.group.id)
    current.last_notification_at = utc_now()
    current.save(only=[AlertGroup.last_notification_at])

    delivered = []
    monkeypatch.setattr(
        lifecycle, "notify_alert",
        lambda group, event_type=None: delivered.append(event_type) or 1,
    )
    stakeholder = []
    monkeypatch.setattr(
        lifecycle, "notify_stakeholders",
        lambda group, event_type, **kwargs: stakeholder.append(event_type),
    )

    resolved = upsert_alert(signal(route, status="resolved"))
    assert resolved.group.status == "resolved"
    assert delivered == ["resolved"]
    assert stakeholder == ["resolved"]
    assert not AlertGroup.get_by_id(first.group.id).notification_pending
    assert count_events(first.group.id, "recovery_notification_scheduled") == 0


def test_recovery_is_deferred_and_due_process_sends_once(route, monkeypatch):
    monkeypatch.setattr(Config, "RECOVERY_NOTIFICATION_DELAY_SECONDS", 300)
    first = upsert_alert(signal(route))
    group = AlertGroup.get_by_id(first.group.id)
    group.last_notification_at = utc_now()
    group.save(only=[AlertGroup.last_notification_at])
    channel = delivered_channel(group, route)

    immediate_calls = []
    monkeypatch.setattr(
        lifecycle, "notify_alert", lambda *a, **kw: immediate_calls.append("alert"),
    )
    monkeypatch.setattr(
        lifecycle, "notify_stakeholders", lambda *a, **kw: immediate_calls.append("stakeholder"),
    )

    resolved = upsert_alert(signal(route, status="resolved"))
    group = AlertGroup.get_by_id(first.group.id)
    assert resolved.group.status == "resolved"
    assert Alert.get_by_id(first.alert.id).status == "resolved"
    assert group.notification_pending
    assert group.notification_reason == "recovery"
    assert group.notification_due_at > utc_now()
    assert immediate_calls == []
    assert count_events(group.id, "recovery_notification_scheduled") == 1
    assert notification_queue.process_due_alert_group_notifications()["sent"] == 0

    # Deliberate replay of the same source recovery must not extend the due time.
    saved_due = group.notification_due_at
    upsert_alert(signal(route, status="resolved"))
    assert AlertGroup.get_by_id(group.id).notification_due_at == saved_due
    assert count_events(group.id, "recovery_notification_scheduled") == 1

    delivery = []
    monkeypatch.setattr(
        notification_queue, "notify_alert", send_channel_success(delivery),
    )
    AlertGroup.update(notification_due_at=utc_now() - timedelta(seconds=1)).where(
        AlertGroup.id == group.id,
    ).execute()

    result = notification_queue.process_due_alert_group_notifications()
    assert result["processed"] == 1
    assert result["sent"] == 1
    assert delivery == [(group.id, "resolved", {channel.id})]
    assert count_events(group.id, "recovery_notification_sent") == 1
    assert not AlertGroup.get_by_id(group.id).notification_pending
    assert notification_queue.process_due_alert_group_notifications()["sent"] == 0
    assert len(delivery) == 1


def test_reopen_cancels_queued_recovery_without_mutating_old_child(route, monkeypatch):
    monkeypatch.setattr(Config, "RECOVERY_NOTIFICATION_DELAY_SECONDS", 300)
    first = upsert_alert(signal(route))
    upsert_alert(signal(route, status="resolved"))
    group = AlertGroup.get_by_id(first.group.id)
    assert group.notification_pending

    reopened = upsert_alert(signal(route))
    assert reopened.outcome == "reopened"
    assert reopened.group.id == group.id
    assert reopened.alert.id != first.alert.id
    assert Alert.get_by_id(first.alert.id).status == "resolved"
    assert count_events(group.id, "recovery_notification_cancelled") == 1

    refreshed = AlertGroup.get_by_id(group.id)
    assert refreshed.status == "firing"
    assert refreshed.notification_reason != "recovery"
    assert notification_queue.process_due_alert_group_notifications()["sent"] == 0


def test_scheduler_ignores_expired_recovery_after_group_state_changes(route, monkeypatch):
    monkeypatch.setattr(Config, "RECOVERY_NOTIFICATION_DELAY_SECONDS", 10)
    first = upsert_alert(signal(route))
    upsert_alert(signal(route, status="resolved"))
    # Stale recovery selected by a worker prior to a state transition.
    selected = AlertGroup.get_by_id(first.group.id)
    selected.notification_due_at = utc_now() - timedelta(seconds=1)
    selected.save(only=[AlertGroup.notification_due_at])
    snapshot = AlertGroup.get_by_id(first.group.id)

    upsert_alert(signal(route))

    deliveries = []
    monkeypatch.setattr(
        notification_queue, "notify_alert",
        lambda *a, **kw: deliveries.append(1) or 1,
    )
    assert notification_queue._process_due_recovery(snapshot, now=utc_now()) == "skipped"
    assert deliveries == []


def test_retry_when_worker_crashes_keeps_recovery_pending(route, monkeypatch):
    monkeypatch.setattr(Config, "RECOVERY_NOTIFICATION_DELAY_SECONDS", 5)
    first = upsert_alert(signal(route))
    group = AlertGroup.get_by_id(first.group.id)
    group.last_notification_at = utc_now()
    group.save(only=[AlertGroup.last_notification_at])
    delivered_channel(group, route)
    upsert_alert(signal(route, status="resolved"))
    AlertGroup.update(notification_due_at=utc_now() - timedelta(seconds=1)).where(
        AlertGroup.id == group.id,
    ).execute()

    monkeypatch.setattr(
        notification_queue, "notify_alert",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("transient")),
    )
    result = notification_queue.process_due_alert_group_notifications()
    assert result["failed"] == 1
    assert AlertGroup.get_by_id(group.id).notification_pending
    assert count_events(group.id, "recovery_notification_sent") == 0


def test_no_delivered_firing_still_defers_stakeholder_recovery(route, monkeypatch):
    monkeypatch.setattr(Config, "RECOVERY_NOTIFICATION_DELAY_SECONDS", 20)
    first = upsert_alert(signal(route))
    upsert_alert(signal(route, status="resolved"))
    assert AlertGroup.get_by_id(first.group.id).last_notification_at is None
    AlertGroup.update(notification_due_at=utc_now() - timedelta(seconds=1)).where(
        AlertGroup.id == first.group.id,
    ).execute()

    stakeholder_user = create_user(group=route.team.group, email="stake@example.com")
    create_incident_stakeholder(first.group, stakeholder_user)
    delivered = []
    monkeypatch.setattr(
        notification_queue, "send_stakeholder_email",
        lambda *a: delivered.append("stakeholder"),
    )
    monkeypatch.setattr(notification_queue, "send_stakeholder_push", lambda *a, **kw: 0)
    result = notification_queue.process_due_alert_group_notifications()
    assert result["sent"] == 1
    assert delivered == ["stakeholder"]


def test_manual_resolve_remains_immediate(route, monkeypatch):
    monkeypatch.setattr(Config, "RECOVERY_NOTIFICATION_DELAY_SECONDS", 300)
    first = upsert_alert(signal(route))
    calls = []
    monkeypatch.setattr(
        "app.services.alerts.actions.update_alert_messages",
        lambda group, event_type: calls.append("update"),
    )
    monkeypatch.setattr(
        "app.services.alerts.actions.notify_stakeholders",
        lambda group, event_type, **kw: calls.append("stakeholder"),
    )
    resolved = resolve_alert(first.group.id)
    assert resolved.status == "resolved"
    assert calls == ["update", "stakeholder"]
    assert not AlertGroup.get_by_id(first.group.id).notification_pending


@pytest.mark.parametrize("value,expected", [(0, 0), (-3, 0), (20, 20), (90000, 86400), ("oops", 0)])
def test_recovery_delay_is_bounded(monkeypatch, value, expected):
    monkeypatch.setattr(Config, "RECOVERY_NOTIFICATION_DELAY_SECONDS", value)
    assert notification_queue.recovery_notification_delay_seconds() == expected


def test_stale_firing_worker_does_not_clear_new_recovery(route, monkeypatch):
    monkeypatch.setattr(Config, "RECOVERY_NOTIFICATION_DELAY_SECONDS", 30)
    first = upsert_alert(signal(route))
    group = AlertGroup.get_by_id(first.group.id)
    snapshot = AlertGroup.get_by_id(group.id)
    snapshot.notification_due_at = utc_now() - timedelta(seconds=2)
    snapshot.notification_pending = True
    snapshot.notification_reason = "notification"
    snapshot.save(only=[
        AlertGroup.notification_pending,
        AlertGroup.notification_due_at,
        AlertGroup.notification_reason,
    ])
    stale_selected = AlertGroup.get_by_id(group.id)

    upsert_alert(signal(route, status="resolved"))
    assert AlertGroup.get_by_id(group.id).notification_reason == "recovery"

    monkeypatch.setattr(
        notification_queue.alerts_repo,
        "list_due_alert_group_notifications",
        lambda now=None, limit=100: [stale_selected],
    )
    result = notification_queue.process_due_alert_group_notifications()
    assert result["skipped"] == 1
    assert AlertGroup.get_by_id(group.id).notification_reason == "recovery"
    assert AlertGroup.get_by_id(group.id).notification_pending is True
