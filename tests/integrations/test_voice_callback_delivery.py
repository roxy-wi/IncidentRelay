"""Voice callbacks must work while the outbound provider request is in flight."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from app.modules.common import utc_now
from app.modules.db.models import AlertGroup, UserNotificationDelivery
from app.notifiers.voice import notifier as voice_notifier
from app.notifiers.voice.base import VoiceCallResult
from app.services.alerts import notification_queue
from app.services.alerts.actions import acknowledge_alert, resolve_alert
from app.services.alerts.lifecycle import upsert_alert
from app.services.notifications import rules
from app.settings import Config
from app.views import integrations_view
from tests.factories import (
    add_user_to_team, create_group, create_route, create_team, create_user, unique,
)


@pytest.fixture
def voice_group(db, monkeypatch):
    tenant = create_group()
    team = create_team(tenant)
    user = create_user(group=tenant)
    user.phone = "+12025550123"
    user.save()
    add_user_to_team(team, user)
    route = create_route(team, source="webhook", group_by=["alertname"])
    key = unique("voice-callback")
    group = upsert_alert({
        "source": "webhook", "forced_route_id": route.id, "dedup_key": key,
        "title": "DiskFull", "severity": "critical", "status": "firing",
        "labels": {"alertname": key}, "payload": {},
    }).group
    group.assignee = user
    group.notification_pending = True
    group.notification_reason = "notification"
    group.notification_due_at = utc_now() - timedelta(seconds=1)
    group.save()
    rules.create_user_rule(
        user, method="voice_call", delay_seconds=0, event_types=["notification"],
    )
    monkeypatch.setattr(Config, "VOICE_PROVIDER", "stub")
    monkeypatch.setattr(Config, "VOICE_CALLBACK_SECRET", "test-voice-callback")
    monkeypatch.setattr(Config, "ALERT_GROUP_NOTIFICATION_WORKERS", 1)
    return group


@pytest.mark.parametrize(
    ("digit", "status"), [(None, "firing"), ("1", "acknowledged"), ("2", "resolved")],
)
def test_callback_finishes_before_place_call_returns(
    db, app, voice_group, monkeypatch, digit, status,
):
    payload = {
        "call_id": "call-1", "event_type": "dtmf" if digit else "status",
        "status": "completed", "digit": digit,
    }
    responses = []

    def callback(request):
        with app.test_client() as client:
            response = client.post(
                urlsplit(request.callback_url).path, json=payload,
                headers={"X-IncidentRelay-Callback-Secret": request.callback_secret},
            )
            return response.status_code, response.get_json()

    def place_call(request):
        assert not db.in_transaction()
        with ThreadPoolExecutor(max_workers=1) as executor:
            responses.append(executor.submit(callback, request).result(timeout=10))
        return VoiceCallResult(call_id="call-1", status="queued", raw={"accepted": True})

    monkeypatch.setattr(
        voice_notifier, "create_voice_provider",
        lambda *args: SimpleNamespace(name="test", place_call=place_call),
    )
    with app.app_context():
        result = notification_queue.process_due_alert_group_notifications()

    assert result == {"processed": 1, "sent": 1, "skipped": 0, "failed": 0}
    assert len(responses) == 1
    assert responses[0][0] == 200, responses
    assert responses[0][1]["events"][0]["action_rejected"] is False
    group = AlertGroup.get_by_id(voice_group.id)
    assert group.status == status
    assert not group.notification_pending
    assert group.last_notification_at is not None
    delivery = UserNotificationDelivery.get(UserNotificationDelivery.group == group.id)
    assert delivery.status == "sent"
    assert delivery.sent_at is not None
    assert delivery.external_message_id == "call-1"
    assert delivery.provider_status == "completed"
    assert delivery.provider_payload == payload


def test_late_callback_cannot_restore_stale_delivery_status(db, voice_group):
    delivery = rules.create_delivery(
        voice_group, voice_group.assignee, None, "voice_call", "notification", utc_now(),
    )
    stale = UserNotificationDelivery.get_by_id(delivery.id)
    sent_at = utc_now()
    UserNotificationDelivery.update(status="sent", sent_at=sent_at).where(
        UserNotificationDelivery.id == delivery.id,
    ).execute()
    integrations_view._process_voice_rule_callback_event(stale, SimpleNamespace(
        call_id="call-1", status="completed", raw={"status": "completed"},
        action=None, digit=None, event_type="status",
    ))
    stored = UserNotificationDelivery.get_by_id(delivery.id)
    assert stored.status == "sent"
    assert stored.sent_at == sent_at
    assert stored.provider_status == "completed"


def test_failed_voice_call_is_not_marked_sent(db, app, voice_group, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("voice provider unavailable")

    monkeypatch.setattr(rules.DIRECT_NOTIFIERS["voice_call"], "send", fail)
    with app.app_context():
        result = notification_queue.process_due_alert_group_notifications()
    assert result["sent"] == 0
    delivery = UserNotificationDelivery.get(UserNotificationDelivery.group == voice_group.id)
    assert delivery.status == "failed"
    assert delivery.sent_at is None
    assert delivery.last_error == "voice provider unavailable"
    assert AlertGroup.get_by_id(voice_group.id).last_notification_at is None


def test_pending_call_survives_exit_before_dispatch(db, app, voice_group, monkeypatch):
    process = rules.process_due_user_notifications

    def interrupted(*args, **kwargs):
        raise RuntimeError("worker exits after commit")

    monkeypatch.setattr(rules, "process_due_user_notifications", interrupted)
    calls = []
    monkeypatch.setattr(rules.DIRECT_NOTIFIERS["voice_call"], "send",
                        lambda *a, **kw: calls.append(True) or {"provider_status": "queued"})
    with app.app_context():
        assert notification_queue.process_due_alert_group_notifications()["failed"] == 1
    assert calls == []
    delivery = UserNotificationDelivery.get(UserNotificationDelivery.group == voice_group.id)
    assert delivery.status == "pending"
    assert process() == 1
    assert process() == 0
    assert calls == [True]
    assert AlertGroup.get_by_id(voice_group.id).last_notification_at is not None


@pytest.mark.parametrize("action", [acknowledge_alert, resolve_alert])
def test_lifecycle_change_before_dispatch_cancels_call(
    db, app, voice_group, monkeypatch, action,
):
    process = rules.process_due_user_notifications

    def change_then_dispatch(*args, **kwargs):
        assert not db.in_transaction()
        action(voice_group.id)
        return process(*args, **kwargs)

    monkeypatch.setattr(rules, "process_due_user_notifications", change_then_dispatch)
    monkeypatch.setattr(rules.DIRECT_NOTIFIERS["voice_call"], "send",
                        lambda *a, **kw: pytest.fail("must not call after ACK/resolve"))
    with app.app_context():
        assert notification_queue.process_due_alert_group_notifications()["sent"] == 0
    delivery = UserNotificationDelivery.get(UserNotificationDelivery.group == voice_group.id)
    assert delivery.status == "skipped"
    assert AlertGroup.get_by_id(voice_group.id).last_notification_at is None


def test_outer_transaction_defers_dispatch_until_commit(db, app, voice_group, monkeypatch):
    calls = []
    monkeypatch.setattr(rules.DIRECT_NOTIFIERS["voice_call"], "send",
                        lambda *a, **kw: calls.append(True) or {})
    with app.app_context(), db.atomic():
        notification_queue.process_due_alert_group_notifications()
        assert calls == []
        delivery = UserNotificationDelivery.get(UserNotificationDelivery.group == voice_group.id)
        assert delivery.status == "pending"
    assert rules.process_due_user_notifications() == 1
    assert calls == [True]


def test_reassignment_before_dispatch_does_not_call_another_user(
    db, app, voice_group, monkeypatch,
):
    process = rules.process_due_user_notifications
    other = create_user(group=voice_group.team.group)

    def reassign_then_dispatch(*args, **kwargs):
        AlertGroup.update(assignee=other).where(AlertGroup.id == voice_group.id).execute()
        return process(*args, **kwargs)

    monkeypatch.setattr(rules, "process_due_user_notifications", reassign_then_dispatch)
    monkeypatch.setattr(rules.DIRECT_NOTIFIERS["voice_call"], "send",
                        lambda *a, **kw: pytest.fail("delivery belongs to the previous assignee"))
    with app.app_context():
        assert notification_queue.process_due_alert_group_notifications()["sent"] == 0
    delivery = UserNotificationDelivery.get(UserNotificationDelivery.group == voice_group.id)
    assert delivery.status == "skipped"
    assert delivery.last_error == "assignee_changed"


def test_finishing_call_preserves_newly_scheduled_group_notification(
    db, app, voice_group, monkeypatch,
):
    due_at = utc_now() + timedelta(minutes=5)

    def send(*args, **kwargs):
        AlertGroup.update(
            notification_pending=True, notification_reason="update", notification_due_at=due_at,
        ).where(AlertGroup.id == voice_group.id).execute()
        return {}

    monkeypatch.setattr(rules.DIRECT_NOTIFIERS["voice_call"], "send", send)
    with app.app_context():
        assert notification_queue.process_due_alert_group_notifications()["sent"] == 1
    group = AlertGroup.get_by_id(voice_group.id)
    assert group.notification_pending
    assert group.notification_reason == "update"
    assert group.notification_due_at == due_at


def test_provider_error_preserves_callback_metadata(db, voice_group, monkeypatch):
    delivery = rules.create_delivery(
        voice_group, voice_group.assignee, None, "voice_call", "notification", utc_now(),
    )

    def fail_after_callback(*args, **kwargs):
        UserNotificationDelivery.update(
            provider_status="completed", provider_payload={"event_type": "status"},
        ).where(UserNotificationDelivery.id == delivery.id).execute()
        raise RuntimeError("provider response lost")

    monkeypatch.setattr(rules.DIRECT_NOTIFIERS["voice_call"], "send", fail_after_callback)
    assert rules.process_due_user_notifications() == 0
    stored = UserNotificationDelivery.get_by_id(delivery.id)
    assert stored.status == "failed"
    assert stored.provider_status == "completed"
    assert stored.provider_payload == {"event_type": "status"}


@pytest.mark.postgresql
def test_rollback_does_not_place_or_leave_a_call(db, app, voice_group, monkeypatch):
    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("requires transactional group claim")
    create_event = notification_queue.alerts_repo.create_alert_event

    def fail_before_commit(**kwargs):
        if kwargs["event_type"] == "notification_voice_queued":
            raise RuntimeError("failure before commit")
        return create_event(**kwargs)

    monkeypatch.setattr(notification_queue.alerts_repo, "create_alert_event", fail_before_commit)
    monkeypatch.setattr(rules.DIRECT_NOTIFIERS["voice_call"], "send",
                        lambda *a, **kw: pytest.fail("must not call before commit"))
    with app.app_context():
        assert notification_queue.process_due_alert_group_notifications()["failed"] == 1
    assert AlertGroup.get_by_id(voice_group.id).notification_pending
    assert not UserNotificationDelivery.select().exists()


@pytest.mark.postgresql
def test_group_and_user_workers_cannot_send_the_same_call(db, app, voice_group, monkeypatch):
    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("requires concurrent PostgreSQL workers")
    inside = Event()
    finish = Event()
    calls = []

    def send(*args, **kwargs):
        assert not db.in_transaction()
        calls.append(True)
        inside.set()
        assert finish.wait(timeout=10)
        return {}

    def group_worker():
        with app.app_context(), db.connection_context():
            return notification_queue.process_due_alert_group_notifications()

    monkeypatch.setattr(rules.DIRECT_NOTIFIERS["voice_call"], "send", send)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(group_worker)
        try:
            assert inside.wait(timeout=10)
            assert rules.process_due_user_notifications() == 0
            assert notification_queue.process_due_alert_group_notifications()["processed"] == 0
        finally:
            finish.set()
        assert first.result(timeout=10)["sent"] == 1
    assert calls == [True]
