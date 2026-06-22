import json
from types import SimpleNamespace

import pytest

from app.api.schemas.channels import (
    ChannelCreateSchema,
)
from app.notifiers.slack.notifier import (
    SlackNotifier,
)


def make_channel(config):
    return SimpleNamespace(
        id=7,
        config=config,
    )


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_slack_schema_accepts_webhook_mode():
    channel = ChannelCreateSchema(
        team_id=1,
        name="Slack alerts",
        channel_type="slack",
        config={
            "mode": "webhook",
            "webhook_url": (
                "https://hooks.slack.com/services/test"
            ),
        },
    )

    assert channel.config["mode"] == "webhook"
    assert channel.config["webhook_url"].startswith(
        "https://hooks.slack.com/"
    )


def test_slack_schema_accepts_bot_api_mode():
    channel = ChannelCreateSchema(
        team_id=1,
        name="Slack bot",
        channel_type="slack",
        config={
            "mode": "bot_api",
            "bot_token": "xoxb-test-token",
            "channel_id": "C0123456789",
            "signing_secret": "signing-secret",
        },
    )

    assert channel.config == {
        "mode": "bot_api",
        "bot_token": "xoxb-test-token",
        "channel_id": "C0123456789",
        "signing_secret": "signing-secret",
    }


@pytest.mark.parametrize(
    "missing_field",
    [
        "bot_token",
        "channel_id",
        "signing_secret",
    ],
)
def test_slack_schema_rejects_incomplete_bot_config(
    missing_field,
):
    config = {
        "mode": "bot_api",
        "bot_token": "xoxb-test-token",
        "channel_id": "C0123456789",
        "signing_secret": "signing-secret",
    }
    config.pop(missing_field)

    with pytest.raises(
        ValueError,
        match="slack Bot API mode requires",
    ):
        ChannelCreateSchema(
            team_id=1,
            name="Slack bot",
            channel_type="slack",
            config=config,
        )


def test_slack_bot_channel_supports_updates():
    notifier = SlackNotifier()

    assert notifier.can_update(
        make_channel({
            "mode": "bot_api",
            "bot_token": "xoxb-test-token",
            "channel_id": "C0123456789",
            "signing_secret": "secret",
        })
    ) is True

    assert notifier.can_update(
        make_channel({
            "mode": "webhook",
            "webhook_url": (
                "https://hooks.slack.com/services/test"
            ),
        })
    ) is False


def test_slack_bot_send_uses_chat_post_message(
    monkeypatch,
):
    notifier = SlackNotifier()
    calls = []

    monkeypatch.setattr(
        notifier,
        "_build_message_payload",
        lambda *args, **kwargs: {
            "text": "Fallback",
            "blocks": [],
        },
    )

    def fake_post(url, **kwargs):
        calls.append({
            "url": url,
            **kwargs,
        })

        return FakeResponse({
            "ok": True,
            "channel": "C0123456789",
            "ts": "1710000000.000001",
        })

    monkeypatch.setattr(
        "app.notifiers.slack.notifier.requests.post",
        fake_post,
    )

    channel = make_channel({
        "mode": "bot_api",
        "bot_token": "xoxb-test-token",
        "channel_id": "C0123456789",
        "signing_secret": "secret",
    })

    result = notifier.send(
        channel,
        SimpleNamespace(),
        "Alert text",
    )

    assert calls[0]["url"] == (
        "https://slack.com/api/chat.postMessage"
    )
    assert calls[0]["headers"]["Authorization"] == (
        "Bearer xoxb-test-token"
    )
    assert calls[0]["json"]["channel"] == (
        "C0123456789"
    )
    assert calls[0]["json"]["text"] == "Fallback"

    assert result == {
        "provider": "slack",
        "external_message_id": (
            "1710000000.000001"
        ),
        "external_channel_id": "C0123456789",
        "provider_status": "sent",
    }


def test_slack_update_uses_chat_update(
    monkeypatch,
):
    notifier = SlackNotifier()
    calls = []

    monkeypatch.setattr(
        notifier,
        "_build_message_payload",
        lambda *args, **kwargs: {
            "text": "Updated fallback",
            "blocks": [],
        },
    )

    def fake_post(url, **kwargs):
        calls.append({
            "url": url,
            **kwargs,
        })

        return FakeResponse({
            "ok": True,
            "channel": "C0123456789",
            "ts": "1710000000.000001",
        })

    monkeypatch.setattr(
        "app.notifiers.slack.notifier.requests.post",
        fake_post,
    )

    channel = make_channel({
        "mode": "bot_api",
        "bot_token": "xoxb-test-token",
        "channel_id": "C0123456789",
        "signing_secret": "secret",
    })

    alert = SimpleNamespace(
        status="acknowledged",
    )
    delivery = SimpleNamespace(
        external_message_id=(
            "1710000000.000001"
        ),
        external_channel_id="C0123456789",
    )

    result = notifier.update(
        channel,
        alert,
        "Updated alert",
        delivery,
        event_type="acknowledged",
    )

    assert calls[0]["url"] == (
        "https://slack.com/api/chat.update"
    )
    assert calls[0]["json"]["channel"] == (
        "C0123456789"
    )
    assert calls[0]["json"]["ts"] == (
        "1710000000.000001"
    )

    assert result["provider_status"] == "updated"


def test_slack_resolved_update_removes_actions(
    monkeypatch,
):
    notifier = SlackNotifier()
    include_actions = []

    def fake_build(
        *args,
        **kwargs,
    ):
        include_actions.append(
            kwargs["include_actions"]
        )

        return {
            "text": "Resolved",
            "blocks": [],
        }

    monkeypatch.setattr(
        notifier,
        "_build_message_payload",
        fake_build,
    )

    monkeypatch.setattr(
        "app.notifiers.slack.notifier.requests.post",
        lambda *args, **kwargs: FakeResponse({
            "ok": True,
            "channel": "C0123456789",
            "ts": "1710000000.000001",
        }),
    )

    notifier.update(
        make_channel({
            "mode": "bot_api",
            "bot_token": "xoxb-test-token",
            "channel_id": "C0123456789",
            "signing_secret": "secret",
        }),
        SimpleNamespace(
            status="resolved",
        ),
        "Resolved",
        SimpleNamespace(
            external_message_id=(
                "1710000000.000001"
            ),
            external_channel_id=(
                "C0123456789"
            ),
        ),
        event_type="resolved",
    )

    assert include_actions == [False]


def test_slack_buttons_contain_alert_context():
    notifier = SlackNotifier()

    channel = SimpleNamespace(
        id=12,
    )
    alert = SimpleNamespace(
        id=345,
        status="firing",
    )

    actions_block = notifier._actions(
        channel,
        alert,
    )

    assert actions_block["type"] == "actions"
    assert actions_block["block_id"] == "incidentrelay_alert_345"

    buttons = actions_block["elements"]

    assert len(buttons) == 2

    acknowledge_button = next(
        button
        for button in buttons
        if button["action_id"] == "incidentrelay_acknowledge"
    )
    resolve_button = next(
        button
        for button in buttons
        if button["action_id"] == "incidentrelay_resolve"
    )

    acknowledge_context = json.loads(
        acknowledge_button["value"]
    )
    resolve_context = json.loads(
        resolve_button["value"]
    )

    assert acknowledge_context == {
        "action": "acknowledge",
        "alert_id": 345,
        "channel_id": 12,
    }
    assert resolve_context == {
        "action": "resolve",
        "alert_id": 345,
        "channel_id": 12,
    }

    assert acknowledge_button["style"] == "primary"
    assert resolve_button["style"] == "danger"


def test_slack_api_error_is_not_treated_as_success(monkeypatch):
    notifier = SlackNotifier()

    channel = SimpleNamespace(
        id=12,
        config={
            "mode": "bot_api",
            "bot_token": "xoxb-test-token",
            "channel_id": "C0123456789",
            "signing_secret": "test-signing-secret",
        },
    )

    alert = SimpleNamespace(
        id=345,
        status="firing",
        severity="critical",
        source="test",
        message="Test alert",
        team=None,
        assignee=None,
        acknowledged_by=None,
    )

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": False,
                "error": "invalid_auth",
            }

    def fake_post(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(
        "app.notifiers.slack.notifier.requests.post",
        fake_post,
    )

    with pytest.raises(RuntimeError) as exc_info:
        notifier.send(
            channel,
            alert,
            "Test alert",
            event_type="notification",
        )

    error_message = str(exc_info.value)

    assert "Slack API" in error_message
    assert "invalid_auth" in error_message
