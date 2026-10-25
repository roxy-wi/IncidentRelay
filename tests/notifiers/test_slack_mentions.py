import json
from types import SimpleNamespace

import pytest

from app.api.schemas.channels import ChannelCreateSchema
from app.notifiers.slack.notifier import SlackNotifier


def make_channel(config):
    return SimpleNamespace(id=7, config=config)


def make_alert(assignee=None, rotation=None, team=None, source="alertmanager"):
    return SimpleNamespace(
        id=123,
        title="DiskFull",
        message="/var is 95% full",
        severity="critical",
        status="firing",
        source=source,
        priority=None,
        priority_slug=None,
        priority_order=None,
        team=team,
        service=None,
        service_id=None,
        assignee=assignee,
        rotation=rotation,
    )


def make_user(user_id=7, display_name="Ann", slack_user_id="U012ABCDEF"):
    return SimpleNamespace(
        id=user_id,
        display_name=display_name,
        username=display_name.lower(),
        slack_user_id=slack_user_id,
        active=True,
        deleted=False,
    )


def field_value(notifier, alert, channel, label):
    """Return the rendered value of one Slack field, or None when absent."""
    prefix = f"*{label}*\n"

    for field in notifier._field_blocks(alert, channel=channel):
        if field["text"].startswith(prefix):
            return field["text"][len(prefix):]

    return None


# --- 8.1 assignee mention rendering -----------------------------------------


def test_assignee_with_slack_user_id_renders_mention():
    notifier = SlackNotifier()

    value = field_value(
        notifier,
        make_alert(assignee=make_user()),
        make_channel({"mention_assignee": True}),
        "Assignee",
    )

    assert value == "<@U012ABCDEF>"


def test_assignee_without_slack_user_id_falls_back_to_display_name():
    notifier = SlackNotifier()

    value = field_value(
        notifier,
        make_alert(assignee=make_user(slack_user_id=None)),
        make_channel({"mention_assignee": True}),
        "Assignee",
    )

    assert value == "Ann"
    assert "<@" not in value


def test_alert_without_assignee_renders_placeholder():
    notifier = SlackNotifier()

    value = field_value(
        notifier,
        make_alert(assignee=None),
        make_channel({"mention_assignee": True}),
        "Assignee",
    )

    assert value == "-"


# --- 8.2 invalid IDs and escaping -------------------------------------------


@pytest.mark.parametrize(
    "slack_user_id",
    [
        "not-an-id",
        "u012abcdef",
        "<@U012ABCDEF>",
        "U012 ABCDEF",
        "X012ABCDEF",
        "U",
        "'; DROP TABLE users; --",
    ],
)
def test_invalid_slack_user_id_is_never_rendered_as_mention(slack_user_id):
    notifier = SlackNotifier()

    value = field_value(
        notifier,
        make_alert(assignee=make_user(slack_user_id=slack_user_id)),
        make_channel({"mention_assignee": True}),
        "Assignee",
    )

    assert value == "Ann"
    assert "<@" not in value


def test_display_name_fallback_stays_escaped():
    notifier = SlackNotifier()

    value = field_value(
        notifier,
        make_alert(
            assignee=make_user(
                display_name="A<b>&c",
                slack_user_id=None,
            )
        ),
        make_channel({"mention_assignee": True}),
        "Assignee",
    )

    assert value == "A&lt;b&gt;&amp;c"


def test_other_fields_remain_escaped_when_mentions_enabled():
    notifier = SlackNotifier()

    value = field_value(
        notifier,
        make_alert(
            assignee=make_user(),
            team=SimpleNamespace(name="Infra<&>", slug="infra"),
        ),
        make_channel({"mention_assignee": True}),
        "Team",
    )

    assert value == "Infra&lt;&amp;&gt;"


# --- 8.3 on-call mention ----------------------------------------------------


def test_oncall_mention_resolved_at_send_time(monkeypatch):
    notifier = SlackNotifier()
    oncall = make_user(user_id=9, display_name="Bob", slack_user_id="U999BOB")
    rotation = SimpleNamespace(id=3, enabled=True, deleted=False)

    monkeypatch.setattr(
        "app.notifiers.slack.notifier.get_current_oncall_user",
        lambda rot: oncall if rot is rotation else None,
    )

    value = field_value(
        notifier,
        make_alert(assignee=None, rotation=rotation),
        make_channel({"mention_oncall": True}),
        "On-call",
    )

    assert value == "<@U999BOB>"


def test_oncall_field_omitted_without_rotation():
    notifier = SlackNotifier()

    value = field_value(
        notifier,
        make_alert(assignee=make_user(), rotation=None),
        make_channel({"mention_oncall": True}),
        "On-call",
    )

    assert value is None


def test_oncall_field_omitted_when_nobody_is_oncall(monkeypatch):
    notifier = SlackNotifier()
    rotation = SimpleNamespace(id=3, enabled=True, deleted=False)

    monkeypatch.setattr(
        "app.notifiers.slack.notifier.get_current_oncall_user",
        lambda rot: None,
    )

    value = field_value(
        notifier,
        make_alert(rotation=rotation),
        make_channel({"mention_oncall": True}),
        "On-call",
    )

    assert value is None


def test_oncall_resolution_failure_omits_field(monkeypatch):
    notifier = SlackNotifier()
    rotation = SimpleNamespace(id=3, enabled=True, deleted=False)

    def boom(rot):
        raise RuntimeError("rotation lookup failed")

    monkeypatch.setattr(
        "app.notifiers.slack.notifier.get_current_oncall_user",
        boom,
    )

    value = field_value(
        notifier,
        make_alert(rotation=rotation),
        make_channel({"mention_oncall": True}),
        "On-call",
    )

    assert value is None


def test_oncall_equal_to_assignee_is_mentioned_once(monkeypatch):
    notifier = SlackNotifier()
    user = make_user()
    rotation = SimpleNamespace(id=3, enabled=True, deleted=False)

    monkeypatch.setattr(
        "app.notifiers.slack.notifier.get_current_oncall_user",
        lambda rot: user,
    )

    alert = make_alert(assignee=user, rotation=rotation)
    channel = make_channel({
        "mention_assignee": True,
        "mention_oncall": True,
    })

    fields = notifier._field_blocks(alert, channel=channel)
    rendered = "".join(field["text"] for field in fields)

    assert rendered.count("<@U012ABCDEF>") == 1
    assert field_value(notifier, alert, channel, "Assignee") == "<@U012ABCDEF>"
    assert field_value(notifier, alert, channel, "On-call") == "Ann"


def test_oncall_mentioned_when_assignee_mention_disabled(monkeypatch):
    notifier = SlackNotifier()
    user = make_user()
    rotation = SimpleNamespace(id=3, enabled=True, deleted=False)

    monkeypatch.setattr(
        "app.notifiers.slack.notifier.get_current_oncall_user",
        lambda rot: user,
    )

    alert = make_alert(assignee=user, rotation=rotation)
    channel = make_channel({"mention_oncall": True})

    assert field_value(notifier, alert, channel, "Assignee") == "Ann"
    assert field_value(notifier, alert, channel, "On-call") == "<@U012ABCDEF>"


# --- 8.4 defaults are unchanged --------------------------------------------


def test_channel_without_mention_config_renders_plain_name():
    notifier = SlackNotifier()

    value = field_value(
        notifier,
        make_alert(assignee=make_user()),
        make_channel({}),
        "Assignee",
    )

    assert value == "Ann"


def test_payload_without_mention_config_matches_previous_output():
    """A channel with no mention config must render exactly as before."""
    notifier = SlackNotifier()
    alert = make_alert(assignee=make_user())

    payload = notifier._build_message_payload(
        make_channel({}),
        alert,
        "DiskFull",
        "notification",
        include_actions=False,
    )

    fields = payload["blocks"][2]["fields"]

    assert [field["text"].split("\n")[0] for field in fields] == [
        "*Team*",
        "*Service*",
        "*Status*",
        "*Severity*",
        "*Priority*",
        "*Assignee*",
        "*Source*",
        "*Alert ID*",
    ]
    assert fields[5]["text"] == "*Assignee*\nAnn"
    assert "<@" not in json.dumps(payload)


@pytest.mark.parametrize("value", ["true", 1, 0, None, [], {}])
def test_non_boolean_mention_config_does_not_enable_mentions(value):
    notifier = SlackNotifier()

    rendered = field_value(
        notifier,
        make_alert(assignee=make_user()),
        make_channel({"mention_assignee": value}),
        "Assignee",
    )

    assert rendered == "Ann"


# --- 8.5 config validation -------------------------------------------------


def slack_webhook_config(**extra):
    config = {"webhook_url": "https://hooks.slack.com/services/T/B/x"}
    config.update(extra)
    return config


@pytest.mark.parametrize("flag", ["mention_assignee", "mention_oncall"])
def test_schema_accepts_boolean_mention_flags(flag):
    schema = ChannelCreateSchema(
        name="slack-ops",
        channel_type="slack",
        config=slack_webhook_config(**{flag: True}),
    )

    assert schema.config[flag] is True


@pytest.mark.parametrize("flag", ["mention_assignee", "mention_oncall"])
@pytest.mark.parametrize("value", ["true", "yes", 1, 0, [], {}, None])
def test_schema_rejects_non_boolean_mention_flags(flag, value):
    with pytest.raises(ValueError) as exc:
        ChannelCreateSchema(
            name="slack-ops",
            channel_type="slack",
            config=slack_webhook_config(**{flag: value}),
        )

    assert f"slack {flag} must be a boolean" in str(exc.value)


def test_mention_flags_survive_bot_api_mode():
    schema = ChannelCreateSchema(
        name="slack-ops",
        channel_type="slack",
        config={
            "mode": "bot_api",
            "bot_token": "xoxb-test-token",
            "channel_id": "C0123456789",
            "signing_secret": "secret",
            "mention_oncall": True,
        },
    )

    assert schema.config["mention_oncall"] is True


def test_mention_flags_survive_webhook_mode():
    schema = ChannelCreateSchema(
        name="slack-ops",
        channel_type="slack",
        config=slack_webhook_config(mention_assignee=True),
    )

    assert schema.config["mention_assignee"] is True
    assert schema.config["mode"] == "webhook"


# --- 2.8 both transports render mentions identically ------------------------


def test_webhook_and_bot_api_modes_render_same_mentions(monkeypatch):
    notifier = SlackNotifier()
    user = make_user()
    alert = make_alert(assignee=user)

    webhook_payload = notifier._build_message_payload(
        make_channel({
            "mode": "webhook",
            "webhook_url": "https://hooks.slack.com/x",
            "mention_assignee": True,
        }),
        alert,
        "DiskFull",
        "notification",
        include_actions=False,
    )

    bot_payload = notifier._build_message_payload(
        make_channel({
            "mode": "bot_api",
            "bot_token": "xoxb-test-token",
            "channel_id": "C0123456789",
            "signing_secret": "secret",
            "mention_assignee": True,
        }),
        alert,
        "DiskFull",
        "notification",
        include_actions=False,
    )

    assert webhook_payload["blocks"][2] == bot_payload["blocks"][2]
    assert "<@U012ABCDEF>" in json.dumps(webhook_payload)
    assert "<@U012ABCDEF>" in json.dumps(bot_payload)


# --- Slack direct messages for participant notifications --------------------


def bot_channel(**extra):
    config = {
        "mode": "bot_api",
        "bot_token": "xoxb-test-token",
        "channel_id": "C0123456789",
        "signing_secret": "secret",
    }
    config.update(extra)
    return make_channel(config)


def test_direct_message_opens_conversation_and_posts(monkeypatch):
    notifier = SlackNotifier()
    calls = []

    def fake_request(config, method, payload):
        calls.append((method, payload))

        if method == "conversations.open":
            return {"ok": True, "channel": {"id": "D999"}}

        return {"ok": True, "ts": "1710000000.000001", "channel": "D999"}

    monkeypatch.setattr(notifier, "_request", fake_request)

    result = notifier.send_direct_message(
        bot_channel(),
        make_user(),
        "You were added as a responder",
    )

    assert [method for method, _ in calls] == [
        "conversations.open",
        "chat.postMessage",
    ]
    assert calls[0][1] == {"users": "U012ABCDEF"}
    assert calls[1][1]["channel"] == "D999"
    assert result["delivery_mode"] == "direct_message"
    assert result["external_message_id"] == "1710000000.000001"


def test_direct_message_requires_valid_slack_user_id():
    notifier = SlackNotifier()

    with pytest.raises(RuntimeError) as exc:
        notifier.send_direct_message(
            bot_channel(),
            make_user(slack_user_id="nope"),
            "text",
        )

    assert "Slack user id is missing or invalid" in str(exc.value)


def test_direct_message_fails_when_conversation_not_returned(monkeypatch):
    notifier = SlackNotifier()

    monkeypatch.setattr(
        notifier,
        "_request",
        lambda config, method, payload: {"ok": True, "channel": {}},
    )

    with pytest.raises(RuntimeError) as exc:
        notifier.send_direct_message(bot_channel(), make_user(), "text")

    assert "direct channel id was not returned" in str(exc.value)


def test_webhook_only_channel_falls_back_only_when_opted_in(monkeypatch):
    notifier = SlackNotifier()
    sent = {}

    monkeypatch.setattr(
        "app.notifiers.slack.notifier.safe_request",
        lambda method, url, **kwargs: sent.update(
            {"url": url, **kwargs}
        )
        or SimpleNamespace(raise_for_status=lambda: None),
    )

    result = notifier.send_direct_message(
        make_channel({
            "mode": "webhook",
            "webhook_url": "https://hooks.slack.com/services/T/B/x",
            "allow_dm_channel_fallback": True,
        }),
        make_user(),
        "You were added as a responder",
    )

    assert result["delivery_mode"] == "channel_mention"
    assert sent["json"]["text"] == (
        "<@U012ABCDEF> You were added as a responder"
    )


def test_webhook_only_channel_does_not_fall_back_without_opt_in(monkeypatch):
    """A personal responder/stakeholder note must never be posted to the
    shared channel unless channel fallback is explicitly enabled, because the
    note may contain information intended only for one recipient."""
    notifier = SlackNotifier()
    posted = []

    monkeypatch.setattr(
        "app.notifiers.slack.notifier.safe_request",
        lambda method, url, **kwargs: posted.append({"url": url, **kwargs})
        or SimpleNamespace(raise_for_status=lambda: None),
    )

    with pytest.raises(RuntimeError) as exc:
        notifier.send_direct_message(
            make_channel({
                "mode": "webhook",
                "webhook_url": "https://hooks.slack.com/services/T/B/x",
            }),
            make_user(),
            "private responder note",
        )

    assert "channel fallback" in str(exc.value).lower()
    assert posted == []


def test_direct_message_without_any_transport_raises():
    notifier = SlackNotifier()

    with pytest.raises(RuntimeError) as exc:
        notifier.send_direct_message(
            make_channel({"mode": "webhook"}),
            make_user(),
            "text",
        )

    assert "Bot API mode" in str(exc.value)
