import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from urllib.parse import urlencode

from app.notifiers.slack import actions as slack_actions


SIGNING_SECRET = "test-signing-secret"
SLACK_CHANNEL_ID = "C0123456789"


def make_action_body(
    *,
    action="acknowledge",
    alert_id=345,
    local_channel_id=12,
    slack_channel_id=SLACK_CHANNEL_ID,
    slack_user_id="U0123456789",
):
    payload = {
        "type": "block_actions",
        "user": {
            "id": slack_user_id,
        },
        "channel": {
            "id": slack_channel_id,
        },
        "actions": [
            {
                "action_id": (
                    f"incidentrelay_{action}"
                ),
                "value": json.dumps(
                    {
                        "action": action,
                        "alert_id": alert_id,
                        "channel_id": local_channel_id,
                    },
                    separators=(",", ":"),
                ),
            }
        ],
    }

    return urlencode(
        {
            "payload": json.dumps(
                payload,
                separators=(",", ":"),
            )
        }
    ).encode("utf-8")


def sign_body(
    body,
    timestamp,
    secret=SIGNING_SECRET,
):
    base_string = (
        f"v0:{timestamp}:"
    ).encode("utf-8") + body

    digest = hmac.new(
        secret.encode("utf-8"),
        base_string,
        hashlib.sha256,
    ).hexdigest()

    return f"v0={digest}"


def install_action_mocks(
    monkeypatch,
    *,
    channel_team_id=22,
    alert_team_id=22,
):
    channel = SimpleNamespace(
        id=12,
        team_id=channel_team_id,
        enabled=True,
        channel_type="slack",
        config={
            "mode": "bot_api",
            "bot_token": "xoxb-test-token",
            "channel_id": SLACK_CHANNEL_ID,
            "signing_secret": SIGNING_SECRET,
        },
    )

    alert = SimpleNamespace(
        id=345,
        team_id=alert_team_id,
        status="firing",
    )

    user = SimpleNamespace(
        id=7,
    )

    monkeypatch.setattr(
        slack_actions.channels_repo,
        "get_channel",
        lambda channel_id: channel,
    )
    monkeypatch.setattr(
        slack_actions.alerts_repo,
        "get_alert_group",
        lambda alert_id: alert,
    )
    monkeypatch.setattr(
        slack_actions.users_repo,
        "get_user_by_slack_id",
        lambda slack_user_id: user,
    )

    return channel, alert, user


def test_slack_action_acknowledges_alert(
    client,
    monkeypatch,
):
    _, alert, user = install_action_mocks(
        monkeypatch
    )
    calls = []

    def fake_acknowledge(
        alert_id,
        user_id=None,
    ):
        calls.append(
            {
                "alert_id": alert_id,
                "user_id": user_id,
            }
        )
        alert.status = "acknowledged"
        return alert

    monkeypatch.setattr(
        slack_actions,
        "acknowledge_alert",
        fake_acknowledge,
    )

    timestamp = str(int(time.time()))
    body = make_action_body()

    response = client.post(
        "/api/integrations/slack/actions",
        data=body,
        content_type=(
            "application/x-www-form-urlencoded"
        ),
        headers={
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": sign_body(
                body,
                timestamp,
            ),
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "action": "acknowledge",
        "alert_id": alert.id,
        "user_id": user.id,
    }
    assert calls == [
        {
            "alert_id": alert.id,
            "user_id": user.id,
        }
    ]


def test_slack_action_resolves_alert(
    client,
    monkeypatch,
):
    _, alert, user = install_action_mocks(
        monkeypatch
    )
    calls = []

    def fake_resolve(
        alert_id,
        user_id=None,
    ):
        calls.append(
            {
                "alert_id": alert_id,
                "user_id": user_id,
            }
        )
        alert.status = "resolved"
        return alert

    monkeypatch.setattr(
        slack_actions,
        "resolve_alert",
        fake_resolve,
    )

    timestamp = str(int(time.time()))
    body = make_action_body(
        action="resolve"
    )

    response = client.post(
        "/api/integrations/slack/actions",
        data=body,
        content_type=(
            "application/x-www-form-urlencoded"
        ),
        headers={
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": sign_body(
                body,
                timestamp,
            ),
        },
    )

    assert response.status_code == 200
    assert response.get_json()["action"] == "resolve"
    assert calls == [
        {
            "alert_id": alert.id,
            "user_id": user.id,
        }
    ]


def test_slack_action_rejects_invalid_signature(
    client,
    monkeypatch,
):
    install_action_mocks(monkeypatch)

    called = False

    def fake_acknowledge(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        slack_actions,
        "acknowledge_alert",
        fake_acknowledge,
    )

    timestamp = str(int(time.time()))
    body = make_action_body()

    response = client.post(
        "/api/integrations/slack/actions",
        data=body,
        content_type=(
            "application/x-www-form-urlencoded"
        ),
        headers={
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": "v0=invalid",
        },
    )

    assert response.status_code == 403
    assert (
        response.get_json()["error"]
        == "invalid_signature"
    )
    assert called is False


def test_slack_action_rejects_expired_request(
    client,
    monkeypatch,
):
    install_action_mocks(monkeypatch)

    timestamp = str(
        int(time.time()) - 301
    )
    body = make_action_body()

    response = client.post(
        "/api/integrations/slack/actions",
        data=body,
        content_type=(
            "application/x-www-form-urlencoded"
        ),
        headers={
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": sign_body(
                body,
                timestamp,
            ),
        },
    )

    assert response.status_code == 403
    assert (
        response.get_json()["error"]
        == "stale_request"
    )


def test_slack_action_rejects_other_team_alert(
    client,
    monkeypatch,
):
    install_action_mocks(
        monkeypatch,
        channel_team_id=22,
        alert_team_id=23,
    )

    timestamp = str(int(time.time()))
    body = make_action_body()

    response = client.post(
        "/api/integrations/slack/actions",
        data=body,
        content_type=(
            "application/x-www-form-urlencoded"
        ),
        headers={
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": sign_body(
                body,
                timestamp,
            ),
        },
    )

    assert response.status_code == 403
    assert (
        response.get_json()["error"]
        == "action_rejected"
    )


def test_slack_action_rejects_wrong_slack_channel(
    client,
    monkeypatch,
):
    install_action_mocks(monkeypatch)

    timestamp = str(int(time.time()))
    body = make_action_body(
        slack_channel_id="C9999999999"
    )

    response = client.post(
        "/api/integrations/slack/actions",
        data=body,
        content_type=(
            "application/x-www-form-urlencoded"
        ),
        headers={
            "X-Slack-Request-Timestamp": timestamp,
            "X-Slack-Signature": sign_body(
                body,
                timestamp,
            ),
        },
    )

    assert response.status_code == 403
    assert (
        response.get_json()["error"]
        == "action_rejected"
    )
