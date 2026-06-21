from app.modules.db import alerts_repo
from app.services.alerts.lifecycle import upsert_alert
from tests.factories import create_group, create_route, create_silence, create_team


def _alert(route, instance="host1", dedup_key=None):
    return {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": f"external-{instance}",
        "dedup_key": dedup_key or f"dedup-{instance}",
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


def test_silenced_alert_creates_silenced_group_without_notification(monkeypatch, db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    route = create_route(team, group_by=["alertname", "severity"])

    create_silence(
        team,
        matchers={
            "labels": {
                "alertname": "DiskFull",
            }
        },
    )

    calls = []

    monkeypatch.setattr(
        "app.services.alerts.notification_queue.notify_alert",
        lambda alert_group, event_type="notification": calls.append(event_type) or 1,
    )

    result = upsert_alert(_alert(route, "host1"))
    alert_group = result.group
    created = result.created_group

    assert created is True
    assert alert_group.status == "silenced"
    assert alert_group.silenced is True
    assert alert_group.alert_count == 1
    assert alert_group.silenced_count == 1
    assert alert_group.firing_count == 0
    assert alert_group.notification_pending is False
    assert calls == []

    child = alerts_repo.list_alerts_for_group(alert_group.id)[0]

    assert child.status == "silenced"
    assert child.silenced is True


def test_silenced_child_does_not_reopen_acknowledged_group(monkeypatch, db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    route = create_route(team, group_by=["alertname", "severity"])

    result = upsert_alert(_alert(route, "host1", "dedup-host1"))
    alert_group = result.group
    created = result.created_group

    assert created is True

    alerts_repo.acknowledge_alert_group(alert_group.id)

    create_silence(
        team,
        matchers={
            "labels": {
                "instance": "host2",
            }
        },
    )

    calls = []

    monkeypatch.setattr(
        "app.services.alerts.notification_queue.notify_alert",
        lambda alert_group, event_type="notification": calls.append(event_type) or 1,
    )

    result = upsert_alert(_alert(route, "host2", "dedup-host2"))
    alert_group = result.group
    created = result.created_group

    assert created is False
    assert alert_group.status == "acknowledged"
    assert alert_group.alert_count == 2
    assert alert_group.firing_count == 1
    assert alert_group.silenced_count == 1
    assert alert_group.notification_reason != "update"
    assert calls == []

    children = alerts_repo.list_alerts_for_group(alert_group.id)
    statuses = {child.dedup_key: child.status for child in children}

    assert statuses["dedup-host1"] == "firing"
    assert statuses["dedup-host2"] == "silenced"


def test_silenced_child_does_not_schedule_update_for_existing_firing_group(monkeypatch, db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    route = create_route(team, group_by=["alertname", "severity"])

    result = upsert_alert(_alert(route, "host1", "dedup-host1"))
    alert_group = result.group
    created = result.created_group

    assert created is True

    alert_group.notification_pending = False
    alert_group.notification_due_at = None
    alert_group.notification_reason = None
    alert_group.save()

    create_silence(
        team,
        matchers={
            "labels": {
                "instance": "host2",
            }
        },
    )

    result = upsert_alert(_alert(route, "host2", "dedup-host2"))
    alert_group = result.group
    created = result.created_group

    assert created is False
    assert alert_group.status == "firing"
    assert alert_group.firing_count == 1
    assert alert_group.silenced_count == 1
    assert alert_group.notification_pending is False
    assert alert_group.notification_due_at is None
    assert alert_group.notification_reason is None
