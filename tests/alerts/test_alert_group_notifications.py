from datetime import timedelta

from app.modules.db import alerts_repo
from app.modules.db.models import AlertGroup
from app.settings import Config
from app.services.alerts.lifecycle import upsert_alert
import app.services.alerts.notification_queue as notification_queue
from tests.factories import create_group, create_route, create_team
from app.modules.common import utc_now


def _route(group_by=None):
    group = create_group()
    team = create_team(group)
    return create_route(
        team,
        source="webhook",
        matchers={},
        group_by=group_by or ["alertname", "severity"],
    )


def _alert(route, alertname, instance, status="firing"):
    return {
        "source": "webhook",
        "forced_route_id": route.id,
        "external_id": f"{alertname}-{instance}",
        "dedup_key": f"{alertname}:{instance}",
        "status": status,
        "title": alertname,
        "message": f"{alertname} on {instance}",
        "severity": "critical",
        "labels": {
            "alertname": alertname,
            "severity": "critical",
            "instance": instance,
        },
        "payload": {
            "source": "test",
            "instance": instance,
        },
    }


def test_new_group_schedules_notification_instead_of_sending_immediately(db, monkeypatch):
    route = _route(group_by=["alertname", "severity"])
    sent = []

    monkeypatch.setattr(Config, "ALERT_GROUP_WAIT_SECONDS", 30)
    monkeypatch.setattr(
        notification_queue,
        "notify_alert",
        lambda *args, **kwargs: sent.append((args, kwargs)),
    )

    result = upsert_alert(_alert(route, "DiskFull", "host1"))
    group = result.group
    created = result.created_group
    group = alerts_repo.get_alert_group(group.id)

    assert created is True
    assert sent == []
    assert group.notification_pending is True
    assert group.notification_due_at is not None
    assert group.notification_reason == "notification"
    assert group.last_notification_at is None


def test_due_group_notification_is_sent(db, monkeypatch):
    group = create_group()
    team = create_team(group)
    route = create_route(team, group_by=["alertname", "severity"])

    result = upsert_alert(
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
    alert_group = result.group
    created = result.created_group

    assert created is True

    alert_group.notification_pending = True
    alert_group.notification_due_at = utc_now() - timedelta(seconds=1)
    alert_group.notification_reason = "notification"
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
    assert calls == [(alert_group.id, "notification")]
    assert alert_group.notification_pending is False
    assert alert_group.notification_due_at is None
    assert alert_group.last_notification_at is not None


def test_group_resolved_before_group_wait_does_not_send_notification(db, monkeypatch):
    route = _route(group_by=["alertname", "severity"])
    sent = []

    monkeypatch.setattr(Config, "ALERT_GROUP_WAIT_SECONDS", 60)
    monkeypatch.setattr(
        notification_queue,
        "notify_alert",
        lambda *args, **kwargs: sent.append((args, kwargs)),
    )

    result = upsert_alert(_alert(route, "DiskFull", "host1"))
    group = result.group

    upsert_alert(_alert(route, "DiskFull", "host1", status="resolved"))

    group = alerts_repo.get_alert_group(group.id)

    assert group.status == "resolved"
    assert group.notification_pending is False

    result = notification_queue.process_due_alert_group_notifications()

    assert result["sent"] == 0
    assert sent == []
