"""Two firing deliveries must not create two reopened groups/children."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest

from app.db import database_proxy
from app.modules.db.models import Alert, AlertGroup
from app.services.alerts.lifecycle import upsert_alert
from app.services.alerts import lifecycle
from app.services.orchestration.runtime import RuntimeResult
from tests.factories import create_channel, create_group, create_route, create_team, create_user, unique

pytestmark = pytest.mark.postgresql


def test_simultaneous_reopen_has_one_new_child(db, monkeypatch):
    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("requires PostgreSQL")

    g = create_group()
    team = create_team(g)
    route = create_route(team, source="alertmanager", group_by=["alertname"])
    monkeypatch.setattr(
        lifecycle, "run_event_orchestration",
        lambda data, trace=None: RuntimeResult(grouping_reopen_window_seconds=120),
    )
    data = {
        "source": "alertmanager", "forced_route_id": route.id,
        "external_id": unique("flap"), "dedup_key": unique("flap-dedup"),
        "title": "DiskFull", "severity": "critical", "status": "firing",
        "labels": {"alertname": "DiskFull"}, "payload": {},
    }
    first = upsert_alert(dict(data))
    resolved = dict(data, status="resolved")
    upsert_alert(resolved)
    assert AlertGroup.get_by_id(first.group.id).status == "resolved"

    barrier = Barrier(2)

    def fire(_):
        with database_proxy.obj.connection_context():
            barrier.wait(timeout=10)
            return upsert_alert(dict(data)).group.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(fire, (1, 2)))

    assert ids == [first.group.id, first.group.id]
    assert Alert.select().where(Alert.group == first.group.id).count() == 2
    assert AlertGroup.select().where(AlertGroup.id == first.group.id).count() == 1


def test_recovery_delivery_serializes_with_concurrent_reopen(db, monkeypatch):
    """Resolved delivery wins or is cancelled; it must not follow a reopen."""
    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("requires PostgreSQL")

    from threading import Event
    from app.modules.common import utc_now
    from app.services.alerts import notification_queue
    from app.settings import Config

    monkeypatch.setattr(Config, "RECOVERY_NOTIFICATION_DELAY_SECONDS", 60)
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager", group_by=["alertname"])
    monkeypatch.setattr(
        lifecycle,
        "run_event_orchestration",
        lambda event, trace=None: RuntimeResult(grouping_reopen_window_seconds=120),
    )
    data = {
        "source": "alertmanager", "forced_route_id": route.id,
        "external_id": unique("race"), "dedup_key": unique("race-dedup"),
        "title": "DiskFull", "severity": "critical", "status": "firing",
        "labels": {"alertname": "DiskFull"}, "payload": {},
    }
    first = upsert_alert(dict(data))
    original = AlertGroup.get_by_id(first.group.id)
    original.last_notification_at = utc_now()
    original.save(only=[AlertGroup.last_notification_at])
    upsert_alert(dict(data, status="resolved"))
    from app.modules.db import notifications_repo
    channel = create_channel(group, team)
    notifications_repo.save_notification(
        group_id=first.group.id, channel_id=channel.id,
        provider="webhook", event_type="notification", provider_status="sent",
    )

    AlertGroup.update(
        notification_due_at=utc_now() - timedelta(seconds=1)
    ).where(AlertGroup.id == first.group.id).execute()
    selected = AlertGroup.get_by_id(first.group.id)

    sending = Event()
    allow_send = Event()
    calls = []

    def fake_delivery(current, *, event_type, channel_ids, **kwargs):
        sending.set()
        assert allow_send.wait(timeout=10)
        calls.append((current.id, event_type))
        return {"sent": 1, "channels": {
            channel.id: {"status": "sent"},
        }}

    monkeypatch.setattr(notification_queue, "notify_alert", fake_delivery)

    def send_due():
        with database_proxy.obj.connection_context():
            return notification_queue._process_due_recovery(selected, now=utc_now())

    def reopen():
        with database_proxy.obj.connection_context():
            return upsert_alert(dict(data)).group.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        sending_future = executor.submit(send_due)
        assert sending.wait(timeout=10)
        reopening_future = executor.submit(reopen)
        allow_send.set()
        assert sending_future.result(timeout=20) == "sent"
        assert reopening_future.result(timeout=20) == first.group.id

    assert calls == [(first.group.id, "resolved")]
    assert AlertGroup.get_by_id(first.group.id).status == "firing"
    from app.modules.db.models import AlertEvent
    event_types = [
        event.event_type for event in AlertEvent.select()
        .where(AlertEvent.group == first.group.id)
        .order_by(AlertEvent.id.asc())
    ]
    assert event_types.index("recovery_notification_sent") < event_types.index("reopened")


def test_resolved_user_rule_send_is_serialized_before_reopen(db, monkeypatch):
    """A user-rule email may finish before reopen, never after it commits."""
    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("requires PostgreSQL")

    from threading import Event
    from app.modules.common import utc_now
    from app.modules.db.models import UserNotificationDelivery
    from app.services.notifications import rules

    scope = create_group()
    team = create_team(scope)
    recipient = create_user(group=scope)
    route = create_route(team, source="alertmanager", group_by=["alertname"])
    monkeypatch.setattr(
        lifecycle,
        "run_event_orchestration",
        lambda event, trace=None: RuntimeResult(grouping_reopen_window_seconds=120),
    )
    data = {
        "source": "alertmanager", "forced_route_id": route.id,
        "external_id": unique("user-race"), "dedup_key": unique("user-race-key"),
        "title": "DiskFull", "severity": "critical", "status": "firing",
        "labels": {"alertname": "DiskFull"}, "payload": {},
    }
    initial = upsert_alert(dict(data))
    group = AlertGroup.get_by_id(initial.group.id)
    group.assignee = recipient
    group.save(only=[AlertGroup.assignee])
    upsert_alert(dict(data, status="resolved"))
    delivery = UserNotificationDelivery.create(
        group=group.id,
        user=recipient.id,
        method="email",
        event_type="resolved",
        scheduled_at=utc_now(),
        created_at=utc_now(),
    )
    sending = Event()
    allow_send = Event()
    reopening = Event()
    messages = []

    class Notifier:
        @staticmethod
        def send(channel, alert_group, text, event_type):
            sending.set()
            assert allow_send.wait(timeout=15)
            messages.append((alert_group.id, event_type))
            return {"provider": "email"}

    monkeypatch.setitem(rules.DIRECT_NOTIFIERS, rules.NOTIFICATION_METHOD_EMAIL, Notifier())

    def send():
        with database_proxy.obj.connection_context():
            return rules.send_delivery(delivery)

    def reopen():
        with database_proxy.obj.connection_context():
            reopening.set()
            return upsert_alert(dict(data)).group.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = executor.submit(send)
        assert sending.wait(timeout=15)
        next_alert = executor.submit(reopen)
        assert reopening.wait(timeout=15)
        allow_send.set()
        assert pending.result(timeout=30) == 1
        assert next_alert.result(timeout=30) == group.id

    assert messages == [(group.id, "resolved")]
    assert UserNotificationDelivery.get_by_id(delivery.id).status == "sent"
    assert AlertGroup.get_by_id(group.id).status == "firing"
    assert upsert_alert(dict(data, status="resolved")).group.status == "resolved"
    assert rules.send_delivery(delivery) == 0  # Already sent in the previous cycle.


def test_manual_resolve_during_uncommitted_reopen_is_noop(db, monkeypatch):
    """A resolve reading the old committed state cannot destroy the new child.

    The reopening thread has already locked and changed the group but has not
    committed its new occurrence. The resolver sees the previously committed
    resolved state and must not apply a stale write to the new cycle.
    """
    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("requires PostgreSQL")

    from threading import Event
    from app.modules.db import alerts_repo
    from app.services.alerts.actions import resolve_alert

    scope = create_group()
    team = create_team(scope)
    route = create_route(team, source="alertmanager", group_by=["alertname"])
    monkeypatch.setattr(
        lifecycle, "run_event_orchestration",
        lambda data, trace=None: RuntimeResult(grouping_reopen_window_seconds=120),
    )
    data = {
        "source": "alertmanager", "forced_route_id": route.id,
        "external_id": unique("resolve-race"), "dedup_key": unique("resolve-race-key"),
        "title": "DiskFull", "severity": "critical", "status": "firing",
        "labels": {"alertname": "DiskFull"}, "payload": {},
    }
    initial = upsert_alert(dict(data))
    upsert_alert(dict(data, status="resolved"))

    entered = Event()
    release = Event()
    original_create = alerts_repo.create_alert

    def block_new_child(**kwargs):
        entered.set()
        assert release.wait(timeout=20)
        return original_create(**kwargs)

    monkeypatch.setattr(alerts_repo, "create_alert", block_new_child)

    def reopen():
        with database_proxy.obj.connection_context():
            return upsert_alert(dict(data))

    def resolve():
        with database_proxy.obj.connection_context():
            return resolve_alert(
                initial.group.id, update_messages=False,
                defer_stakeholder_notification=True,
            ).status

    with ThreadPoolExecutor(max_workers=2) as executor:
        reopening = executor.submit(reopen)
        try:
            assert entered.wait(timeout=15)
            # Read-committed should see resolved, not the uncommitted reopen.
            resolving = executor.submit(resolve)
            assert resolving.result(timeout=15) == "resolved"
        finally:
            release.set()
        result = reopening.result(timeout=30)

    assert result.outcome == "reopened"
    assert result.group.id == initial.group.id
    assert AlertGroup.get_by_id(initial.group.id).status == "firing"
    children = list(Alert.select().where(Alert.group == initial.group.id))
    assert len(children) == 2
    assert sum(child.status == "resolved" for child in children) == 1
    assert sum(child.status == "firing" for child in children) == 1
