from datetime import timedelta

import pytest

from app.modules.db.models import (
    AlertGroup,
    BrowserPushActionToken,
    BrowserPushSubscription,
)
from app.notifiers.browser_push import service as browser_push
from app.services.alerts.lifecycle import upsert_alert
from tests.factories import (
    create_group,
    create_route,
    create_team,
    create_user,
)
from app.modules.common import utc_now


def create_push_subscription(
    user,
    *,
    endpoint="https://push.example.test/subscription-1",
    enabled=True,
    deleted=False,
):
    now = utc_now()

    return BrowserPushSubscription.create(
        user=user.id,
        endpoint=endpoint,
        p256dh="test-p256dh",
        auth="test-auth",
        device_name="Test browser",
        user_agent="pytest",
        enabled=enabled,
        deleted=deleted,
        created_at=now,
        updated_at=now,
        last_seen_at=now,
    )


def create_assigned_group(user, *, status="firing"):
    group = create_group()
    team = create_team(group)
    route = create_route(team, group_by=["alertname", "severity"])

    result = upsert_alert(
        {
            "source": "alertmanager",
            "forced_route_id": route.id,
            "external_id": f"external-{user.id}",
            "dedup_key": f"dedup-{user.id}",
            "title": "DiskFull",
            "message": "/var is 95% full",
            "severity": "critical",
            "labels": {
                "alertname": "DiskFull",
                "severity": "critical",
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
    alert_group.status = status
    alert_group.save()

    return alert_group


def test_save_user_subscription_creates_subscription(db):
    group = create_group()
    user = create_user("alice", group)

    subscription = browser_push.save_user_subscription(
        user,
        endpoint="https://push.example.test/alice",
        keys={
            "p256dh": "p256dh-value",
            "auth": "auth-value",
        },
        device_name="Alice laptop",
        user_agent="pytest-agent",
    )

    assert subscription.id
    assert subscription.user_id == user.id
    assert subscription.endpoint == "https://push.example.test/alice"
    assert subscription.p256dh == "p256dh-value"
    assert subscription.auth == "auth-value"
    assert subscription.device_name == "Alice laptop"
    assert subscription.user_agent == "pytest-agent"
    assert subscription.enabled is True
    assert subscription.deleted is False


def test_save_user_subscription_updates_existing_and_reenables(db):
    group = create_group()
    user = create_user("alice", group)

    existing = create_push_subscription(
        user,
        endpoint="https://push.example.test/alice",
        enabled=False,
        deleted=True,
    )

    updated = browser_push.save_user_subscription(
        user,
        endpoint="https://push.example.test/alice",
        keys={
            "p256dh": "new-p256dh",
            "auth": "new-auth",
        },
        device_name="Updated device",
        user_agent="new-agent",
    )

    assert updated.id == existing.id
    assert updated.p256dh == "new-p256dh"
    assert updated.auth == "new-auth"
    assert updated.device_name == "Updated device"
    assert updated.user_agent == "new-agent"
    assert updated.enabled is True
    assert updated.deleted is False
    assert updated.deleted_at is None


def test_save_user_subscription_requires_endpoint(db):
    group = create_group()
    user = create_user("alice", group)

    with pytest.raises(ValueError, match="endpoint is required"):
        browser_push.save_user_subscription(
            user,
            endpoint=None,
            keys={
                "p256dh": "p256dh",
                "auth": "auth",
            },
        )


def test_save_user_subscription_requires_keys(db):
    group = create_group()
    user = create_user("alice", group)

    with pytest.raises(ValueError, match="subscription keys p256dh/auth are required"):
        browser_push.save_user_subscription(
            user,
            endpoint="https://push.example.test/alice",
            keys={},
        )


def test_list_user_subscriptions_returns_not_deleted_only(db):
    group = create_group()
    user = create_user("alice", group)

    active = create_push_subscription(
        user,
        endpoint="https://push.example.test/active",
        enabled=True,
        deleted=False,
    )
    create_push_subscription(
        user,
        endpoint="https://push.example.test/deleted",
        enabled=False,
        deleted=True,
    )

    rows = browser_push.list_user_subscriptions(user)

    assert len(rows) == 1
    assert rows[0]["id"] == active.id
    assert rows[0]["enabled"] is True
    assert rows[0]["device_name"] == "Test browser"


def test_disable_user_subscription_soft_deletes_own_subscription(db):
    group = create_group()
    user = create_user("alice", group)

    subscription = create_push_subscription(user)

    result = browser_push.disable_user_subscription(user, subscription.id)

    assert result.id == subscription.id

    subscription = BrowserPushSubscription.get_by_id(subscription.id)

    assert subscription.enabled is False
    assert subscription.deleted is True
    assert subscription.deleted_at is not None


def test_disable_user_subscription_does_not_disable_other_user_device(db):
    group = create_group()
    alice = create_user("alice", group)
    bob = create_user("bob", group)

    subscription = create_push_subscription(bob)

    result = browser_push.disable_user_subscription(alice, subscription.id)

    subscription = BrowserPushSubscription.get_by_id(subscription.id)

    assert result is None
    assert subscription.enabled is True
    assert subscription.deleted is False


def test_build_alert_push_payload_for_firing_group_creates_ack_and_resolve_tokens(db, monkeypatch):
    monkeypatch.setattr(
        browser_push.Config,
        "BROWSER_PUSH_ACTION_TOKEN_TTL_SECONDS",
        900,
        raising=False,
    )

    group = create_group()
    user = create_user("alice", group)
    alert_group = create_assigned_group(user, status="firing")

    payload = browser_push.build_alert_push_payload(
        alert_group,
        user,
        event_type="notification",
    )

    assert payload["title"] == "CRITICAL: [P1] DiskFull"
    assert payload["alert_id"] == alert_group.id
    assert payload["alert_group_id"] == alert_group.id
    assert payload["tag"] == f"incidentrelay-alert-group-{alert_group.id}"
    assert payload["require_interaction"] is True
    assert payload["renotify"] is True
    assert payload["silent"] is False
    assert payload["action_tokens"]["ack"]
    assert payload["action_tokens"]["resolve"]
    assert payload["priority"] == "P1"
    assert payload["priority_label"] == "P1 Critical"

    assert (
        BrowserPushActionToken
        .select()
        .where(
            BrowserPushActionToken.group == alert_group.id,
            BrowserPushActionToken.user == user.id,
        )
        .count()
    ) == 2


def test_build_alert_push_payload_for_acknowledged_group_creates_only_resolve_token(db):
    group = create_group()
    user = create_user("alice", group)
    alert_group = create_assigned_group(user, status="acknowledged")

    payload = browser_push.build_alert_push_payload(
        alert_group,
        user,
        event_type="acknowledged",
    )

    assert "ack" not in payload["action_tokens"]
    assert payload["action_tokens"]["resolve"]

    tokens = list(
        BrowserPushActionToken
        .select()
        .where(BrowserPushActionToken.group == alert_group.id)
    )

    assert len(tokens) == 1
    assert tokens[0].action == "resolve"


def test_build_alert_push_payload_for_resolved_group_creates_no_action_tokens(db):
    group = create_group()
    user = create_user("alice", group)
    alert_group = create_assigned_group(user, status="resolved")

    payload = browser_push.build_alert_push_payload(
        alert_group,
        user,
        event_type="resolved",
    )

    assert payload["action_tokens"] == {}
    assert (
        BrowserPushActionToken
        .select()
        .where(BrowserPushActionToken.group == alert_group.id)
        .count()
    ) == 0


def test_send_alert_push_to_user_sends_to_active_subscriptions_only(db, monkeypatch):
    monkeypatch.setattr(browser_push.Config, "BROWSER_PUSH_ENABLED", True, raising=False)

    group = create_group()
    user = create_user("alice", group)
    alert_group = create_assigned_group(user)

    create_push_subscription(
        user,
        endpoint="https://push.example.test/active-1",
        enabled=True,
        deleted=False,
    )
    create_push_subscription(
        user,
        endpoint="https://push.example.test/active-2",
        enabled=True,
        deleted=False,
    )
    create_push_subscription(
        user,
        endpoint="https://push.example.test/deleted",
        enabled=True,
        deleted=True,
    )
    create_push_subscription(
        user,
        endpoint="https://push.example.test/disabled",
        enabled=False,
        deleted=False,
    )

    calls = []

    def fake_webpush(subscription, payload):
        calls.append((subscription.endpoint, payload))

    monkeypatch.setattr(browser_push, "_webpush", fake_webpush)

    sent = browser_push.send_alert_push_to_user(
        user,
        alert_group,
        event_type="notification",
    )

    assert sent == 2
    assert len(calls) == 2
    assert {endpoint for endpoint, _ in calls} == {
        "https://push.example.test/active-1",
        "https://push.example.test/active-2",
    }


def test_send_alert_push_to_user_returns_zero_when_disabled(db, monkeypatch):
    monkeypatch.setattr(browser_push.Config, "BROWSER_PUSH_ENABLED", False, raising=False)

    group = create_group()
    user = create_user("alice", group)
    alert_group = create_assigned_group(user)

    create_push_subscription(user)

    monkeypatch.setattr(
        browser_push,
        "_webpush",
        lambda subscription, payload: pytest.fail("_webpush must not be called"),
    )

    assert browser_push.send_alert_push_to_user(user, alert_group) == 0


def test_send_test_push_ignores_failed_subscription_and_disables_gone_subscription(db, monkeypatch):
    group = create_group()
    user = create_user("alice", group)
    subscription = create_push_subscription(user)

    class FakeWebPushException(Exception):
        def __init__(self):
            super().__init__("gone")
            self.response = type("Response", (), {"status_code": 410})()

    def fake_webpush(subscription, payload):
        raise FakeWebPushException()

    monkeypatch.setattr(browser_push, "WebPushException", FakeWebPushException)
    monkeypatch.setattr(browser_push, "_webpush", fake_webpush)

    sent = browser_push.send_test_push(user)

    subscription = BrowserPushSubscription.get_by_id(subscription.id)

    assert sent == 0
    assert subscription.enabled is False
    assert subscription.deleted is True
    assert subscription.deleted_at is not None


def test_execute_push_action_ack_uses_token_once(db, monkeypatch):
    group = create_group()
    user = create_user("alice", group)
    alert_group = create_assigned_group(user, status="firing")

    token = browser_push.create_action_token(user, alert_group, "ack")

    def fake_run_alert_push_action(group_id, user_id, action):
        assert group_id == alert_group.id
        assert user_id == user.id
        assert action == "ack"

        updated_group = AlertGroup.get_by_id(group_id)
        updated_group.status = "acknowledged"
        updated_group.save()

        return updated_group

    monkeypatch.setattr(browser_push, "_run_alert_push_action", fake_run_alert_push_action)
    monkeypatch.setattr(browser_push, "write_audit", lambda *args, **kwargs: None)

    result = browser_push.execute_push_action(token, "ack")

    assert result == {
        "ok": True,
        "action": "ack",
        "alert_group_id": alert_group.id,
        "alert_id": alert_group.id,
        "status": "acknowledged",
    }

    record = BrowserPushActionToken.get(
        BrowserPushActionToken.token_hash == browser_push._hash_token(token)
    )

    assert record.used_at is not None

    retry = browser_push.execute_push_action(token, "ack")

    assert retry == {
        "ok": False,
        "error": "token_already_used",
    }


def test_execute_push_action_resolve(db, monkeypatch):
    group = create_group()
    user = create_user("alice", group)
    alert_group = create_assigned_group(user, status="acknowledged")

    token = browser_push.create_action_token(user, alert_group, "resolve")

    def fake_run_alert_push_action(group_id, user_id, action):
        updated_group = AlertGroup.get_by_id(group_id)
        updated_group.status = "resolved"
        updated_group.save()

        return updated_group

    monkeypatch.setattr(browser_push, "_run_alert_push_action", fake_run_alert_push_action)
    monkeypatch.setattr(browser_push, "write_audit", lambda *args, **kwargs: None)

    result = browser_push.execute_push_action(token, "resolve")

    assert result["ok"] is True
    assert result["action"] == "resolve"
    assert result["alert_group_id"] == alert_group.id
    assert result["alert_id"] == alert_group.id
    assert result["status"] == "resolved"


def test_execute_push_action_rejects_action_mismatch(db):
    group = create_group()
    user = create_user("alice", group)
    alert_group = create_assigned_group(user)

    token = browser_push.create_action_token(user, alert_group, "ack")

    result = browser_push.execute_push_action(token, "resolve")

    assert result == {
        "ok": False,
        "error": "action_mismatch",
    }


def test_execute_push_action_rejects_expired_token(db):
    group = create_group()
    user = create_user("alice", group)
    alert_group = create_assigned_group(user)

    token = "expired-token"

    BrowserPushActionToken.create(
        user=user.id,
        group=alert_group.id,
        action="ack",
        token_hash=browser_push._hash_token(token),
        expires_at=utc_now() - timedelta(seconds=1),
    )

    result = browser_push.execute_push_action(token, "ack")

    assert result == {
        "ok": False,
        "error": "token_expired",
    }


def test_execute_push_action_rejects_invalid_token(db):
    result = browser_push.execute_push_action("does-not-exist", "ack")

    assert result == {
        "ok": False,
        "error": "invalid_token",
    }


def test_execute_push_action_rejects_invalid_action(db):
    result = browser_push.execute_push_action("some-token", "close")

    assert result == {
        "ok": False,
        "error": "invalid_action",
    }
