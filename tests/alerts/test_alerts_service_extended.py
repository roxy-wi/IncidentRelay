from datetime import datetime, timedelta

from app.modules.db import alerts_repo, escalation_policies_repo
from app.modules.db.models import Alert, AlertEvent, AlertGroup
from app.services.alerts.actions import acknowledge_alert, resolve_alert
from app.services.alerts.escalation import maybe_escalate_alert
from app.services.alerts.lifecycle import upsert_alert
from app.services.alerts.reminders import (
    get_alert_reminder_interval,
    send_unacked_reminders,
    should_send_reminder,
)
import app.services.alerts.escalation as alert_escalation
import app.services.alerts.lifecycle as alert_lifecycle
import app.services.alerts.reminders as alert_reminders
from tests.factories import (
    add_user_to_team,
    create_group,
    create_route,
    create_rotation,
    create_silence,
    create_team,
    create_user,
)
from app.modules.common import utc_now


def normalized_alert(**overrides):
    data = {
        "source": "alertmanager",
        "team_slug": "sre",
        "external_id": "external-1",
        "dedup_key": "dedup-1",
        "title": "DiskFull",
        "message": "/var is 95% full",
        "severity": "critical",
        "labels": {
            "alertname": "DiskFull",
            "severity": "critical",
            "instance": "host1",
            "team": "sre",
        },
        "payload": {"source": "test"},
        "status": "firing",
    }
    data.update(overrides)
    return data


def create_alert_group_for_route(route, **overrides):
    data = normalized_alert(
        forced_route_id=route.id,
        team_slug=None,
    )
    data.update(overrides)

    result = upsert_alert(data)
    alert_group = result.group

    assert alert_group is not None

    return alert_group


def test_upsert_alert_creates_routed_alert_with_current_oncall(monkeypatch, db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    user = create_user("alice", group)
    add_user_to_team(team, user)
    rotation = create_rotation(team, users=[user])
    route = create_route(team, rotation=rotation)
    calls = []

    monkeypatch.setattr(
        alert_lifecycle,
        "notify_alert",
        lambda alert_group, event_type="notification": calls.append(
            (alert_group.id, event_type)
        )
        or 1,
    )

    result = upsert_alert(normalized_alert())
    alert_group = result.group
    created = result.created_group

    assert created is True
    assert alert_group.team == team
    assert alert_group.route == route
    assert alert_group.rotation == rotation
    assert alert_group.assignee == user
    assert alert_group.group_key == (
        f"source=alertmanager|team_id={route.team_id}|"
        f"route_id={route.id}|service_id=|"
        "dedup_key=dedup-1"
    )
    assert alert_group.status == "firing"

    child = alerts_repo.list_alerts_for_group(alert_group.id)[0]

    assert child.dedup_key == "dedup-1"
    assert child.team == team
    assert child.route == route
    assert child.rotation == rotation
    assert child.assignee == user
    assert calls == []
    assert AlertEvent.select().where(
        (AlertEvent.group == alert_group.id) & (AlertEvent.event_type == "created")
    ).exists()


def test_upsert_alert_ignores_orphan_resolved_payload(monkeypatch, db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    create_route(team)

    monkeypatch.setattr(
        alert_lifecycle,
        "notify_alert",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not notify")
        ),
    )

    result = upsert_alert(normalized_alert(status="resolved"))
    alert_group = result.group
    created = result.created_group

    assert alert_group is None
    assert created is False
    assert Alert.select().count() == 0
    assert AlertGroup.select().count() == 0


def test_upsert_alert_preserves_acknowledged_status_when_payload_fires_again(db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    create_route(team)

    result = upsert_alert(normalized_alert())
    alert_group = result.group
    created = result.created_group

    assert created is True

    alerts_repo.acknowledge_alert_group(alert_group.id)

    result = upsert_alert(normalized_alert(message="updated message"))
    alert_group = result.group
    created = result.created_group

    assert created is False
    assert alert_group.status == "acknowledged"
    assert alert_group.message == "updated message"

    child = alerts_repo.list_alerts_for_group(alert_group.id)[0]

    assert child.status == "firing"
    assert child.message == "updated message"
    assert AlertEvent.select().where(
        (AlertEvent.group == alert_group.id) & (AlertEvent.event_type == "updated")
    ).exists()


def test_upsert_alert_resolves_existing_alert_and_notifies(monkeypatch, db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    create_route(team)

    result = upsert_alert(normalized_alert())
    alert_group = result.group
    created = result.created_group

    assert created is True

    alert_group.last_notification_at = utc_now()
    alert_group.save()

    calls = []
    monkeypatch.setattr(
        alert_lifecycle,
        "notify_alert",
        lambda alert_group, event_type="notification": calls.append(event_type) or 1,
    )

    result = upsert_alert(normalized_alert(status="resolved"))
    alert_group = result.group
    created = result.created_group

    assert created is False
    assert alert_group.status == "resolved"
    assert alert_group.resolved_at is not None

    child = alerts_repo.list_alerts_for_group(alert_group.id)[0]

    assert child.status == "resolved"
    assert child.resolved_at is not None
    assert calls == ["resolved"]


def test_upsert_alert_creates_silenced_alert_without_notification(monkeypatch, db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    create_route(team)
    silence = create_silence(team, matchers={"labels": {"alertname": "DiskFull"}})

    monkeypatch.setattr(
        alert_lifecycle,
        "notify_alert",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not notify")
        ),
    )

    result = upsert_alert(normalized_alert())
    alert_group = result.group
    created = result.created_group

    assert created is True
    assert alert_group.status == "silenced"
    assert alert_group.silenced is True

    child = alerts_repo.list_alerts_for_group(alert_group.id)[0]

    assert child.status == "silenced"
    assert child.silenced is True
    assert AlertEvent.select().where(
        (AlertEvent.group == alert_group.id)
        & (AlertEvent.event_type == "silenced")
        & (AlertEvent.message.contains(silence.name))
    ).exists()


def test_acknowledge_and_resolve_alert_update_statuses_and_create_events(
    monkeypatch,
    db,
):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    user = create_user("alice", group)
    create_route(team)

    result = upsert_alert(normalized_alert())
    alert_group = result.group
    created = result.created_group

    assert created is True

    updates = []
    monkeypatch.setattr(
        "app.services.alerts.actions.update_alert_messages",
        lambda alert_group, event_type: updates.append((alert_group.id, event_type))
        or 1,
    )

    acknowledged = acknowledge_alert(alert_group.id, user_id=user.id)
    resolved = resolve_alert(alert_group.id, user_id=user.id)

    assert acknowledged.status == "acknowledged"
    assert acknowledged.acknowledged_by == user
    assert acknowledged.acknowledged_at is not None
    assert resolved.status == "resolved"
    assert resolved.resolved_at is not None
    assert updates == [
        (alert_group.id, "acknowledged"),
        (alert_group.id, "resolved"),
    ]
    assert [
        event.event_type
        for event in (
            AlertEvent.select()
            .where(
                (AlertEvent.group == alert_group.id)
                & (AlertEvent.event_type.in_(["acknowledged", "resolved"]))
            )
            .order_by(AlertEvent.id.asc())
        )
    ] == ["acknowledged", "resolved"]


def _create_firing_alert_group_for_reminder(route, *, dedup_key, instance):
    result = upsert_alert(
        {
            "source": "alertmanager",
            "forced_route_id": route.id,
            "external_id": f"external-{dedup_key}",
            "dedup_key": dedup_key,
            "title": "DiskFull",
            "message": f"/var is 95% full on {instance}",
            "severity": "critical",
            "labels": {
                "alertname": "DiskFull",
                "severity": "critical",
                "instance": instance,
            },
            "payload": {},
            "status": "firing",
        }
    )
    alert_group = result.group
    created = result.created_group

    assert alert_group is not None
    assert created is True

    return alert_group


def test_reminder_interval_uses_rotation_before_global_config(db, monkeypatch):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    rotation = create_rotation(team)
    rotation.reminder_interval_seconds = 30
    rotation.save()
    route = create_route(
        team,
        source="alertmanager",
        rotation=rotation,
        group_by=["alertname", "severity"],
    )
    alert_group = _create_firing_alert_group_for_reminder(
        route,
        dedup_key="dedup-reminder-rotation",
        instance="host1",
    )

    now = utc_now()
    alert_group.last_notification_at = now - timedelta(seconds=31)
    alert_group.notification_pending = False
    alert_group.notification_due_at = None
    alert_group.notification_reason = None
    alert_group.save()
    alert_group = AlertGroup.get_by_id(alert_group.id)

    assert get_alert_reminder_interval(alert_group) == 30
    assert should_send_reminder(alert_group, now) is True

    alert_group.last_notification_at = now - timedelta(seconds=29)
    alert_group.save()
    alert_group = AlertGroup.get_by_id(alert_group.id)

    assert should_send_reminder(alert_group, now) is False

    alert_group.last_notification_at = None
    alert_group.save()
    alert_group = AlertGroup.get_by_id(alert_group.id)

    assert should_send_reminder(alert_group, now) is False


def test_send_unacked_reminders_counts_only_successful_sends(monkeypatch, db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    rotation = create_rotation(team)
    rotation.reminder_interval_seconds = 30
    rotation.save()
    route = create_route(
        team,
        source="alertmanager",
        rotation=rotation,
        group_by=["alertname", "severity", "instance"],
    )
    successful_group = _create_firing_alert_group_for_reminder(
        route,
        dedup_key="dedup-reminder-success",
        instance="host1",
    )
    failed_group = _create_firing_alert_group_for_reminder(
        route,
        dedup_key="dedup-reminder-failed",
        instance="host2",
    )

    assert successful_group.id != failed_group.id

    now = utc_now()
    for alert_group in (successful_group, failed_group):
        alert_group = AlertGroup.get_by_id(alert_group.id)
        alert_group.rotation = rotation.id
        alert_group.status = "firing"
        alert_group.last_notification_at = now - timedelta(seconds=120)
        alert_group.notification_pending = False
        alert_group.notification_due_at = None
        alert_group.notification_reason = None
        alert_group.reminder_count = 0
        alert_group.save()

    monkeypatch.setattr(
        alert_reminders.alerts_repo,
        "list_firing_alert_groups",
        lambda: [
            AlertGroup.get_by_id(successful_group.id),
            AlertGroup.get_by_id(failed_group.id),
        ],
    )
    monkeypatch.setattr(
        "app.services.notifications.rules.has_deliverable_user_notification",
        lambda alert_group, event_type="notification": True,
    )
    monkeypatch.setattr(
        alert_reminders,
        "maybe_escalate_alert",
        lambda alert_group: False,
    )

    sent_calls = []

    def fake_notify_alert(alert_group, event_type="reminder"):
        assert event_type == "reminder"
        sent_calls.append(alert_group.id)

        if alert_group.id == successful_group.id:
            return 1

        return 0

    monkeypatch.setattr(
        alert_reminders,
        "notify_alert",
        fake_notify_alert,
    )

    count = send_unacked_reminders()
    successful_group = AlertGroup.get_by_id(successful_group.id)
    failed_group = AlertGroup.get_by_id(failed_group.id)

    assert count == 1
    assert sent_calls == [successful_group.id, failed_group.id]
    assert successful_group.reminder_count == 1
    assert failed_group.reminder_count == 0

    successful_events = list(
        AlertEvent.select().where(
            (AlertEvent.group == successful_group.id)
            & (AlertEvent.event_type == "reminder_sent")
        )
    )
    failed_events = list(
        AlertEvent.select().where(
            (AlertEvent.group == failed_group.id)
            & (AlertEvent.event_type == "reminder_sent")
        )
    )

    assert len(successful_events) == 1
    assert successful_events[0].message == "Reminder count: 1"
    assert failed_events == []


def test_zero_reminder_interval_disables_reminders(db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    rotation = create_rotation(team)
    rotation.reminder_interval_seconds = 0
    rotation.save()
    route = create_route(team, rotation=rotation)
    alert_group = create_alert_group_for_route(route)
    alert_group.last_notification_at = None

    assert get_alert_reminder_interval(alert_group) == 0
    assert should_send_reminder(alert_group, utc_now()) is False


def test_send_unacked_reminders_does_not_increment_when_no_notification_was_sent(
    monkeypatch,
    db,
):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    rotation = create_rotation(team)
    route = create_route(team, rotation=rotation)
    alert_group = create_alert_group_for_route(route)
    alert_group.last_notification_at = None
    alert_group.save()

    monkeypatch.setattr(
        "app.services.notifications.rules.has_deliverable_user_notification",
        lambda alert_group, event_type="notification": True,
    )
    monkeypatch.setattr(
        alert_reminders,
        "maybe_escalate_alert",
        lambda alert_group: False,
    )
    monkeypatch.setattr(
        alert_reminders,
        "notify_alert",
        lambda alert_group, event_type="reminder": 0,
    )

    assert send_unacked_reminders() == 0

    stored = AlertGroup.get_by_id(alert_group.id)

    assert stored.reminder_count == 0


def test_maybe_escalate_alert_assigns_next_rotation_user(monkeypatch, db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    team.escalation_after_reminders = 0
    team.save()
    first = create_user("alice", group)
    second = create_user("bob", group)
    add_user_to_team(team, first)
    add_user_to_team(team, second)
    rotation = create_rotation(team, users=[first, second])
    route = create_route(team, rotation=rotation)
    alert_group = create_alert_group_for_route(route)
    alert_group.assignee = first
    alert_group.reminder_count = 1
    alert_group.save()
    calls = []

    monkeypatch.setattr(
        "app.services.notifications.rules.has_deliverable_user_notification",
        lambda alert_group, event_type="notification": True,
    )
    monkeypatch.setattr(
        alert_escalation,
        "notify_alert",
        lambda alert_group, event_type="escalation": calls.append(event_type) or 1,
    )

    assert maybe_escalate_alert(alert_group) is True

    stored = AlertGroup.get_by_id(alert_group.id)

    assert stored.assignee == second
    assert stored.escalation_level == 1
    assert stored.reminder_count == 0
    assert calls == ["escalation"]


def test_policy_alert_assigns_user_when_first_enabled_rule_position_is_not_one(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="test")
    alice = create_user(group=group)
    add_user_to_team(team, alice)
    policy = escalation_policies_repo.create_policy(
        team_id=team.id,
        name="Default policy",
        enabled=True,
        repeat_count=0,
    )
    rule = escalation_policies_repo.create_rule(
        policy_id=policy.id,
        position=2,
        delay_seconds=300,
        target_type="user",
        target_id=alice.id,
        enabled=True,
    )
    route.escalation_policy = policy
    route.save()

    result = upsert_alert(
        {
            "source": "test",
            "dedup_key": "policy-user-position-2",
            "title": "Policy user test",
            "message": "test",
            "severity": "critical",
            "labels": {
                "alertname": "PolicyUserTest",
                "severity": "critical",
            },
            "payload": {},
            "status": "firing",
        }
    )
    alert_group = result.group
    created = result.created_group

    assert alert_group is not None
    assert created is True
    assert alert_group.escalation_policy_id == policy.id
    assert alert_group.escalation_rule_id == rule.id
    assert alert_group.rotation_id is None
    assert alert_group.assignee_id == alice.id
    assert alert_group.next_escalation_at is not None


def test_policy_alert_assigns_rotation_when_first_enabled_rule_position_is_not_one(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="test")
    alice = create_user(group=group)
    add_user_to_team(team, alice)
    rotation = create_rotation(
        team,
        users=[alice],
        duration_seconds=86400,
    )
    policy = escalation_policies_repo.create_policy(
        team_id=team.id,
        name="Default policy",
        enabled=True,
        repeat_count=0,
    )
    rule = escalation_policies_repo.create_rule(
        policy_id=policy.id,
        position=2,
        delay_seconds=300,
        target_type="rotation",
        target_id=rotation.id,
        enabled=True,
    )
    route.escalation_policy = policy
    route.save()

    result = upsert_alert(
        {
            "source": "test",
            "dedup_key": "policy-rotation-position-2",
            "title": "Policy rotation test",
            "message": "test",
            "severity": "critical",
            "labels": {
                "alertname": "PolicyRotationTest",
                "severity": "critical",
            },
            "payload": {},
            "status": "firing",
        }
    )
    alert_group = result.group
    created = result.created_group

    assert alert_group is not None
    assert created is True
    assert alert_group.escalation_policy_id == policy.id
    assert alert_group.escalation_rule_id == rule.id
    assert alert_group.rotation_id == rotation.id
    assert alert_group.assignee_id == alice.id
    assert alert_group.next_escalation_at is not None


def test_policy_alert_assigns_rotation_when_first_rule_was_deleted_and_second_is_rotation(
    db,
):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="test")
    alice = create_user(group=group)
    add_user_to_team(team, alice)
    rotation = create_rotation(
        team,
        users=[alice],
        duration_seconds=86400,
    )
    policy = escalation_policies_repo.create_policy(
        team_id=team.id,
        name="Default policy",
        enabled=True,
        repeat_count=0,
    )
    first_rule = escalation_policies_repo.create_rule(
        policy_id=policy.id,
        position=1,
        delay_seconds=60,
        target_type="rotation",
        target_id=rotation.id,
        enabled=True,
    )
    second_rule = escalation_policies_repo.create_rule(
        policy_id=policy.id,
        position=2,
        delay_seconds=300,
        target_type="rotation",
        target_id=rotation.id,
        enabled=True,
    )
    escalation_policies_repo.delete_rule(first_rule.id)
    route.escalation_policy = policy
    route.save()

    result = upsert_alert(
        {
            "source": "test",
            "dedup_key": "policy-second-rule-rotation",
            "title": "Policy rotation test",
            "message": "test",
            "severity": "critical",
            "labels": {
                "alertname": "PolicyRotationTest",
                "severity": "critical",
            },
            "payload": {},
            "status": "firing",
        }
    )
    alert_group = result.group
    created = result.created_group

    assert alert_group is not None
    assert created is True
    assert alert_group.escalation_policy_id == policy.id
    assert alert_group.escalation_rule_id == second_rule.id
    assert alert_group.rotation_id == rotation.id
    assert alert_group.assignee_id == alice.id
    assert alert_group.next_escalation_at is not None


def test_maybe_escalate_alert_updates_state_without_notification_target(
    monkeypatch,
    db,
):
    group = create_group(slug="infra-no-escalation-target")
    team = create_team(group, slug="sre-no-escalation-target")
    team.escalation_after_reminders = 0
    team.save()
    first = create_user("alice-no-target", group)
    second = create_user("bob-no-target", group)
    add_user_to_team(team, first)
    add_user_to_team(team, second)
    rotation = create_rotation(team, users=[first, second])
    route = create_route(team, rotation=rotation)
    alert_group = create_alert_group_for_route(route)
    alert_group.assignee = first
    alert_group.reminder_count = 1
    alert_group.save()

    monkeypatch.setattr(
        alert_escalation,
        "has_matching_notification_channel",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        alert_escalation,
        "notify_alert",
        lambda *args, **kwargs: 0,
    )

    assert maybe_escalate_alert(alert_group) is True

    stored = AlertGroup.get_by_id(alert_group.id)

    assert stored.assignee == second
    assert stored.escalation_level == 1
    assert stored.reminder_count == 0
    assert AlertEvent.select().where(
        (AlertEvent.group == stored.id)
        & (AlertEvent.event_type == "escalation_notification_skipped")
    ).exists()


def test_maybe_escalate_alert_records_notification_failure_after_transition(
    monkeypatch,
    db,
):
    group = create_group(slug="infra-escalation-failure")
    team = create_team(group, slug="sre-escalation-failure")
    team.escalation_after_reminders = 0
    team.save()
    first = create_user("alice-delivery-failure", group)
    second = create_user("bob-delivery-failure", group)
    add_user_to_team(team, first)
    add_user_to_team(team, second)
    rotation = create_rotation(team, users=[first, second])
    route = create_route(team, rotation=rotation)
    alert_group = create_alert_group_for_route(route)
    alert_group.assignee = first
    alert_group.reminder_count = 1
    alert_group.save()

    monkeypatch.setattr(
        alert_escalation,
        "has_matching_notification_channel",
        lambda *args, **kwargs: True,
    )

    def fail_delivery(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(alert_escalation, "notify_alert", fail_delivery)

    assert maybe_escalate_alert(alert_group) is True

    stored = AlertGroup.get_by_id(alert_group.id)

    assert stored.assignee == second
    assert stored.escalation_level == 1
    assert AlertEvent.select().where(
        (AlertEvent.group == stored.id)
        & (AlertEvent.event_type == "escalation_notification_failed")
    ).exists()
