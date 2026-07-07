from datetime import datetime, timedelta

from app.modules.db import alerts_repo
from app.modules.db.models import AlertGroup
from app.settings import Config
from app.services.alerts.lifecycle import upsert_alert
import app.services.alerts.notification_queue as notification_queue
from tests.factories import create_group, create_route, create_team


def _route(group_by):
    group = create_group()
    team = create_team(group)
    return create_route(
        team,
        source="webhook",
        group_by=group_by,
        matchers={},
    )


def _alert(route, name, instance, status="firing"):
    return {
        "source": "webhook",
        "forced_route_id": route.id,
        "external_id": f"{name}-{instance}",
        "dedup_key": f"{name}:{instance}",
        "status": status,
        "title": name,
        "message": f"{name} on {instance}",
        "severity": "critical",
        "labels": {
            "alertname": name,
            "severity": "critical",
            "instance": instance,
        },
        "payload": {},
    }


def test_alerts_with_same_group_key_create_one_group(db):
    route = _route(group_by=["alertname", "severity"])

    result = upsert_alert(_alert(route, "DiskFull", "host1"))
    group1 = result.group
    created1 = result.created_group

    result = upsert_alert(_alert(route, "DiskFull", "host2"))
    group2 = result.group
    created2 = result.created_group


    assert created1 is True
    assert created2 is False
    assert group1.id == group2.id

    alerts = alerts_repo.list_alerts_for_group(group1.id)
    group = alerts_repo.get_alert_group(group1.id)

    assert len(alerts) == 2
    assert group.alert_count == 2
    assert group.firing_count == 2


def test_ack_group_does_not_ack_each_child_alert(db):
    route = _route(group_by=["alertname", "severity"])
    result = upsert_alert(_alert(route, "DiskFull", "host1"))
    group = result.group


    group = alerts_repo.acknowledge_alert_group(group.id, user_id=None)
    child = alerts_repo.list_alerts_for_group(group.id)[0]

    assert group.status == "acknowledged"
    assert child.status == "firing"


def test_resolve_group_resolves_child_alerts(db):
    route = _route(group_by=["alertname", "severity"])
    result = upsert_alert(_alert(route, "DiskFull", "host1"))
    group = result.group


    group = alerts_repo.resolve_alert_group(group.id)
    child = alerts_repo.list_alerts_for_group(group.id)[0]

    assert group.status == "resolved"
    assert child.status == "resolved"


def test_merge_groups_moves_alerts_to_target(db):
    route = _route(group_by=["alertname", "severity", "instance"])

    result = upsert_alert(_alert(route, "DiskFull", "host1"))
    group1 = result.group

    result = upsert_alert(_alert(route, "DiskFull", "host2"))
    group2 = result.group


    merged = alerts_repo.merge_alert_groups(
        target_group_id=group1.id,
        source_group_ids=[group2.id],
        reason="same incident",
    )

    source = alerts_repo.get_alert_group(group2.id)
    alerts = alerts_repo.list_alerts_for_group(group1.id)

    assert merged.id == group1.id
    assert source.status == "merged"
    assert source.merged_into.id == group1.id
    assert len(alerts) == 2


def test_alerts_api_returns_groups(client, admin_headers, db):
    route = _route(group_by=["alertname", "severity"])

    result = upsert_alert(_alert(route, "DiskFull", "host1"))
    group1 = result.group

    result = upsert_alert(_alert(route, "DiskFull", "host2"))
    group2 = result.group


    response = client.get(
        "/api/alerts",
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()
    ids = [item["id"] for item in payload["items"]]

    assert group1.id == group2.id
    assert group1.id in ids

    item = next(item for item in payload["items"] if item["id"] == group1.id)

    assert item["type"] == "alert_group"
    assert item["alert_count"] == 2
    assert item["firing_count"] == 2


def test_alert_group_details_include_child_alerts(client, admin_headers, db):
    route = _route(group_by=["alertname", "severity"])

    result = upsert_alert(_alert(route, "DiskFull", "host1"))
    group1 = result.group

    upsert_alert(_alert(route, "DiskFull", "host2"))

    response = client.get(
        f"/api/alerts/{group1.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()

    assert payload["id"] == group1.id
    assert payload["type"] == "alert_group"
    assert payload["alert_count"] == 2
    assert len(payload["alerts"]) == 2

    child_instances = {
        alert["labels"]["instance"]
        for alert in payload["alerts"]
    }

    assert child_instances == {"host1", "host2"}


def test_empty_group_by_uses_dedup_key_instead_of_default_labels(db):
    route = _route(group_by=[])

    result = upsert_alert(_alert(route, "DiskFull", "host1"))
    group1 = result.group
    created1 = result.created_group

    result = upsert_alert(_alert(route, "DiskFull", "host2"))
    group2 = result.group
    created2 = result.created_group


    assert created1 is True
    assert created2 is True
    assert group1.id != group2.id

    group1 = alerts_repo.get_alert_group(group1.id)
    group2 = alerts_repo.get_alert_group(group2.id)

    assert group1.alert_count == 1
    assert group2.alert_count == 1


def test_missing_group_by_values_do_not_merge_unrelated_alerts(db):
    route = _route(group_by=["alertname", "severity"])

    alert1 = {
        **_alert(route, "DiskFull", "host1"),
        "labels": {"severity": "critical"},
    }
    alert2 = {
        **_alert(route, "CpuHigh", "host2"),
        "labels": {"severity": "critical"},
    }

    result = upsert_alert(alert1)
    group1 = result.group
    created1 = result.created_group

    result = upsert_alert(alert2)
    group2 = result.group
    created2 = result.created_group

    assert created1 is True
    assert created2 is True
    assert group1.id != group2.id


def test_grouping_respects_route_scope(db):
    route1 = _route(group_by=["alertname", "severity"])
    route2 = _route(group_by=["alertname", "severity"])

    result = upsert_alert(_alert(route1, "DiskFull", "host1"))
    group1 = result.group
    created1 = result.created_group

    result = upsert_alert(_alert(route2, "DiskFull", "host2"))
    group2 = result.group
    created2 = result.created_group


    assert created1 is True
    assert created2 is True
    assert group1.id != group2.id


def test_grouping_respects_configured_labels(db):
    route = _route(group_by=["alertname", "severity", "mount"])

    result = upsert_alert({
        **_alert(route, "DiskFull", "host1"),
        "labels": {
            "alertname": "DiskFull",
            "severity": "critical",
            "instance": "host1",
            "mount": "/var",
        },
    })
    group1 = result.group
    created1 = result.created_group

    result = upsert_alert({
        **_alert(route, "DiskFull", "host2"),
        "labels": {
            "alertname": "DiskFull",
            "severity": "critical",
            "instance": "host2",
            "mount": "/var",
        },
    })
    group2 = result.group
    created2 = result.created_group

    result = upsert_alert({
        **_alert(route, "DiskFull", "host3"),
        "labels": {
            "alertname": "DiskFull",
            "severity": "critical",
            "instance": "host3",
            "mount": "/data",
        },
    })
    group3 = result.group
    created3 = result.created_group


    assert created1 is True
    assert created2 is False
    assert created3 is True
    assert group1.id == group2.id
    assert group1.id != group3.id


def test_acknowledged_group_stays_acknowledged_after_recalculate(db):
    route = _route(group_by=["alertname", "severity"])
    result = upsert_alert(_alert(route, "DiskFull", "host1"))
    group = result.group


    group = alerts_repo.acknowledge_alert_group(group.id)
    group = alerts_repo.recalculate_alert_group(group)
    child = alerts_repo.list_alerts_for_group(group.id)[0]

    assert group.status == "acknowledged"
    assert child.status == "firing"


def test_new_child_alert_reopens_acknowledged_group(db):
    route = _route(group_by=["alertname", "severity"])

    result = upsert_alert(_alert(route, "DiskFull", "host1"))
    group1 = result.group

    alerts_repo.acknowledge_alert_group(group1.id)
    result = upsert_alert(_alert(route, "DiskFull", "host2"))
    group2 = result.group
    created2 = result.created_group


    assert created2 is False
    assert group1.id == group2.id
    assert group2.status == "firing"
    assert group2.acknowledged_at is None


def test_new_group_schedules_notification_instead_of_sending_immediately(db, monkeypatch):
    route = _route(group_by=["alertname", "severity"])
    sent = []

    monkeypatch.setattr(Config, "ALERT_GROUP_WAIT_SECONDS", 30)
    monkeypatch.setattr(
        notification_queue,
        "notify_alert",
        lambda *args, **kwargs: sent.append(args),
    )

    result = upsert_alert(_alert(route, "DiskFull", "host1"))
    group = result.group
    created = result.created_group

    group = alerts_repo.get_alert_group(group.id)

    assert created is True
    assert sent == []
    assert group.notification_pending is True
    assert group.notification_due_at is not None
    assert group.last_notification_at is None


def test_due_group_notification_is_sent(db, monkeypatch):
    group = create_group()
    team = create_team(group)
    route = create_route(
        team,
        source="alertmanager",
        group_by=["alertname", "severity"],
    )

    result = upsert_alert(
        {
            "source": "alertmanager",
            "forced_route_id": route.id,
            "external_id": "external-due-notification",
            "dedup_key": "dedup-due-notification",
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
    alert_group = result.group
    created = result.created_group


    assert created is True

    alert_group.notification_pending = True
    alert_group.notification_due_at = datetime.utcnow() - timedelta(seconds=1)
    alert_group.notification_reason = "notification"
    alert_group.status = "firing"
    alert_group.save()

    calls = []
    monkeypatch.setattr(
        "app.services.notifications.rules.has_deliverable_user_notification",
        lambda group, event_type="notification": True,
    )
    monkeypatch.setattr(
        notification_queue,
        "notify_alert",
        lambda group, event_type="notification": calls.append((group.id, event_type)) or 1,
    )

    result = notification_queue.process_due_alert_group_notifications()
    alert_group = AlertGroup.get_by_id(alert_group.id)

    assert result["processed"] == 1
    assert result["sent"] == 1
    assert result["skipped"] == 0
    assert result["failed"] == 0
    assert calls == [(alert_group.id, "notification")]
    assert alert_group.notification_pending is False
    assert alert_group.notification_due_at is None
    assert alert_group.notification_reason is None
    assert alert_group.last_notification_at is not None


def test_group_resolved_before_group_wait_does_not_send_notification(db, monkeypatch):
    route = _route(group_by=["alertname", "severity"])
    sent = []

    monkeypatch.setattr(Config, "ALERT_GROUP_WAIT_SECONDS", 60)
    monkeypatch.setattr(
        notification_queue,
        "notify_alert",
        lambda *args, **kwargs: sent.append(args),
    )

    result = upsert_alert(_alert(route, "DiskFull", "host1"))
    group = result.group

    child = alerts_repo.list_alerts_for_group(group.id)[0]

    upsert_alert({
        **_alert(route, "DiskFull", "host1", status="resolved"),
        "dedup_key": child.dedup_key,
    })

    group = alerts_repo.get_alert_group(group.id)

    assert group.status == "resolved"
    assert group.notification_pending is False

    result = notification_queue.process_due_alert_group_notifications()

    assert result["sent"] == 0
    assert sent == []


def test_new_child_after_notification_schedules_group_interval_update(db, monkeypatch):
    group = create_group()
    team = create_team(group)
    route = create_route(
        team,
        source="alertmanager",
        group_by=["alertname", "severity"],
    )

    monkeypatch.setattr(
        notification_queue.Config,
        "ALERT_GROUP_WAIT_SECONDS",
        30,
        raising=False,
    )
    monkeypatch.setattr(
        notification_queue.Config,
        "ALERT_GROUP_INTERVAL_SECONDS",
        300,
        raising=False,
    )

    result = upsert_alert(
        {
            "source": "alertmanager",
            "forced_route_id": route.id,
            "external_id": "external-host1",
            "dedup_key": "dedup-host1",
            "title": "DiskFull",
            "message": "/var is 95% full on host1",
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
    alert_group = result.group
    created = result.created_group


    assert created is True
    assert alert_group.status == "firing"
    assert alert_group.notification_pending is True
    assert alert_group.notification_reason == "notification"

    alert_group.notification_due_at = datetime.utcnow() - timedelta(seconds=1)
    alert_group.save()

    calls = []
    monkeypatch.setattr(
        notification_queue,
        "notify_alert",
        lambda group, event_type="notification": calls.append((group.id, event_type)) or 1,
    )

    result = notification_queue.process_due_alert_group_notifications()
    alert_group = AlertGroup.get_by_id(alert_group.id)

    assert result["processed"] == 1
    assert result["sent"] == 1
    assert result["skipped"] == 0
    assert result["failed"] == 0
    assert calls == [(alert_group.id, "notification")]
    assert alert_group.notification_pending is False
    assert alert_group.notification_due_at is None
    assert alert_group.notification_reason is None
    assert alert_group.last_notification_at is not None

    first_notification_at = alert_group.last_notification_at

    result = upsert_alert(
        {
            "source": "alertmanager",
            "forced_route_id": route.id,
            "external_id": "external-host2",
            "dedup_key": "dedup-host2",
            "title": "DiskFull",
            "message": "/var is 95% full on host2",
            "severity": "critical",
            "labels": {
                "alertname": "DiskFull",
                "severity": "critical",
                "instance": "host2",
            },
            "payload": {},
            "status": "firing",
        }
    )
    alert_group = result.group
    created = result.created_group


    alert_group = AlertGroup.get_by_id(alert_group.id)

    assert created is False
    assert alert_group.status == "firing"
    assert alert_group.alert_count == 2
    assert alert_group.firing_count == 2
    assert alert_group.notification_pending is True
    assert alert_group.notification_reason == "update"
    assert alert_group.notification_due_at == first_notification_at + timedelta(seconds=300)
    assert alert_group.last_notification_at == first_notification_at
