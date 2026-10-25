"""Release 2.4 crash/restart safety for the persistent recovery queue.

Provider delivery and the database commit cannot be atomic: a crash after a
remote success can cause a duplicate, but must never silently lose recovery.
"""

from datetime import timedelta

import pytest

from app.modules.common import utc_now
from app.modules.db import notifications_repo
from app.modules.db.models import AlertGroup, RecoveryNotificationDelivery
from app.services.alerts import lifecycle, notification_queue
from app.services.alerts.lifecycle import upsert_alert
from app.services.orchestration.runtime import RuntimeResult
from app.settings import Config
from tests.factories import create_channel, create_group, create_route, create_team


def _signal(route, status="firing"):
    return {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": "release-24-recovery",
        "dedup_key": "release-24-recovery",
        "title": "Database unavailable",
        "severity": "critical",
        "status": status,
        "labels": {"alertname": "DatabaseUnavailable"},
        "payload": {},
    }


def _due_recovery(monkeypatch, *, channel_count=1):
    monkeypatch.setattr(Config, "RECOVERY_NOTIFICATION_DELAY_SECONDS", 60)
    tenant = create_group()
    team = create_team(tenant)
    route = create_route(team, source="alertmanager", group_by=["alertname"])
    monkeypatch.setattr(
        lifecycle,
        "run_event_orchestration",
        lambda event, trace=None: RuntimeResult(grouping_reopen_window_seconds=120),
    )
    first = upsert_alert(_signal(route))
    group = AlertGroup.get_by_id(first.group.id)
    group.last_notification_at = utc_now()
    group.save(only=[AlertGroup.last_notification_at])

    channels = []
    for index in range(channel_count):
        channel = create_channel(tenant, team)
        notifications_repo.save_notification(
            group_id=group.id,
            channel_id=channel.id,
            provider="webhook",
            event_type="notification",
            provider_status="sent",
            external_message_id=f"initial-{index}",
        )
        channels.append(channel.id)

    upsert_alert(_signal(route, "resolved"))
    assert AlertGroup.get_by_id(group.id).notification_reason == "recovery"
    _force_due(group.id)
    return route, group.id, channels


def _force_due(group_id):
    previous = utc_now() - timedelta(seconds=1)
    AlertGroup.update(notification_due_at=previous).where(
        AlertGroup.id == group_id
    ).execute()
    RecoveryNotificationDelivery.update(next_attempt_at=previous).where(
        (RecoveryNotificationDelivery.group == group_id)
        & (RecoveryNotificationDelivery.status == "pending")
    ).execute()


def _send_success(calls):
    def deliver(group, *, event_type, channel_ids, enqueue_rules, report_channels):
        assert event_type == "resolved"
        assert enqueue_rules is False
        assert report_channels is True
        assert len(channel_ids) == 1
        channel_id = next(iter(channel_ids))
        calls.append(channel_id)
        return {
            "sent": 1,
            "channels": {channel_id: {"status": "sent"}},
        }

    return deliver


def test_crash_before_recipient_snapshot_leaves_recovery_retryable(db, monkeypatch):
    _route, group_id, channels = _due_recovery(monkeypatch)
    selected = AlertGroup.get_by_id(group_id)

    with monkeypatch.context() as crashing:
        def stop_before_snapshot(*args, **kwargs):
            raise SystemExit("worker killed before snapshot")

        crashing.setattr(
            notification_queue, "_snapshot_recovery_targets", stop_before_snapshot,
        )
        with pytest.raises(SystemExit, match="worker killed"):
            notification_queue._process_due_recovery(selected, now=utc_now())

    assert AlertGroup.get_by_id(group_id).notification_pending is True
    assert RecoveryNotificationDelivery.select().where(
        RecoveryNotificationDelivery.group == group_id
    ).count() == 0

    # A new scheduler process reconnects to the existing durable queue.
    db.close()
    db.connect(reuse_if_open=True)
    calls = []
    monkeypatch.setattr(notification_queue, "notify_alert", _send_success(calls))
    result = notification_queue.process_due_alert_group_notifications()
    assert result["sent"] == 1
    assert calls == channels
    assert AlertGroup.get_by_id(group_id).notification_pending is False


def test_crash_after_provider_success_is_at_least_once(db, monkeypatch):
    """The remote success may repeat after rollback; delivery is never lost."""
    _route, group_id, channels = _due_recovery(monkeypatch)
    calls = []
    monkeypatch.setattr(notification_queue, "notify_alert", _send_success(calls))
    real_attempt = notification_queue._try_recovery_target

    with monkeypatch.context() as crashing:
        def stop_after_send(group, delivery, *, now):
            real_attempt(group, delivery, now=now)
            raise SystemExit("crash before database commit")

        crashing.setattr(notification_queue, "_try_recovery_target", stop_after_send)
        with pytest.raises(SystemExit, match="crash before database commit"):
            notification_queue.process_due_alert_group_notifications()

    # The network side effect happened, but its DB transaction rolled back.
    assert calls == channels
    assert AlertGroup.get_by_id(group_id).notification_pending is True
    assert RecoveryNotificationDelivery.select().where(
        RecoveryNotificationDelivery.group == group_id
    ).count() == 0

    db.close()
    db.connect(reuse_if_open=True)
    assert notification_queue.process_due_alert_group_notifications()["sent"] == 1
    assert calls == channels * 2  # Documented at-least-once crash window.
    assert AlertGroup.get_by_id(group_id).notification_pending is False
    assert RecoveryNotificationDelivery.get().status == "sent"
    assert notification_queue.process_due_alert_group_notifications()["processed"] == 0


def test_worker_restart_retains_retry_deadline_and_completed_recipients(db, monkeypatch):
    _route, group_id, channels = _due_recovery(monkeypatch, channel_count=2)
    good_id, flaky_id = channels
    calls = []

    def flaky_send(group, *, event_type, channel_ids, **kwargs):
        channel_id = next(iter(channel_ids))
        calls.append(channel_id)
        if channel_id == flaky_id and calls.count(flaky_id) == 1:
            return {
                "sent": 0,
                "channels": {flaky_id: {"status": "failed", "error": "timeout"}},
            }
        return {"sent": 1, "channels": {channel_id: {"status": "sent"}}}

    monkeypatch.setattr(notification_queue, "notify_alert", flaky_send)
    assert notification_queue.process_due_alert_group_notifications()["failed"] == 1

    retry_due = AlertGroup.get_by_id(group_id).notification_due_at
    rows = list(RecoveryNotificationDelivery.select().where(
        RecoveryNotificationDelivery.group == group_id
    ))
    assert {row.target_id: row.status for row in rows} == {
        good_id: "sent", flaky_id: "pending",
    }
    assert {row.target_id: row.attempts for row in rows} == {
        good_id: 1, flaky_id: 1,
    }
    assert retry_due > utc_now()

    db.close()
    db.connect(reuse_if_open=True)
    assert AlertGroup.get_by_id(group_id).notification_due_at == retry_due
    assert notification_queue.process_due_alert_group_notifications()["processed"] == 0
    assert calls == [good_id, flaky_id]

    _force_due(group_id)
    assert notification_queue.process_due_alert_group_notifications()["sent"] == 1
    assert calls == [good_id, flaky_id, flaky_id]
    assert not AlertGroup.get_by_id(group_id).notification_pending


def test_stale_selected_row_cannot_override_new_retry_deadline(db, monkeypatch):
    _route, group_id, channels = _due_recovery(monkeypatch)
    stale_selection = AlertGroup.get_by_id(group_id)
    send_count = []

    def fail_one(group, *, channel_ids, **kwargs):
        send_count.extend(channel_ids)
        return {
            "sent": 0,
            "channels": {channels[0]: {"status": "failed", "error": "provider down"}},
        }

    monkeypatch.setattr(notification_queue, "notify_alert", fail_one)
    assert notification_queue._process_due_recovery(
        stale_selection, now=utc_now()
    ) == "retrying"
    next_due = AlertGroup.get_by_id(group_id).notification_due_at

    # A second worker selected the old due row before the first rescheduled.
    assert notification_queue._process_due_recovery(
        stale_selection, now=utc_now()
    ) == "skipped"
    assert AlertGroup.get_by_id(group_id).notification_due_at == next_due
    assert send_count == channels
    assert RecoveryNotificationDelivery.get().attempts == 1


def test_old_resolved_selection_cannot_send_in_second_recovery_cycle(db, monkeypatch):
    route, group_id, _channels = _due_recovery(monkeypatch)
    old_selection = AlertGroup.get_by_id(group_id)
    old_due = old_selection.notification_due_at

    assert upsert_alert(_signal(route)).outcome == "reopened"
    upsert_alert(_signal(route, "resolved"))
    fresh = AlertGroup.get_by_id(group_id)
    assert fresh.status == "resolved"
    assert fresh.notification_pending is True
    assert fresh.notification_due_at != old_due

    calls = []
    monkeypatch.setattr(notification_queue, "notify_alert", _send_success(calls))
    assert notification_queue._process_due_recovery(
        old_selection, now=utc_now()
    ) == "skipped"
    assert calls == []
    assert AlertGroup.get_by_id(group_id).notification_due_at == fresh.notification_due_at
