"""PostgreSQL concurrent recovery schedulers share the grouping/row fence."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest

from app.db import database_proxy
from app.modules.common import utc_now
from app.modules.db import notifications_repo
from app.modules.db.models import AlertGroup, RecoveryNotificationDelivery
from app.services.alerts import lifecycle, notification_queue
from app.services.alerts.lifecycle import upsert_alert
from app.services.orchestration.runtime import RuntimeResult
from app.settings import Config
from tests.factories import create_channel, create_group, create_route, create_team, unique

pytestmark = pytest.mark.postgresql


def test_two_workers_cannot_deliver_the_same_due_recovery_twice(db, monkeypatch):
    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("requires PostgreSQL")

    monkeypatch.setattr(Config, "RECOVERY_NOTIFICATION_DELAY_SECONDS", 60)
    tenant = create_group()
    team = create_team(tenant)
    route = create_route(team, source="alertmanager", group_by=["alertname"])
    monkeypatch.setattr(
        lifecycle,
        "run_event_orchestration",
        lambda event, trace=None: RuntimeResult(grouping_reopen_window_seconds=120),
    )
    key = unique("worker-race")
    data = {
        "source": "alertmanager", "forced_route_id": route.id,
        "external_id": key, "dedup_key": key,
        "title": "Database unavailable", "severity": "critical",
        "status": "firing", "labels": {"alertname": "DatabaseUnavailable"},
        "payload": {},
    }
    group_id = upsert_alert(dict(data)).group.id
    group = AlertGroup.get_by_id(group_id)
    group.last_notification_at = utc_now()
    group.save(only=[AlertGroup.last_notification_at])
    channel = create_channel(tenant, team)
    notifications_repo.save_notification(
        group_id=group_id, channel_id=channel.id, provider="webhook",
        event_type="notification", provider_status="sent",
    )
    upsert_alert(dict(data, status="resolved"))
    AlertGroup.update(
        notification_due_at=utc_now() - timedelta(seconds=1),
    ).where(AlertGroup.id == group_id).execute()
    selection = AlertGroup.get_by_id(group_id)

    inside_provider = Event()
    finish_provider = Event()
    provider_calls = []

    def slow_provider(current, *, event_type, channel_ids, **kwargs):
        inside_provider.set()
        assert finish_provider.wait(timeout=15)
        provider_calls.append((current.id, event_type, tuple(channel_ids)))
        return {
            "sent": 1,
            "channels": {channel.id: {"status": "sent"}},
        }

    monkeypatch.setattr(notification_queue, "notify_alert", slow_provider)

    def worker():
        with database_proxy.obj.connection_context():
            return notification_queue._process_due_recovery(selection, now=utc_now())

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(worker)
        try:
            assert inside_provider.wait(timeout=15)
            second = pool.submit(worker)
        finally:
            finish_provider.set()
        assert sorted((first.result(timeout=30), second.result(timeout=30))) == [
            "sent", "skipped",
        ]

    assert provider_calls == [(group_id, "resolved", (channel.id,))]
    assert RecoveryNotificationDelivery.get().status == "sent"
    assert not AlertGroup.get_by_id(group_id).notification_pending


def test_reclaimer_waits_for_inflight_resolved_user_delivery(db, monkeypatch):
    """A slow provider with the group lock held cannot be paged twice."""
    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("requires PostgreSQL")

    from app.modules.db.models import UserNotificationDelivery
    from app.services.notifications import rules
    from tests.factories import create_user

    tenant = create_group()
    team = create_team(tenant)
    recipient = create_user(group=tenant)
    route = create_route(team, source="alertmanager", group_by=["alertname"])
    key = unique("reclaim-race")
    group_id = upsert_alert({
        "source": "alertmanager", "forced_route_id": route.id,
        "external_id": key, "dedup_key": key,
        "title": "Database unavailable", "severity": "critical",
        "status": "firing", "labels": {"alertname": "DatabaseUnavailable"},
        "payload": {},
    }).group.id
    group = AlertGroup.get_by_id(group_id)
    group.assignee = recipient
    group.status = "resolved"
    group.resolved_at = utc_now() - timedelta(hours=3)
    group.save(only=[AlertGroup.assignee, AlertGroup.status, AlertGroup.resolved_at])
    old = utc_now() - timedelta(hours=2)
    delivery = UserNotificationDelivery.create(
        group=group_id,
        user=recipient.id,
        method=rules.NOTIFICATION_METHOD_EMAIL,
        event_type="resolved",
        status="processing",
        scheduled_at=old,
        created_at=old,
        updated_at=utc_now() - timedelta(hours=1),
    )

    inside_provider = Event()
    finish_provider = Event()
    reclaimer_started = Event()
    calls = []

    class SlowNotifier:
        @staticmethod
        def send(channel, alert_group, text, event_type="notification"):
            inside_provider.set()
            assert finish_provider.wait(timeout=15)
            calls.append(alert_group.id)
            return {"provider": "email", "provider_status": "sent"}

    monkeypatch.setitem(
        rules.DIRECT_NOTIFIERS, rules.NOTIFICATION_METHOD_EMAIL, SlowNotifier(),
    )

    def send_inflight():
        with database_proxy.obj.connection_context():
            return rules.send_delivery(delivery, already_claimed=True)

    def reclaim():
        with database_proxy.obj.connection_context():
            reclaimer_started.set()
            return rules.reclaim_abandoned_resolved_deliveries()

    with ThreadPoolExecutor(max_workers=2) as pool:
        sending = pool.submit(send_inflight)
        try:
            assert inside_provider.wait(timeout=15)
            reclamation = pool.submit(reclaim)
            assert reclaimer_started.wait(timeout=15)
        finally:
            finish_provider.set()
        assert sending.result(timeout=30) == 1
        assert reclamation.result(timeout=30) == 0

    assert UserNotificationDelivery.get_by_id(delivery.id).status == "sent"
    assert calls == [group_id]
    assert rules.process_due_user_notifications() == 0
