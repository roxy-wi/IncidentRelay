from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event, Lock

from flask import has_app_context
import pytest

from app.db import database_proxy
from app.modules.common import utc_now
from app.modules.db.models import AlertGroup
from app.services import scheduler
from app.services.alerts import notification_queue
from app.services.alerts.actions import acknowledge_alert
from app.services.alerts.lifecycle import upsert_alert
from app.settings import Config
from tests.factories import create_group, create_route, create_team, unique

pytestmark = pytest.mark.postgresql


@pytest.fixture
def due(db):
    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("requires PostgreSQL row claims")

    def create(count=1):
        tenant = create_group()
        route = create_route(create_team(tenant), source="webhook", group_by=["labels.host"])
        groups = []
        for _ in range(count):
            key = unique("parallel-delivery")
            groups.append(upsert_alert({
                "source": "webhook", "forced_route_id": route.id, "dedup_key": key,
                "title": "Test", "status": "firing", "severity": "critical",
                "labels": {"host": key}, "payload": {},
            }).group)
        AlertGroup.update(notification_pending=True, notification_reason="notification",
                          notification_due_at=utc_now() - timedelta(seconds=1)).where(
            AlertGroup.id.in_([group.id for group in groups])
        ).execute()
        return [AlertGroup.get_by_id(group.id) for group in groups]

    return create


def test_distinct_groups_deliver_in_parallel_with_app_context(app, due, monkeypatch):
    groups = due(4)
    barrier = Barrier(4)
    calls = []
    lock = Lock()
    monkeypatch.setattr(Config, "ALERT_GROUP_NOTIFICATION_WORKERS", 4)

    def provider(group, event_type="notification", **kwargs):
        assert has_app_context()
        barrier.wait(timeout=10)
        with lock:
            calls.append(group.id)
        return 1

    def no_global_lock(*args, **kwargs):
        raise AssertionError("PostgreSQL delivery must use per-group claims")

    monkeypatch.setattr(notification_queue, "notify_alert", provider)
    monkeypatch.setattr(scheduler, "acquire_db_lock", no_global_lock)
    with app.app_context():
        result = scheduler.alert_group_notification_job()
    assert result == {"processed": 4, "sent": 4, "skipped": 0, "failed": 0}
    assert sorted(calls) == sorted(group.id for group in groups)
    assert AlertGroup.select().where(AlertGroup.notification_pending == True).count() == 0  # noqa: E712


def test_two_schedulers_do_not_deliver_the_same_group(due, monkeypatch):
    selected = due()[0]
    inside = Event()
    finish = Event()
    calls = []
    monkeypatch.setattr(notification_queue.alerts_repo, "list_due_alert_group_notifications", lambda **kw: [selected])

    def provider(group, event_type="notification", **kwargs):
        calls.append(group.id)
        inside.set()
        assert finish.wait(timeout=10)
        return 1

    def worker():
        with database_proxy.obj.connection_context():
            return notification_queue.process_due_alert_group_notifications()

    monkeypatch.setattr(notification_queue, "notify_alert", provider)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(worker)
        try:
            assert inside.wait(timeout=10)
            second = pool.submit(worker)
            assert second.result(timeout=5)["skipped"] == 1
        finally:
            finish.set()
        assert first.result(timeout=10)["sent"] == 1
    assert calls == [selected.id]


def test_acknowledged_stale_selection_is_not_sent(due, monkeypatch):
    selected = due()[0]
    acknowledge_alert(selected.id)
    monkeypatch.setattr(notification_queue.alerts_repo, "list_due_alert_group_notifications", lambda **kw: [selected])
    monkeypatch.setattr(notification_queue, "notify_alert", lambda *a, **kw: pytest.fail("must not send after ACK"))
    assert notification_queue.process_due_alert_group_notifications()["skipped"] == 1
    assert AlertGroup.get_by_id(selected.id).status == "acknowledged"


def test_ack_serializes_with_a_claimed_delivery(due, monkeypatch):
    selected = due()[0]
    inside = Event()
    finish = Event()
    ack_started = Event()
    ack_done = Event()

    def provider(group, event_type="notification", **kwargs):
        inside.set()
        assert finish.wait(timeout=10)
        return 1

    def delivery():
        with database_proxy.obj.connection_context():
            return notification_queue.process_due_alert_group_notifications()

    def ack():
        with database_proxy.obj.connection_context():
            ack_started.set()
            acknowledge_alert(selected.id)
            ack_done.set()

    monkeypatch.setattr(notification_queue, "notify_alert", provider)
    with ThreadPoolExecutor(max_workers=2) as pool:
        sending = pool.submit(delivery)
        try:
            assert inside.wait(timeout=10)
            acknowledging = pool.submit(ack)
            assert ack_started.wait(timeout=5)
            assert not ack_done.wait(timeout=0.2)
        finally:
            finish.set()
        assert sending.result(timeout=10)["sent"] == 1
        acknowledging.result(timeout=10)
    group = AlertGroup.get_by_id(selected.id)
    assert group.status == "acknowledged"
    assert not group.notification_pending


def test_failed_worker_rolls_back_claim_for_retry(due, monkeypatch):
    selected = due()[0]

    def fail(*args, **kwargs):
        raise RuntimeError("worker failed before delivery")

    monkeypatch.setattr(notification_queue, "notify_alert", fail)
    assert notification_queue.process_due_alert_group_notifications()["failed"] == 1
    assert AlertGroup.get_by_id(selected.id).notification_pending
    monkeypatch.setattr(notification_queue, "notify_alert", lambda *a, **kw: 1)
    assert notification_queue.process_due_alert_group_notifications()["sent"] == 1
    assert not AlertGroup.get_by_id(selected.id).notification_pending


def test_one_connection_pool_uses_the_coordinator_instead_of_deadlocking(db, due, monkeypatch):
    import threading
    due(2)
    caller = threading.get_ident()
    monkeypatch.setattr(db, "_max_connections", 1)
    monkeypatch.setattr(Config, "ALERT_GROUP_NOTIFICATION_WORKERS", 8)

    def provider(group, event_type="notification", **kwargs):
        assert threading.get_ident() == caller
        return 1

    monkeypatch.setattr(notification_queue, "notify_alert", provider)
    assert notification_queue.process_due_alert_group_notifications()["sent"] == 2
