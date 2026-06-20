from datetime import datetime, timedelta

from app.modules.db.models import AlertEvent, AlertGroup
from app.services.alerts.escalation import maybe_escalate_alert
from app.services.alerts.lifecycle import upsert_alert
from app.services.alerts.reminders import send_unacked_reminders
import app.services.alerts.escalation as alert_escalation
import app.services.alerts.notification_queue as notification_queue
from app.settings import Config
from tests.factories import (
    add_user_to_team,
    create_escalation_policy,
    create_escalation_policy_rule,
    create_group,
    create_route,
    create_rotation,
    create_team,
    create_user,
    unique,
)


def normalized_alert(**overrides):
    data = {
        "source": "alertmanager",
        "team_slug": "sre",
        "external_id": unique("external"),
        "dedup_key": unique("dedup"),
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


def test_admin_can_create_policy_and_rotation_rule(client, admin_headers, db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    user = create_user("alice", group)
    add_user_to_team(team, user)
    rotation = create_rotation(team, users=[user])

    response = client.post(
        "/api/escalation-policies",
        json={
            "team_id": team.id,
            "name": "Critical policy",
            "description": "Critical alert chain",
            "enabled": True,
            "repeat_count": 1,
        },
        headers=admin_headers,
    )

    assert response.status_code == 201

    policy = response.get_json()

    assert policy["name"] == "Critical policy"
    assert policy["team_id"] == team.id
    assert policy["repeat_count"] == 1
    assert policy["rules"] == []

    response = client.post(
        f"/api/escalation-policies/{policy['id']}/rules",
        json={
            "position": 1,
            "delay_seconds": 60,
            "target_type": "rotation",
            "target_id": rotation.id,
            "enabled": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 201

    rule = response.get_json()

    assert rule["policy_id"] == policy["id"]
    assert rule["position"] == 1
    assert rule["delay_seconds"] == 60
    assert rule["target_type"] == "rotation"
    assert rule["target_id"] == rotation.id


def test_policy_rule_rejects_rotation_from_another_team(client, admin_headers, db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    other_team = create_team(group, slug=unique("other-team"))
    user = create_user("alice", group)
    add_user_to_team(other_team, user)
    rotation = create_rotation(other_team, users=[user])
    policy = create_escalation_policy(team)

    response = client.post(
        f"/api/escalation-policies/{policy.id}/rules",
        json={
            "position": 1,
            "delay_seconds": 60,
            "target_type": "rotation",
            "target_id": rotation.id,
            "enabled": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "rotation_team_mismatch"


def test_policy_rule_rejects_user_outside_team(client, admin_headers, db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    other_group = create_group(slug=unique("other-group"))
    other_team = create_team(other_group, slug=unique("other-team"))
    outsider = create_user("outsider", other_group)
    add_user_to_team(other_team, outsider)
    policy = create_escalation_policy(team)

    response = client.post(
        f"/api/escalation-policies/{policy.id}/rules",
        json={
            "position": 1,
            "delay_seconds": 60,
            "target_type": "user",
            "target_id": outsider.id,
            "enabled": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "user_team_mismatch"


def test_upsert_alert_with_policy_uses_first_rule_target(monkeypatch, db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    user = create_user("alice", group)
    add_user_to_team(team, user)
    rotation = create_rotation(team, users=[user])
    policy = create_escalation_policy(team)
    rule = create_escalation_policy_rule(
        policy,
        position=1,
        delay_seconds=60,
        target_type="rotation",
        rotation=rotation,
    )
    route = create_route(team, escalation_policy=policy)
    calls = []

    monkeypatch.setattr(Config, "ALERT_GROUP_WAIT_SECONDS", 0, raising=False)
    monkeypatch.setattr(
        notification_queue,
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
    assert alert_group.route.id == route.id
    assert alert_group.escalation_policy.id == policy.id
    assert alert_group.escalation_rule.id == rule.id
    assert alert_group.rotation.id == rotation.id
    assert alert_group.assignee.id == user.id
    assert alert_group.next_escalation_at is not None

    result = notification_queue.process_due_alert_group_notifications()

    assert result["sent"] == 1
    assert calls == [(alert_group.id, "notification")]


def test_policy_escalation_moves_alert_to_next_rule(monkeypatch, db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    first_user = create_user("alice", group)
    second_user = create_user("bob", group)
    add_user_to_team(team, first_user)
    add_user_to_team(team, second_user)
    first_rotation = create_rotation(team, name="Primary", users=[first_user])
    second_rotation = create_rotation(team, name="Backup", users=[second_user])
    policy = create_escalation_policy(team)
    first_rule = create_escalation_policy_rule(
        policy,
        position=1,
        delay_seconds=60,
        target_type="rotation",
        rotation=first_rotation,
    )
    second_rule = create_escalation_policy_rule(
        policy,
        position=2,
        delay_seconds=120,
        target_type="rotation",
        rotation=second_rotation,
    )
    create_route(team, escalation_policy=policy)

    monkeypatch.setattr(
        "app.services.notifications.rules.has_deliverable_user_notification",
        lambda alert_group, event_type="notification": True,
    )
    monkeypatch.setattr(
        notification_queue,
        "notify_alert",
        lambda alert_group, event_type="notification": 1,
    )

    result = upsert_alert(normalized_alert())
    alert_group = result.group
    created = result.created_group


    assert created is True
    assert alert_group.escalation_rule.id == first_rule.id
    assert alert_group.assignee.id == first_user.id

    alert_group.next_escalation_at = datetime.utcnow() - timedelta(seconds=1)
    alert_group.save()

    calls = []
    monkeypatch.setattr(
        alert_escalation,
        "notify_alert",
        lambda alert_group, event_type="escalation": calls.append(event_type) or 1,
    )

    assert maybe_escalate_alert(alert_group) is True

    alert_group = AlertGroup.get_by_id(alert_group.id)

    assert alert_group.escalation_rule.id == second_rule.id
    assert alert_group.rotation.id == second_rotation.id
    assert alert_group.assignee.id == second_user.id
    assert alert_group.escalation_level == 1
    assert alert_group.reminder_count == 0
    assert alert_group.last_escalated_at is not None
    assert calls == ["escalation"]
    assert AlertEvent.select().where(
        (AlertEvent.group == alert_group.id) & (AlertEvent.event_type == "escalated")
    ).exists()


def test_policy_alert_ignores_team_escalation_after_reminders(monkeypatch, db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    team.escalation_enabled = True
    team.escalation_after_reminders = 1
    team.save()
    first_user = create_user("alice", group)
    second_user = create_user("bob", group)
    add_user_to_team(team, first_user)
    add_user_to_team(team, second_user)
    first_rotation = create_rotation(team, name="Primary", users=[first_user])
    second_rotation = create_rotation(team, name="Backup", users=[second_user])
    policy = create_escalation_policy(team)
    first_rule = create_escalation_policy_rule(
        policy,
        position=1,
        delay_seconds=3600,
        target_type="rotation",
        rotation=first_rotation,
    )
    create_escalation_policy_rule(
        policy,
        position=2,
        delay_seconds=3600,
        target_type="rotation",
        rotation=second_rotation,
    )
    create_route(team, escalation_policy=policy)

    monkeypatch.setattr(notification_queue, "notify_alert", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        "app.services.notifications.rules.has_deliverable_user_notification",
        lambda alert_group, event_type="notification": True,
    )

    result = upsert_alert(normalized_alert())
    alert_group = result.group
    created = result.created_group


    assert created is True

    alert_group.reminder_count = 10
    alert_group.next_escalation_at = datetime.utcnow() + timedelta(minutes=30)
    alert_group.save()

    assert maybe_escalate_alert(alert_group) is False

    alert_group = AlertGroup.get_by_id(alert_group.id)

    assert alert_group.escalation_rule.id == first_rule.id
    assert alert_group.assignee.id == first_user.id


def test_policy_escalation_runs_when_reminder_interval_is_disabled(monkeypatch, db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    first_user = create_user("alice", group)
    second_user = create_user("bob", group)
    add_user_to_team(team, first_user)
    add_user_to_team(team, second_user)
    first_rotation = create_rotation(team, name="Primary", users=[first_user])
    second_rotation = create_rotation(team, name="Backup", users=[second_user])
    first_rotation.reminder_interval_seconds = 0
    first_rotation.save()
    policy = create_escalation_policy(team)
    create_escalation_policy_rule(
        policy,
        position=1,
        delay_seconds=60,
        target_type="rotation",
        rotation=first_rotation,
    )
    second_rule = create_escalation_policy_rule(
        policy,
        position=2,
        delay_seconds=120,
        target_type="rotation",
        rotation=second_rotation,
    )
    create_route(team, escalation_policy=policy)

    monkeypatch.setattr(alert_escalation, "notify_alert", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        "app.services.notifications.rules.has_deliverable_user_notification",
        lambda alert_group, event_type="notification": True,
    )

    result = upsert_alert(normalized_alert())
    alert_group = result.group
    created = result.created_group


    assert created is True

    alert_group.next_escalation_at = datetime.utcnow() - timedelta(seconds=1)
    alert_group.save()

    assert send_unacked_reminders() == 1

    alert_group = AlertGroup.get_by_id(alert_group.id)

    assert alert_group.escalation_rule.id == second_rule.id
    assert alert_group.assignee.id == second_user.id


def test_alert_details_include_policy_state(client, admin_headers, monkeypatch, db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    user = create_user("alice", group)
    add_user_to_team(team, user)
    rotation = create_rotation(team, users=[user])
    policy = create_escalation_policy(team, name="Critical escalation")
    rule = create_escalation_policy_rule(
        policy,
        position=1,
        delay_seconds=300,
        target_type="rotation",
        rotation=rotation,
    )
    create_route(team, escalation_policy=policy)

    monkeypatch.setattr(notification_queue, "notify_alert", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        "app.services.notifications.rules.has_deliverable_user_notification",
        lambda alert_group, event_type="notification": True,
    )

    result = upsert_alert(normalized_alert())
    alert_group = result.group
    created = result.created_group


    assert created is True

    response = client.get(
        f"/api/alerts/{alert_group.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200

    data = response.get_json()

    assert data["escalation_mode"] == "policy"
    assert data["escalation_policy_id"] == policy.id
    assert data["escalation_policy_name"] == "Critical escalation"
    assert data["escalation_rule_id"] == rule.id
    assert data["escalation_rule_position"] == 1
    assert data["escalation_rule_target_type"] == "rotation"
    assert data["next_escalation_at"] is not None
    assert data["team_escalation_enabled"] is not None


def test_policy_exhausted_alert_does_not_send_more_reminders(monkeypatch, db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    user = create_user("alice", group)
    add_user_to_team(team, user)
    rotation = create_rotation(team, users=[user])
    policy = create_escalation_policy(
        team,
        repeat_count=0,
    )
    rule = create_escalation_policy_rule(
        policy,
        position=1,
        delay_seconds=60,
        target_type="rotation",
        rotation=rotation,
    )
    create_route(team, escalation_policy=policy)
    calls = []

    monkeypatch.setattr(
        notification_queue,
        "notify_alert",
        lambda alert_group, event_type="notification": calls.append(event_type) or 1,
    )
    monkeypatch.setattr(
        "app.services.notifications.rules.has_deliverable_user_notification",
        lambda alert_group, event_type="notification": True,
    )

    result = upsert_alert(normalized_alert())
    alert_group = result.group
    created = result.created_group


    assert created is True
    assert alert_group.escalation_rule.id == rule.id

    alert_group.next_escalation_at = None
    alert_group.save()
    calls.clear()

    assert send_unacked_reminders() == 0
    assert calls == []
