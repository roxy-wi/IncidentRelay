from datetime import datetime, timedelta

from app.modules.db.models import UserNotificationDelivery
from app.services.notifications import rules
from app.services.alerts.actions import resolve_alert
from app.services.alerts.lifecycle import upsert_alert
from tests.factories import add_user_to_team, create_group, create_route, create_team, create_user


def _group_with_assignee():
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    user = create_user("alice", group)

    add_user_to_team(team, user)

    route = create_route(team, group_by=["alertname", "severity"])

    alert_group, created = upsert_alert(
        {
            "source": "alertmanager",
            "forced_route_id": route.id,
            "external_id": "external-1",
            "dedup_key": "dedup-1",
            "title": "DiskFull",
            "message": "/var is 95% full",
            "severity": "critical",
            "labels": {
                "alertname": "DiskFull",
                "severity": "critical",
                "instance": "host1",
            },
            "payload": {},
            "status": "firing",
        }
    )

    assert created is True

    alert_group.assignee = user
    alert_group.save()

    return alert_group, user


def test_has_deliverable_user_notification_uses_default_browser_push_for_group(db, monkeypatch):
    alert_group, user = _group_with_assignee()

    monkeypatch.setattr(
        rules.browser_push,
        "can_send_alert_push",
        lambda group: group.id == alert_group.id,
    )

    assert rules.has_deliverable_user_notification(alert_group) is True


def test_enqueue_user_notifications_creates_group_delivery_for_default_browser_push(db, monkeypatch):
    alert_group, user = _group_with_assignee()

    monkeypatch.setattr(
        rules.browser_push,
        "send_alert_push_to_user",
        lambda assignee, group, event_type="notification": 1,
    )

    sent = rules.enqueue_user_notifications(
        alert_group,
        event_type="notification",
    )

    assert sent == 1

    delivery = UserNotificationDelivery.get()

    assert delivery.group_id == alert_group.id
    assert delivery.user_id == user.id
    assert delivery.alert_id is None if hasattr(delivery, "alert_id") else True
    assert delivery.method == "browser_push"
    assert delivery.status == "sent"
    assert delivery.provider == "browser_push"


def test_custom_delayed_user_notification_is_skipped_when_group_no_longer_firing(db, monkeypatch):
    alert_group, user = _group_with_assignee()

    rules.create_user_rule(
        user,
        method="browser_push",
        delay_seconds=60,
        severities=["critical"],
        event_types=["notification"],
        enabled=True,
    )

    created = rules.enqueue_user_notifications(
        alert_group,
        event_type="notification",
    )

    assert created == 0

    delivery = UserNotificationDelivery.get()
    assert delivery.group_id == alert_group.id
    assert delivery.status == "pending"

    resolve_alert(alert_group.id, user_id=user.id)

    delivery.scheduled_at = datetime.utcnow() - timedelta(seconds=1)
    delivery.save()

    monkeypatch.setattr(
        rules.browser_push,
        "send_alert_push_to_user",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not send skipped notification")
        ),
    )

    processed = rules.process_due_user_notifications()

    delivery = UserNotificationDelivery.get_by_id(delivery.id)

    assert processed == 0
    assert delivery.status == "skipped"
    assert delivery.last_error == "alert_not_firing"


def test_resolved_user_notification_is_not_skipped_when_group_is_resolved(db, monkeypatch):
    alert_group, user = _group_with_assignee()

    rules.create_user_rule(
        user,
        method="browser_push",
        delay_seconds=60,
        severities=["critical"],
        event_types=["resolved"],
        enabled=True,
    )

    resolve_alert(alert_group.id, user_id=user.id)

    created = rules.enqueue_user_notifications(
        alert_group,
        event_type="resolved",
    )

    assert created == 0

    delivery = UserNotificationDelivery.get()
    delivery.scheduled_at = datetime.utcnow() - timedelta(seconds=1)
    delivery.save()

    calls = []

    monkeypatch.setattr(
        rules.browser_push,
        "send_alert_push_to_user",
        lambda assignee, group, event_type="resolved": calls.append(
            (assignee.id, group.id, event_type)
        ) or 1,
    )

    processed = rules.process_due_user_notifications()

    delivery = UserNotificationDelivery.get_by_id(delivery.id)

    assert processed == 1
    assert delivery.status == "sent"
    assert delivery.group_id == alert_group.id
    assert calls == [(user.id, alert_group.id, "resolved")]


def test_rules_reject_child_alert_objects(db):
    alert_group, user = _group_with_assignee()

    child = alert_group.alerts[0]

    try:
        rules.has_deliverable_user_notification(child)
    except TypeError as exc:
        assert "AlertGroup" in str(exc)
    else:
        raise AssertionError("child Alert must not be accepted")
