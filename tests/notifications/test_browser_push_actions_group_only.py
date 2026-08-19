from datetime import timedelta

import pytest

from app.modules.db.models import AlertGroup, BrowserPushActionToken
from app.notifiers.browser_push import service as browser_push
from app.services.alerts.lifecycle import upsert_alert
from tests.factories import add_user_to_team, create_group, create_route, create_team, create_user
from app.modules.common import utc_now


@pytest.fixture(autouse=True)
def disable_browser_push_audit(monkeypatch):
    monkeypatch.setattr(
        browser_push,
        "write_audit",
        lambda *args, **kwargs: None,
    )


def _group_with_user(status="firing"):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    user = create_user("alice", group)

    add_user_to_team(team, user)

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

    if status == "acknowledged":
        alert_group.status = "acknowledged"
        alert_group.save()
    elif status == "resolved":
        alert_group.status = "resolved"
        alert_group.save()

    return alert_group, user


def test_build_alert_push_payload_creates_group_action_tokens_for_firing_group(db):
    alert_group, user = _group_with_user(status="firing")

    payload = browser_push.build_alert_push_payload(
        alert_group,
        user,
        event_type="notification",
    )

    assert payload["alert_group_id"] == alert_group.id
    assert payload["alert_id"] == alert_group.id
    assert payload["status"] == "firing"
    assert set(payload["action_tokens"].keys()) == {"ack", "resolve"}

    tokens = list(BrowserPushActionToken.select())

    assert len(tokens) == 2
    assert {token.group_id for token in tokens} == {alert_group.id}
    assert {token.user_id for token in tokens} == {user.id}
    assert {token.action for token in tokens} == {"ack", "resolve"}


def test_build_alert_push_payload_creates_only_resolve_token_for_acknowledged_group(db):
    alert_group, user = _group_with_user(status="acknowledged")

    payload = browser_push.build_alert_push_payload(
        alert_group,
        user,
        event_type="acknowledged",
    )

    assert payload["alert_group_id"] == alert_group.id
    assert set(payload["action_tokens"].keys()) == {"resolve"}

    token = BrowserPushActionToken.get()

    assert token.group_id == alert_group.id
    assert token.user_id == user.id
    assert token.action == "resolve"


def test_execute_push_action_acknowledges_group(db):
    alert_group, user = _group_with_user(status="firing")

    payload = browser_push.build_alert_push_payload(
        alert_group,
        user,
        event_type="notification",
    )

    result = browser_push.execute_push_action(
        payload["action_tokens"]["ack"],
        "ack",
    )

    stored = AlertGroup.get_by_id(alert_group.id)

    assert result["ok"] is True
    assert result["action"] == "ack"
    assert result["alert_group_id"] == alert_group.id
    assert result["alert_id"] == alert_group.id
    assert result["status"] == "acknowledged"
    assert stored.status == "acknowledged"
    assert stored.acknowledged_by_id == user.id


def test_execute_push_action_resolves_group(db):
    alert_group, user = _group_with_user(status="firing")

    payload = browser_push.build_alert_push_payload(
        alert_group,
        user,
        event_type="notification",
    )

    result = browser_push.execute_push_action(
        payload["action_tokens"]["resolve"],
        "resolve",
    )

    stored = AlertGroup.get_by_id(alert_group.id)

    assert result["ok"] is True
    assert result["action"] == "resolve"
    assert result["alert_group_id"] == alert_group.id
    assert result["status"] == "resolved"
    assert stored.status == "resolved"
    assert stored.resolved_by_id == user.id


def test_execute_push_action_rejects_token_reuse(db):
    alert_group, user = _group_with_user(status="firing")

    payload = browser_push.build_alert_push_payload(
        alert_group,
        user,
        event_type="notification",
    )

    token = payload["action_tokens"]["ack"]

    first = browser_push.execute_push_action(token, "ack")
    second = browser_push.execute_push_action(token, "ack")

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["error"] == "token_already_used"


def test_execute_push_action_rejects_expired_token(db):
    alert_group, user = _group_with_user(status="firing")

    payload = browser_push.build_alert_push_payload(
        alert_group,
        user,
        event_type="notification",
    )

    token_value = payload["action_tokens"]["ack"]

    token = BrowserPushActionToken.get(BrowserPushActionToken.action == "ack")
    token.expires_at = utc_now() - timedelta(seconds=1)
    token.save()

    result = browser_push.execute_push_action(token_value, "ack")

    assert result["ok"] is False
    assert result["error"] == "token_expired"


def test_execute_push_action_rejects_wrong_action_for_token(db):
    alert_group, user = _group_with_user(status="firing")

    payload = browser_push.build_alert_push_payload(
        alert_group,
        user,
        event_type="notification",
    )

    result = browser_push.execute_push_action(
        payload["action_tokens"]["ack"],
        "resolve",
    )

    assert result["ok"] is False
    assert result["error"] == "action_mismatch"
