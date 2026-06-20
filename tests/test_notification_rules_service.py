from datetime import datetime, timedelta

from app.modules.db.models import (
    UserNotificationDelivery,
)
from app.services.notifications import rules
from app.services.alerts.lifecycle import upsert_alert
from tests.factories import (
    create_group,
    create_route,
    create_team,
    create_user,
)


def create_assigned_group(user, *, status="firing", severity="critical"):
    group = create_group()
    team = create_team(group)
    route = create_route(team, group_by=["alertname", "severity"])

    result = upsert_alert(
        {
            "source": "alertmanager",
            "forced_route_id": route.id,
            "external_id": f"external-{user.id}-{status}-{severity}",
            "dedup_key": f"dedup-{user.id}-{status}-{severity}",
            "title": "DiskFull",
            "message": "/var is 95% full",
            "severity": severity,
            "labels": {
                "alertname": "DiskFull",
                "severity": severity,
                "instance": "host1",
            },
            "payload": {"source": "test"},
            "status": "firing",
        }
    )

    alert_group = result.group
    created = result.created_group

    assert created is True

    alert_group.assignee = user
    alert_group.severity = severity
    alert_group.status = status
    alert_group.save()

    return alert_group


def test_create_user_notification_rule(db):
    group = create_group()
    user = create_user("alice", group)

    rule = rules.create_user_rule(
        user,
        method="browser_push",
        delay_seconds=120,
        severities=["critical"],
        event_types=["notification"],
        enabled=True,
    )

    assert rule.id
    assert rule.user_id == user.id
    assert rule.method == "browser_push"
    assert rule.delay_seconds == 120
    assert rule.severities == ["critical"]
    assert rule.event_types == ["notification"]
    assert rule.position == 1
    assert rule.enabled is True


def test_list_matching_rules_filters_by_event_type_and_severity(db):
    group = create_group()
    user = create_user("alice", group)
    alert_group = create_assigned_group(user, severity="critical")

    matching = rules.create_user_rule(
        user,
        method="browser_push",
        delay_seconds=0,
        severities=["critical"],
        event_types=["notification"],
    )
    rules.create_user_rule(
        user,
        method="email",
        delay_seconds=60,
        severities=["warning"],
        event_types=["notification"],
    )
    rules.create_user_rule(
        user,
        method="voice_call",
        delay_seconds=300,
        severities=["critical"],
        event_types=["resolved"],
    )

    rules1 = rules.list_matching_rules(alert_group, "notification")

    assert [rule.id for rule in rules1] == [matching.id]


def test_has_deliverable_user_notification_uses_default_browser_push_without_custom_rules(
    db,
    monkeypatch,
):
    group = create_group()
    user = create_user("alice", group)
    alert_group = create_assigned_group(user)

    monkeypatch.setattr(
        rules.browser_push,
        "can_send_alert_push",
        lambda pushed_group: pushed_group.id == alert_group.id,
    )

    assert rules.has_deliverable_user_notification(alert_group) is True


def test_has_deliverable_user_notification_uses_custom_rules_when_present(
    db,
    monkeypatch,
):
    group = create_group()
    user = create_user("alice", group)
    alert_group = create_assigned_group(user)

    rules.create_user_rule(
        user,
        method="email",
        delay_seconds=60,
        severities=["critical"],
        event_types=["notification"],
    )

    monkeypatch.setattr(
        rules.browser_push,
        "can_send_alert_push",
        lambda pushed_group: False,
    )

    assert rules.has_deliverable_user_notification(alert_group) is True
    assert rules.has_deliverable_user_notification(
        alert_group,
        event_type="resolved",
    ) is False


def test_enqueue_user_notifications_default_browser_push_sends_immediately(
    db,
    monkeypatch,
):
    group = create_group()
    user = create_user("alice", group)
    alert_group = create_assigned_group(user)

    calls = []

    monkeypatch.setattr(
        rules.browser_push,
        "can_send_alert_push",
        lambda pushed_group: True,
    )

    def fake_send_alert_push_to_user(assignee, pushed_group, event_type="notification"):
        calls.append(
            {
                "user_id": assignee.id,
                "alert_group_id": pushed_group.id,
                "event_type": event_type,
            }
        )
        return 1

    monkeypatch.setattr(
        rules.browser_push,
        "send_alert_push_to_user",
        fake_send_alert_push_to_user,
    )

    sent = rules.enqueue_user_notifications(
        alert_group,
        event_type="notification",
    )

    assert sent == 1
    assert calls == [
        {
            "user_id": user.id,
            "alert_group_id": alert_group.id,
            "event_type": "notification",
        }
    ]

    delivery = UserNotificationDelivery.get(
        UserNotificationDelivery.group == alert_group.id
    )

    assert delivery.rule_id is None
    assert delivery.method == "browser_push"
    assert delivery.status == "sent"
    assert delivery.sent_at is not None


def test_enqueue_user_notifications_creates_pending_delayed_rule(db, monkeypatch):
    group = create_group()
    user = create_user("alice", group)
    alert_group = create_assigned_group(user)

    rule = rules.create_user_rule(
        user,
        method="browser_push",
        delay_seconds=300,
        severities=["critical"],
        event_types=["notification"],
    )

    monkeypatch.setattr(
        rules.browser_push,
        "send_alert_push_to_user",
        lambda *args, **kwargs: 1,
    )

    sent = rules.enqueue_user_notifications(
        alert_group,
        event_type="notification",
    )

    assert sent == 0

    delivery = UserNotificationDelivery.get(
        UserNotificationDelivery.group == alert_group.id
    )

    assert delivery.rule_id == rule.id
    assert delivery.method == "browser_push"
    assert delivery.status == "pending"
    assert delivery.scheduled_at > datetime.utcnow()


def test_process_due_user_notifications_sends_due_delivery(db, monkeypatch):
    group = create_group()
    user = create_user("alice", group)
    alert_group = create_assigned_group(user)

    rule = rules.create_user_rule(
        user,
        method="browser_push",
        delay_seconds=60,
        severities=["critical"],
        event_types=["notification"],
    )

    delivery = UserNotificationDelivery.create(
        group=alert_group.id,
        user=user.id,
        rule=rule.id,
        method="browser_push",
        event_type="notification",
        status="pending",
        scheduled_at=datetime.utcnow() - timedelta(seconds=1),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    calls = []

    def fake_send_alert_push_to_user(assignee, pushed_group, event_type="notification"):
        calls.append((assignee.id, pushed_group.id, event_type))
        return 1

    monkeypatch.setattr(
        rules.browser_push,
        "send_alert_push_to_user",
        fake_send_alert_push_to_user,
    )

    sent = rules.process_due_user_notifications()

    assert sent == 1
    assert calls == [(user.id, alert_group.id, "notification")]

    delivery = UserNotificationDelivery.get_by_id(delivery.id)

    assert delivery.status == "sent"
    assert delivery.sent_at is not None
    assert delivery.provider == "browser_push"
    assert delivery.provider_status == "sent"


def test_process_due_user_notifications_does_not_send_future_delivery(db, monkeypatch):
    group = create_group()
    user = create_user("alice", group)
    alert_group = create_assigned_group(user)

    rule = rules.create_user_rule(
        user,
        method="browser_push",
        delay_seconds=60,
    )

    UserNotificationDelivery.create(
        group=alert_group.id,
        user=user.id,
        rule=rule.id,
        method="browser_push",
        event_type="notification",
        status="pending",
        scheduled_at=datetime.utcnow() + timedelta(minutes=5),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    monkeypatch.setattr(
        rules.browser_push,
        "send_alert_push_to_user",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not send future delivery")
        ),
    )

    assert rules.process_due_user_notifications() == 0


def test_process_due_user_notifications_skips_if_alert_no_longer_firing(
    db,
    monkeypatch,
):
    group = create_group()
    user = create_user("alice", group)
    alert_group = create_assigned_group(user, status="acknowledged")

    rule = rules.create_user_rule(
        user,
        method="browser_push",
        delay_seconds=60,
    )

    delivery = UserNotificationDelivery.create(
        group=alert_group.id,
        user=user.id,
        rule=rule.id,
        method="browser_push",
        event_type="notification",
        status="pending",
        scheduled_at=datetime.utcnow() - timedelta(seconds=1),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    monkeypatch.setattr(
        rules.browser_push,
        "send_alert_push_to_user",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not send for non-firing alert group")
        ),
    )

    sent = rules.process_due_user_notifications()

    assert sent == 0

    delivery = UserNotificationDelivery.get_by_id(delivery.id)

    assert delivery.status == "skipped"
    assert delivery.last_error == "alert_not_firing"


def test_process_due_user_notifications_does_not_send_already_processing_delivery_twice(
    db,
    monkeypatch,
):
    group = create_group()
    user = create_user("alice", group)
    alert_group = create_assigned_group(user)

    rule = rules.create_user_rule(
        user,
        method="browser_push",
        delay_seconds=60,
    )

    UserNotificationDelivery.create(
        group=alert_group.id,
        user=user.id,
        rule=rule.id,
        method="browser_push",
        event_type="notification",
        status="processing",
        scheduled_at=datetime.utcnow() - timedelta(seconds=1),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )

    monkeypatch.setattr(
        rules.browser_push,
        "send_alert_push_to_user",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not send already processing delivery from query")
        ),
    )

    assert rules.process_due_user_notifications() == 0
