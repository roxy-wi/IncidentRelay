"""Release 2.4 worker-crash gate for abandoned user recovery claims.

The scheduler must reclaim orphaned resolved claims without stealing a
fresh processing claim or delivering a previous resolved lifecycle cycle.
"""

from datetime import timedelta

from app.modules.common import utc_now
from app.modules.db.models import AlertGroup, UserNotificationDelivery
from app.services.notifications import rules
from tests.factories import create_group, create_route, create_team, create_user, unique


def _resolved_group():
    tenant = create_group()
    team = create_team(tenant)
    recipient = create_user(group=tenant)
    route = create_route(team, source="alertmanager")
    timestamp = utc_now()
    key = unique("recovery-processing")
    group = AlertGroup.create(
        team=team,
        route=route,
        assignee=recipient,
        source="alertmanager",
        group_key=key,
        group_key_hash=key,
        title="Recovery processing claim",
        status="resolved",
        resolved_at=timestamp - timedelta(hours=3),
    )
    return group, recipient


def _processing_delivery(group, recipient, *, abandoned):
    now = utc_now()
    return UserNotificationDelivery.create(
        group=group,
        user=recipient,
        rule=None,
        method=rules.NOTIFICATION_METHOD_EMAIL,
        event_type="resolved",
        status="processing",
        scheduled_at=now - timedelta(hours=2),
        created_at=now - timedelta(hours=2),
        updated_at=now - (timedelta(hours=1) if abandoned else timedelta()),
    )


def _fake_email(monkeypatch, sent):
    class Notifier:
        @staticmethod
        def send(channel, group, text, event_type="notification"):
            sent.append((group.id, event_type))
            return {"provider": "email", "provider_status": "sent"}

    monkeypatch.setitem(rules.DIRECT_NOTIFIERS, rules.NOTIFICATION_METHOD_EMAIL, Notifier())


def test_fresh_processing_resolution_is_not_stolen_by_another_worker(db, monkeypatch):
    group, user = _resolved_group()
    delivery = _processing_delivery(group, user, abandoned=False)
    sent = []
    _fake_email(monkeypatch, sent)

    assert rules.process_due_user_notifications() == 0
    assert UserNotificationDelivery.get_by_id(delivery.id).status == "processing"
    assert sent == []


def test_abandoned_processing_resolution_is_reclaimed_after_worker_crash(db, monkeypatch):
    group, user = _resolved_group()
    delivery = _processing_delivery(group, user, abandoned=True)
    sent = []
    _fake_email(monkeypatch, sent)

    # A worker died after claiming this row. A later scheduler run must pick
    # it up once the processing lease expires and finish the delivery.
    assert rules.process_due_user_notifications() == 1
    assert UserNotificationDelivery.get_by_id(delivery.id).status == "sent"
    assert sent == [(group.id, "resolved")]
    assert rules.process_due_user_notifications() == 0
    assert len(sent) == 1


def test_abandoned_old_cycle_claim_is_cancelled_after_reopen(db, monkeypatch):
    group, user = _resolved_group()
    delivery = _processing_delivery(group, user, abandoned=True)
    # Mimic a later resolved cycle using the same AlertGroup ID.
    current = AlertGroup.get_by_id(group.id)
    current.resolved_at = utc_now() - timedelta(minutes=10)
    current.save(only=[AlertGroup.resolved_at])
    sent = []
    _fake_email(monkeypatch, sent)

    assert rules.process_due_user_notifications() == 0
    stored = UserNotificationDelivery.get_by_id(delivery.id)
    assert stored.status == "skipped"
    assert stored.last_error == "alert_group_reopened"
    assert sent == []
