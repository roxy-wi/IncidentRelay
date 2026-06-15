import pytest

from app.modules.db import alerts_repo
from app.services.alerts.lifecycle import upsert_alert
from app.services.notifications.delivery import notify_alert, update_alert_messages
from tests.factories import create_group, create_route, create_team


def _group_and_child():
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
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

    child = alerts_repo.list_alerts_for_group(alert_group.id)[0]

    return alert_group, child


def test_notify_alert_rejects_child_alert(db):
    alert_group, child = _group_and_child()

    with pytest.raises(TypeError, match="AlertGroup"):
        notify_alert(child)


def test_update_alert_messages_rejects_child_alert(db):
    alert_group, child = _group_and_child()

    with pytest.raises(TypeError, match="AlertGroup"):
        update_alert_messages(child, "resolved")
