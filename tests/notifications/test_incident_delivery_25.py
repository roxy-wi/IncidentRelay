"""Incident delivery retries preserve successful channels, devices and event identity."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from peewee import OperationalError
from pywebpush import WebPushException

from app.login import create_access_token
from app.modules.common import utc_now
from app.modules.db import incident_core_repo
from app.modules.db.models import (
    AuditLog,
    BrowserPushSubscription,
    Incident,
    IncidentEvent,
    IncidentNotificationDelivery as Delivery,
    IncidentResponder,
    IncidentStakeholder,
)
from app.notifiers.browser_push import service as push
from app.services.incidents import core, responders, stakeholders
from app.services.notifications import incidents as delivery
from tests.factories import create_group, create_team, create_user, unique


@pytest.fixture(autouse=True)
def transports(monkeypatch):
    mail = Mock(return_value=True)
    webpush = Mock(return_value=True)
    monkeypatch.setattr(stakeholders, "send_stakeholder_email", mail)
    monkeypatch.setattr(push, "_webpush", webpush)
    monkeypatch.setattr(push.Config, "BROWSER_PUSH_ENABLED", True)
    monkeypatch.setattr(
        push.Config, "PUBLIC_BASE_URL", "https://incidentrelay.example.test"
    )
    return mail, webpush


def _context():
    team = create_team(create_group())
    actor = create_user(group=team.group, is_admin=True)
    recipient = create_user(group=team.group)
    incident = Incident.create(team=team, title="Database unavailable")
    return incident, actor, recipient


def _subscription(user):
    return BrowserPushSubscription.create(
        user=user,
        endpoint=f"https://push.example.test/{unique('device')}",
        p256dh="test-key",
        auth="test-auth",
    )


def _stakeholder_event(incident, user, *, event_type="created"):
    stakeholder = IncidentStakeholder.create(incident=incident, user=user)
    with incident_core_repo.incident_transaction(incident.id):
        event = incident_core_repo.create_event(incident.id, "incident_declared")
        delivery.enqueue_stakeholders(incident, event, event_type)
    return stakeholder, event


def _retry():
    due = list(Delivery.select().where(Delivery.status == "pending"))
    if due:
        return delivery.process_due_incident_notifications(
            now=max(row.next_attempt_at for row in due),
        )
    return delivery.process_due_incident_notifications()


def test_email_failure_does_not_block_push_or_resend_it(db, transports):
    mail, webpush = transports
    incident, _, user = _context()
    _subscription(user)
    _, event = _stakeholder_event(incident, user)
    mail.side_effect = OSError("SMTP unavailable")
    assert delivery.dispatch_event(event.id) == 1
    assert Delivery.get(Delivery.method == "email").status == "pending"
    assert Delivery.get(Delivery.method == "browser_push").status == "sent"
    assert delivery.dispatch_event(event.id) == 0  # Backoff is respected.
    mail.side_effect = None
    assert _retry() == 1
    assert mail.call_count == 2
    assert webpush.call_count == 1
    assert {row.status for row in Delivery.select()} == {"sent"}
    delivery.dispatch_event(event.id)
    assert mail.call_count == 2


def test_duplicate_roles_and_repeated_enqueue_have_one_delivery_per_channel(
    db, transports
):
    incident, _, user = _context()
    _subscription(user)
    IncidentStakeholder.create(incident=incident, user=user, role="observer")
    IncidentStakeholder.create(
        incident=incident, email=user.email.upper(), role="executive"
    )
    _, event = _stakeholder_event(incident, user)
    delivery.enqueue_stakeholders(incident, event, "created")
    delivery.dispatch_event(event.id)
    delivery.enqueue_stakeholders(incident, event, "created")
    delivery.dispatch_event(event.id)
    assert Delivery.select().count() == 2
    assert transports[0].call_count == transports[1].call_count == 1


def test_partial_responder_push_retries_only_failed_device(db, transports):
    incident, actor, user = _context()
    first, second = _subscription(user), _subscription(user)
    failed = True
    calls = []

    def send(subscription, payload, **kwargs):
        calls.append(subscription.id)
        assert kwargs == {"timeout": 10}
        if failed and subscription.id == second.id:
            raise OSError("provider temporarily unavailable")

    transports[1].side_effect = send
    row = responders.create_incident_responder(
        incident_id=incident.id,
        user_id=actor.id,
        payload={"target_type": "user", "target_user_id": user.id},
    )
    assert row.notification_status == "pending"
    assert Delivery.get().sent_subscription_ids == [first.id]
    assert Delivery.get().subscription_ids == [first.id, second.id]
    _subscription(user)  # Retrying an event must not pick up additional devices.
    failed = False
    assert _retry() == 2
    assert calls == [first.id, second.id, second.id]
    assert IncidentResponder.get_by_id(row.id).notification_status == "sent"
    assert IncidentResponder.get_by_id(row.id).notification_error is None
    responders.notify_incident_responder_requested(row)
    assert calls == [first.id, second.id, second.id]


@pytest.mark.parametrize("status", [404, 410])
def test_gone_push_endpoint_is_disabled_and_not_retried(db, transports, status):
    incident, _, user = _context()
    subscription = _subscription(user)
    _, event = _stakeholder_event(incident, user)
    transports[1].side_effect = WebPushException(
        "gone",
        response=SimpleNamespace(status_code=status),
    )
    delivery.dispatch_event(event.id)
    current = BrowserPushSubscription.get_by_id(subscription.id)
    assert not current.enabled and current.deleted
    assert Delivery.get(Delivery.method == "browser_push").status == "skipped"
    _retry()
    assert transports[1].call_count == 1


def test_retry_limit_and_backoff_preserve_a_terminal_failure(db, transports):
    incident, _, user = _context()
    IncidentStakeholder.create(incident=incident, email=user.email)
    event = incident_core_repo.create_event(incident.id, "incident_declared")
    delivery.enqueue_stakeholders(incident, event, "created")
    transports[0].return_value = False
    now = utc_now()
    for attempt in range(1, 6):
        delivery.process_due_incident_notifications(now=now)
        row = Delivery.get()
        assert row.attempts == attempt
        if attempt < 5:
            assert row.status == "pending"
            assert row.next_attempt_at == now + timedelta(
                seconds=30 * 2 ** (attempt - 1)
            )
            delivery.process_due_incident_notifications(
                now=row.next_attempt_at - timedelta(seconds=1)
            )
            assert transports[0].call_count == attempt
            now = row.next_attempt_at
    assert row.status == "failed" and row.delivered_at is None
    delivery.process_due_incident_notifications(now=now + timedelta(days=1))
    assert transports[0].call_count == 5


@pytest.mark.parametrize("status", ["accepted", "declined", "expired", "resolved"])
def test_responder_retry_is_cancelled_after_request_finishes(db, transports, status):
    incident, actor, user = _context()
    _subscription(user)
    transports[1].side_effect = OSError("offline")
    row = responders.create_incident_responder(
        incident_id=incident.id,
        user_id=actor.id,
        payload={"target_type": "user", "target_user_id": user.id},
    )
    IncidentResponder.update(status=status).where(
        IncidentResponder.id == row.id
    ).execute()
    _retry()
    assert transports[1].call_count == 1
    assert Delivery.get().status == "skipped"


def test_expired_deadline_cancels_retry_before_expiration_job(db, transports):
    incident, actor, user = _context()
    _subscription(user)
    transports[1].side_effect = OSError("offline")
    row = responders.create_incident_responder(
        incident_id=incident.id,
        user_id=actor.id,
        payload={"target_type": "user", "target_user_id": user.id},
    )
    IncidentResponder.update(expires_at=utc_now() - timedelta(seconds=1)).where(
        IncidentResponder.id == row.id,
    ).execute()
    _retry()
    assert Delivery.get().status == "skipped"
    assert transports[1].call_count == 1


@pytest.mark.parametrize("reason", ["inactive_user", "unsubscribe", "disable_flag"])
def test_retry_respects_current_recipient_preferences(db, transports, reason):
    incident, _, user = _context()
    _subscription(user)
    stakeholder, event = _stakeholder_event(incident, user)
    transports[0].side_effect = OSError("offline")
    transports[1].side_effect = OSError("offline")
    delivery.dispatch_event(event.id)
    if reason == "inactive_user":
        user.active = False
        user.save()
    elif reason == "unsubscribe":
        stakeholder.active = False
        stakeholder.save()
    else:
        stakeholder.notify_on_created = False
        stakeholder.save()
    _retry()
    assert transports[0].call_count == transports[1].call_count == 1
    assert {row.status for row in Delivery.select()} == {"skipped"}


def test_failed_delivery_keeps_event_content_and_hides_provider_secrets(
    db, transports, caplog
):
    incident, _, user = _context()
    _, event = _stakeholder_event(incident, user)
    transports[0].side_effect = RuntimeError(
        "password=supersecret endpoint=private-url"
    )
    delivery.dispatch_event(event.id)
    row = Delivery.get(Delivery.method == "email")
    assert row.last_error == "RuntimeError"
    assert "supersecret" not in caplog.text and "private-url" not in caplog.text
    incident.title = "Later title"
    incident.workflow_status = "resolved"
    incident.save()
    transports[0].side_effect = None
    _retry()
    _, subject, body = transports[0].call_args.args
    assert "Database unavailable" in subject and "Later title" not in subject
    assert "Status: declared" in body
    assert f"https://incidentrelay.example.test/incidents/{incident.id}" in body


def test_no_devices_can_retry_after_push_subscription_is_added(db, transports):
    incident, actor, user = _context()
    row = responders.create_incident_responder(
        incident_id=incident.id,
        user_id=actor.id,
        payload={"target_type": "user", "target_user_id": user.id},
    )
    assert row.notification_status == "pending"
    assert Delivery.get().last_error == "no_active_push_subscriptions"
    _subscription(user)
    assert _retry() == 1
    assert IncidentResponder.get_by_id(row.id).notification_status == "sent"


def test_live_claim_is_skipped_and_abandoned_claim_is_recovered(db, transports):
    incident, _, user = _context()
    IncidentStakeholder.create(incident=incident, email=user.email)
    event = incident_core_repo.create_event(incident.id, "incident_declared")
    delivery.enqueue_stakeholders(incident, event, "created")
    now = utc_now()
    Delivery.update(
        status="processing",
        claim_token="dead-worker",
        attempts=1,
        claim_expires_at=now + timedelta(seconds=300),
    ).execute()
    delivery.process_due_incident_notifications(now=now)
    transports[0].assert_not_called()
    delivery.process_due_incident_notifications(now=now + timedelta(seconds=301))
    assert Delivery.get().status == "sent"
    assert Delivery.get().attempts == 2
    transports[0].assert_called_once()


def test_dispatch_does_not_send_inside_an_open_transaction(db, transports):
    incident, _, user = _context()
    _subscription(user)
    with db.atomic():
        _, event = _stakeholder_event(incident, user)
        assert delivery.dispatch_event(event.id) == 0
        transports[0].assert_not_called()
        transports[1].assert_not_called()
    assert delivery.dispatch_event(event.id) == 2


def test_enqueue_failure_rolls_back_request_event_and_audit(db, monkeypatch):
    incident, actor, user = _context()

    def fail(*args, **kwargs):
        raise OperationalError("outbox unavailable")

    monkeypatch.setattr(Delivery, "get_or_create", fail)
    with pytest.raises(OperationalError, match="outbox"):
        responders.create_incident_responder(
            incident_id=incident.id,
            user_id=actor.id,
            payload={"target_type": "user", "target_user_id": user.id},
        )
    assert IncidentResponder.select().count() == 0
    assert IncidentEvent.select().count() == AuditLog.select().count() == 0


def test_postcommit_dispatch_failure_keeps_successful_api_response(
    client, db, monkeypatch
):
    incident, actor, user = _context()
    token, _ = create_access_token(actor)

    def fail(**kwargs):
        raise OperationalError("database connection lost")

    monkeypatch.setattr(delivery, "process_due_incident_notifications", fail)
    response = client.post(
        f"/api/incidents/{incident.id}/responders",
        headers={"Authorization": f"Bearer {token}"},
        json={"target_type": "user", "target_user_id": user.id},
    )
    assert response.status_code == 201, response.json
    assert IncidentResponder.select().count() == 1
    assert Delivery.get().status == "pending"
    assert IncidentEvent.select().count() == AuditLog.select().count() == 1


def test_priority_change_queues_once_and_unchanged_priority_does_not(db, transports):
    incident, _, user = _context()
    _subscription(user)
    IncidentStakeholder.create(incident=incident, user=user)
    core.update_incident(incident.id, expected_version=1, priority_slug="p1")
    core.update_incident(incident.id, expected_version=2, priority_slug="p1")
    assert Delivery.select().count() == 2
    assert {row.payload["event_type"] for row in Delivery.select()} == {
        "priority_changed"
    }
    assert transports[0].call_count == transports[1].call_count == 1


def test_comment_delivery_contains_comment_and_omits_author(client, db, transports):
    incident, actor, user = _context()
    for target in (actor, user):
        IncidentStakeholder.create(incident=incident, user=target)
        _subscription(target)
    token, _ = create_access_token(actor)
    response = client.post(
        f"/api/incidents/{incident.id}/comments",
        headers={"Authorization": f"Bearer {token}"},
        json={"body": "Failover complete"},
    )
    assert response.status_code == 201
    assert Delivery.select().count() == 2
    assert {row.user_id for row in Delivery.select()} == {user.id}
    assert "Failover complete" in transports[0].call_args.args[2]
    payload = transports[1].call_args.args[1]
    assert "Failover complete" in payload["body"]
    assert payload["action_tokens"] == {}
    assert "alert_group_id" not in payload


def test_stale_worker_result_cannot_overwrite_replacement_claim(db, transports):
    incident, _, user = _context()
    IncidentStakeholder.create(incident=incident, email=user.email)
    event = incident_core_repo.create_event(incident.id, "incident_declared")
    delivery.enqueue_stakeholders(incident, event, "created")

    def replace_claim(*args):
        Delivery.update(claim_token="new-worker").execute()
        return True

    transports[0].side_effect = replace_claim
    delivery.dispatch_event(event.id)
    row = Delivery.get()
    assert row.status == "processing" and row.claim_token == "new-worker"
    assert IncidentEvent.select().count() == 1
