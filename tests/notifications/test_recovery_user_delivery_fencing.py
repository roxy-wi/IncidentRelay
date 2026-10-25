"""Resolved user-rule deliveries must be fenced against AlertGroup reopen."""

from datetime import timedelta

from app.modules.common import utc_now
from app.modules.db.models import AlertGroup, UserNotificationDelivery
from app.services.alerts import lifecycle
from app.services.alerts.lifecycle import upsert_alert
from app.services.notifications import rules
from app.services.orchestration.runtime import RuntimeResult
from tests.factories import create_group, create_route, create_team, create_user


def _alert(route, status="firing"):
    return {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": "user-rule-reopen-race",
        "dedup_key": "user-rule-reopen-race",
        "title": "Database unavailable",
        "severity": "critical",
        "status": status,
        "labels": {"alertname": "DatabaseUnavailable"},
        "payload": {},
    }


def _resolved_assigned_group(monkeypatch):
    group = create_group()
    team = create_team(group)
    user = create_user(group=group)
    route = create_route(team, source="alertmanager", group_by=["alertname"])
    monkeypatch.setattr(
        lifecycle,
        "run_event_orchestration",
        lambda event, trace=None: RuntimeResult(grouping_reopen_window_seconds=300),
    )
    first = upsert_alert(_alert(route))
    assigned = AlertGroup.get_by_id(first.group.id)
    assigned.assignee = user
    assigned.save(only=[AlertGroup.assignee])
    upsert_alert(_alert(route, "resolved"))
    stored = AlertGroup.get_by_id(first.group.id)
    assert stored.status == "resolved"
    assert stored.resolved_at is not None
    return route, stored, user


def _delivery(group, user, *, status="pending", created_at=None):
    return UserNotificationDelivery.create(
        group=group.id,
        user=user.id,
        rule=None,
        method="email",
        event_type="resolved",
        status=status,
        scheduled_at=utc_now() - timedelta(seconds=1),
        created_at=created_at or utc_now(),
    )


def test_stale_processing_resolution_not_delivered_after_second_resolution(db, monkeypatch):
    """Already-claimed jobs survive pending-only reopen cancellation."""
    route, group, user = _resolved_assigned_group(monkeypatch)
    stale = _delivery(group, user, status="processing")
    old_created_at = stale.created_at

    assert upsert_alert(_alert(route)).outcome == "reopened"
    # An already-claimed delivery is not part of pending-only cancellation.
    assert UserNotificationDelivery.get_by_id(stale.id).status == "processing"
    upsert_alert(_alert(route, "resolved"))
    current = AlertGroup.get_by_id(group.id)
    assert current.status == "resolved"
    # Simulate an unambiguously later resolution (without time.sleep()).
    current.resolved_at = old_created_at + timedelta(seconds=60)
    current.assignee = user
    current.save(only=[AlertGroup.resolved_at, AlertGroup.assignee])

    calls = []
    monkeypatch.setitem(
        rules.DIRECT_NOTIFIERS,
        rules.NOTIFICATION_METHOD_EMAIL,
        type("Notifier", (), {
            "send": staticmethod(lambda *args, **kwargs: calls.append(args) or {"provider": "email"}),
        })(),
    )

    assert rules.should_skip_delivery_for_group_status(stale) is True
    assert rules.send_delivery(stale, already_claimed=True) == 0
    refreshed = UserNotificationDelivery.get_by_id(stale.id)
    assert refreshed.status == "skipped"
    assert refreshed.last_error == "alert_group_reopened"
    assert calls == []


def test_valid_delayed_resolution_sends_once_and_claims_delivery(db, monkeypatch):
    _route, group, user = _resolved_assigned_group(monkeypatch)
    delivery = _delivery(group, user)
    calls = []
    monkeypatch.setitem(
        rules.DIRECT_NOTIFIERS,
        rules.NOTIFICATION_METHOD_EMAIL,
        type("Notifier", (), {
            "send": staticmethod(lambda *args, **kwargs: calls.append(args) or {"provider": "email"}),
        })(),
    )

    assert rules.send_delivery(delivery) == 1
    assert rules.send_delivery(delivery) == 0
    assert rules.process_due_user_notifications() == 0
    assert UserNotificationDelivery.get_by_id(delivery.id).status == "sent"
    assert len(calls) == 1


def test_reassigned_resolution_skips_previous_recipient(db, monkeypatch):
    _route, group, original = _resolved_assigned_group(monkeypatch)
    delivery = _delivery(group, original)
    replacement = create_user(group=group.team.group)
    AlertGroup.update(assignee=replacement.id).where(AlertGroup.id == group.id).execute()
    calls = []
    monkeypatch.setitem(
        rules.DIRECT_NOTIFIERS,
        rules.NOTIFICATION_METHOD_EMAIL,
        type("Notifier", (), {
            "send": staticmethod(lambda *args, **kwargs: calls.append(args) or {"provider": "email"}),
        })(),
    )

    assert rules.process_due_user_notifications() == 0
    assert calls == []
    stored = UserNotificationDelivery.get_by_id(delivery.id)
    assert stored.status == "skipped"
    assert stored.last_error == "assignee_changed"


def test_recovery_target_snapshot_fixes_original_assignee(db, monkeypatch):
    from app.modules.db.models import RecoveryNotificationDelivery
    from app.services.alerts import notification_queue

    _route, group, user = _resolved_assigned_group(monkeypatch)
    group.last_notification_at = utc_now()
    group.save(only=[AlertGroup.last_notification_at])

    notification_queue._snapshot_recovery_targets(group, now=utc_now())
    target = RecoveryNotificationDelivery.get(
        (RecoveryNotificationDelivery.group == group.id)
        & (RecoveryNotificationDelivery.target_kind == "user_rules")
    )
    assert target.target_id == user.id

    replacement = create_user(group=group.team.group)
    AlertGroup.update(assignee=replacement.id).where(AlertGroup.id == group.id).execute()
    current = AlertGroup.get_by_id(group.id)
    monkeypatch.setattr(
        rules, "enqueue_user_notifications",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not enqueue for reassigned recipient")
        ),
    )
    assert notification_queue._deliver_recovery_target(current, target) == ("skipped", 0)
