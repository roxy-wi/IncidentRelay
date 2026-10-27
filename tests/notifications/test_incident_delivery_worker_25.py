"""Worker concurrency, scheduler integration and transport failure contracts."""

import importlib
import smtplib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from unittest.mock import Mock

import pytest
from peewee import IntegrityError

from app.db import database_proxy
from app.modules.common import utc_now
from app.modules.db import incident_core_repo
from app.modules.db.models import (
    Incident,
    IncidentEvent,
    IncidentNotificationDelivery as Delivery,
    IncidentResponder,
    IncidentStakeholder,
)
from app.services import scheduler
from app.services.incidents import stakeholder_mail, stakeholders
from app.services.notifications import incidents as delivery
from tests.factories import create_group, create_team, create_user


def _queued_mail():
    team = create_team(create_group())
    incident = Incident.create(team=team, title="Queued update")
    IncidentStakeholder.create(incident=incident, email="recipient@example.test")
    event = incident_core_repo.create_event(incident.id, "incident_declared")
    delivery.enqueue_stakeholders(incident, event, "created")
    return incident, event


def test_two_workers_cannot_deliver_the_same_live_claim(db, monkeypatch):
    _, event = _queued_mail()
    sending = Event()
    finish = Event()
    calls = []

    def send(*args):
        calls.append(args)
        sending.set()
        assert finish.wait(timeout=10)
        return True

    monkeypatch.setattr(stakeholders, "send_stakeholder_email", send)

    def run():
        with database_proxy.obj.connection_context():
            return delivery.dispatch_event(event.id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run)
        try:
            assert sending.wait(timeout=10)
            second = pool.submit(run)
            assert second.result(timeout=10) == 0
        finally:
            finish.set()
        assert first.result(timeout=10) == 1
    assert len(calls) == 1
    assert Delivery.get().attempts == 1
    assert Delivery.get().status == "sent"


def test_concurrent_enqueue_preserves_single_target(db):
    incident, event = _queued_mail()
    barrier = Barrier(2)

    def enqueue():
        with database_proxy.obj.connection_context():
            barrier.wait(timeout=10)
            with incident_core_repo.incident_transaction(incident.id):
                delivery.enqueue_stakeholders(incident, event, "created")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(enqueue) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)
    assert Delivery.select().count() == 1


def test_expired_worker_cannot_adopt_a_new_workers_claim(db, monkeypatch):
    _, event = _queued_mail()
    send = Mock(return_value=True)
    monkeypatch.setattr(stakeholders, "send_stakeholder_email", send)
    original = Delivery.get_or_none

    def replace_claim(*args, **kwargs):
        Delivery.update(claim_token="replacement-worker").execute()
        return original(*args, **kwargs)

    monkeypatch.setattr(Delivery, "get_or_none", replace_claim)
    delivery.dispatch_event(event.id)
    send.assert_not_called()
    assert Delivery.get().claim_token == "replacement-worker"
    assert Delivery.get().status == "processing"


def test_lost_claim_is_checked_immediately_before_email(db, monkeypatch):
    _, event = _queued_mail()
    send = Mock(return_value=True)
    monkeypatch.setattr(stakeholders, "send_stakeholder_email", send)
    original = delivery._is_relevant

    def replace_claim(row):
        Delivery.update(claim_token="replacement-worker").execute()
        return original(row)

    monkeypatch.setattr(delivery, "_is_relevant", replace_claim)
    delivery.dispatch_event(event.id)
    send.assert_not_called()
    assert Delivery.get().claim_token == "replacement-worker"


def test_scheduler_uses_existing_notification_job_and_releases_lock(db, monkeypatch):
    _, event = _queued_mail()
    send = Mock(return_value=True)
    release = Mock()
    monkeypatch.setattr(stakeholders, "send_stakeholder_email", send)
    monkeypatch.setattr(scheduler, "process_due_user_notifications", lambda: 3)
    monkeypatch.setattr(scheduler, "acquire_db_lock", lambda name: "owner")
    monkeypatch.setattr(scheduler, "release_db_lock", release)
    assert scheduler.user_notification_rules_job() == 4
    assert Delivery.get().event_id == event.id
    assert Delivery.get().status == "sent"
    release.assert_called_once_with("user_notification_rules_job", "owner")


def test_abandoned_last_attempt_exhausts_without_sending_again(db, monkeypatch):
    _queued_mail()
    send = Mock(return_value=True)
    monkeypatch.setattr(stakeholders, "send_stakeholder_email", send)
    Delivery.update(
        status="processing",
        attempts=5,
        claim_token="crashed",
        claim_expires_at=utc_now() - timedelta(seconds=1),
    ).execute()
    delivery.process_due_incident_notifications()
    assert Delivery.get().status == "failed"
    assert Delivery.get().attempts == 5
    send.assert_not_called()


def test_preupgrade_requests_resume_but_sent_and_finished_requests_do_not(
    db, monkeypatch
):
    incident, _ = _queued_mail()
    Delivery.delete().execute()
    user = create_user(group=incident.team.group)
    for notification_status, status in (
        ("pending", "requested"),
        ("failed", "requested"),
        ("sent", "requested"),
        ("failed", "accepted"),
    ):
        IncidentResponder.create(
            incident=incident,
            target_type="user",
            target_user=user,
            notification_status=notification_status,
            status=status,
        )
    IncidentResponder.create(
        incident=incident,
        target_type="team",
        target_team=incident.team,
        expires_at=utc_now() - timedelta(seconds=1),
    )
    monkeypatch.setattr(delivery.Config, "BROWSER_PUSH_ENABLED", False)
    delivery.process_due_incident_notifications()
    assert Delivery.select().count() == 2
    assert (
        IncidentEvent.select()
        .where(
            IncidentEvent.event_type == "responder_notification_queued",
        )
        .count()
        == 2
    )
    delivery.process_due_incident_notifications()
    assert Delivery.select().count() == 2


def test_legacy_target_resolution_error_does_not_block_existing_queue(
    db, monkeypatch, caplog
):
    incident, _ = _queued_mail()
    user = create_user(group=incident.team.group)
    IncidentResponder.create(incident=incident, target_type="user", target_user=user)
    send = Mock(return_value=True)
    monkeypatch.setattr(stakeholders, "send_stakeholder_email", send)

    def fail(*args):
        raise RuntimeError("provider-secret")

    monkeypatch.setattr(delivery, "enqueue_responder", fail)
    assert delivery.process_due_incident_notifications() == 1
    send.assert_called_once()
    assert "enqueue deferred" in caplog.text
    assert "provider-secret" not in caplog.text
    assert Delivery.select().count() == 1
    assert (
        IncidentEvent.select()
        .where(
            IncidentEvent.event_type == "responder_notification_queued",
        )
        .count()
        == 0
    )


@pytest.mark.parametrize("outcome", ["refused", "exception", "success"])
def test_smtp_outcome_is_reported_truthfully(monkeypatch, outcome):
    smtp = Mock()
    smtp.__enter__ = Mock(return_value=smtp)
    smtp.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(stakeholder_mail.smtplib, "SMTP", Mock(return_value=smtp))
    monkeypatch.setattr(stakeholder_mail.Config, "SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(stakeholder_mail.Config, "SMTP_USER", "")
    monkeypatch.setattr(stakeholder_mail.Config, "SMTP_PASSWORD", "")
    if outcome == "refused":
        smtp.send_message.return_value = {"recipient@example.test": (550, b"refused")}
        with pytest.raises(smtplib.SMTPRecipientsRefused):
            stakeholder_mail.send_incident_mail(
                "recipient@example.test", "Subject", "Body"
            )
    elif outcome == "exception":
        smtp.send_message.side_effect = smtplib.SMTPServerDisconnected("offline")
        with pytest.raises(smtplib.SMTPServerDisconnected):
            stakeholder_mail.send_incident_mail(
                "recipient@example.test", "Subject", "Body"
            )
    else:
        smtp.send_message.return_value = {}
        assert stakeholder_mail.send_incident_mail(
            "recipient@example.test", "Subject", "Body"
        )


def test_delivery_migration_is_repeatable_and_unique_per_event(db):
    migration = importlib.import_module(
        "app.migrations.20261027010000_incident_notification_delivery"
    )
    with db.atomic() as transaction:
        migration.downgrade()
        migration.upgrade()
        migration.upgrade()
        incident, event = _queued_mail()
        with pytest.raises(IntegrityError), db.atomic():
            Delivery.create(
                incident=incident,
                event=event,
                method="email",
                target_key=Delivery.get().target_key,
                payload={},
            )
        assert Delivery.select().count() == 1
        transaction.rollback()
