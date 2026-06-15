import pytest

from app.notifiers.plugins import DiscordNotifier, IncomingWebhookNotifier
from app.notifiers.mattermost.notifier import MattermostNotifier
from tests.factories import create_alert, create_channel, create_group, create_route, create_team


def test_mattermost_bot_payload_contains_action_context(db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    route = create_route(team)
    channel = create_channel(
        group,
        team,
        channel_type="mattermost",
        config={"channel_id": "mm-channel", "callback_secret": "secret"},
    )
    alert = create_alert(route)

    payload = MattermostNotifier()._build_post_payload(
        channel,
        alert,
        "plain text",
        event_type="notification",
        include_actions=True,
    )

    attachment = payload["props"]["attachments"][0]
    actions = attachment["actions"]

    assert payload["channel_id"] == "mm-channel"
    assert [action["name"] for action in actions] == ["Acknowledge", "Resolve"]
    assert actions[0]["id"] == f"ack{alert.id}"
    assert actions[1]["id"] == f"resolve{alert.id}"

    for action in actions:
        context = action["integration"]["context"]
        assert context["alert_id"] == alert.id
        assert context["channel_id"] == channel.id
        assert context["secret"] == "secret"


def test_mattermost_acknowledged_payload_keeps_only_resolve_action(db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    route = create_route(team)
    channel = create_channel(group, team, channel_type="mattermost", config={"channel_id": "mm-channel"})
    alert = create_alert(route)
    alert.status = "acknowledged"

    payload = MattermostNotifier()._build_post_payload(
        channel,
        alert,
        "plain text",
        event_type="acknowledged",
        include_actions=True,
    )

    actions = payload["props"]["attachments"][0]["actions"]
    assert [action["name"] for action in actions] == ["Resolve"]


def test_mattermost_resolved_payload_has_no_actions(db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    route = create_route(team)
    channel = create_channel(group, team, channel_type="mattermost", config={"channel_id": "mm-channel"})
    alert = create_alert(route)
    alert.status = "resolved"

    payload = MattermostNotifier()._build_post_payload(
        channel,
        alert,
        "plain text",
        event_type="resolved",
        include_actions=True,
    )

    attachment = payload["props"]["attachments"][0]
    assert "actions" not in attachment
    assert attachment["title"] == f"RESOLVED: [P3] {alert.title}"


def test_incoming_webhook_requires_webhook_url(db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    route = create_route(team)
    channel = create_channel(group, team, config={})
    alert = create_alert(route)

    with pytest.raises(RuntimeError, match="webhook_url is missing"):
        IncomingWebhookNotifier().send(channel, alert, "text")


def test_discord_notifier_posts_content_payload(monkeypatch, db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    route = create_route(team)
    channel = create_channel(
        group,
        team,
        channel_type="discord",
        config={"webhook_url": "https://discord.example/webhook"},
    )
    alert = create_alert(route)
    calls = []

    class Response:
        def raise_for_status(self):
            calls.append("raise_for_status")

    def fake_post(url, json, timeout):
        calls.append((url, json, timeout))
        return Response()

    monkeypatch.setattr("app.notifiers.plugins.requests.post", fake_post)

    result = DiscordNotifier().send(channel, alert, "discord text")

    assert result == {"provider": "discord"}
    assert calls[0] == (
        "https://discord.example/webhook",
        {"content": "discord text"},
        10,
    )
    assert calls[1] == "raise_for_status"
