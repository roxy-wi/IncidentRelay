from types import SimpleNamespace

from app.notifiers.mattermost.notifier import MattermostNotifier
from app.notifiers.slack.notifier import SlackNotifier
from app.notifiers.telegram.actions import (
    build_telegram_action_data,
    parse_telegram_action_data,
)
from app.notifiers.telegram.bot import build_alert_keyboard


def _button_texts_from_telegram(keyboard):
    return [button.text for row in keyboard.keyboard for button in row]


def test_telegram_shelve_callback_round_trip():
    value = build_telegram_action_data("s1h", 41, 7)
    assert parse_telegram_action_data(value) == {
        "action": "shelve",
        "alert_id": 41,
        "channel_id": 7,
        "duration_seconds": 3600,
    }

    value = build_telegram_action_data("uns", 41, 7)
    assert parse_telegram_action_data(value) == {
        "action": "unshelve",
        "alert_id": 41,
        "channel_id": 7,
    }


def test_telegram_keyboard_switches_shelve_to_unshelve(monkeypatch):
    from app.notifiers.telegram import bot as telegram_bot

    channel = SimpleNamespace(id=7, config={"actions_enabled": True})
    alert = SimpleNamespace(id=41, status="firing")

    monkeypatch.setattr(telegram_bot, "build_alert_web_url", lambda _alert: None)
    monkeypatch.setattr(telegram_bot, "is_alert_group_shelved", lambda _alert: False)
    keyboard = build_alert_keyboard(channel, alert)
    assert _button_texts_from_telegram(keyboard) == [
        "Acknowledge",
        "Resolve",
        "Shelve 1h",
    ]

    monkeypatch.setattr(telegram_bot, "is_alert_group_shelved", lambda _alert: True)
    keyboard = build_alert_keyboard(channel, alert)
    assert _button_texts_from_telegram(keyboard) == ["Unshelve", "Resolve"]


def test_slack_actions_switch_shelve_to_unshelve(monkeypatch):
    from app.notifiers.slack import notifier as slack_notifier

    notifier = SlackNotifier()
    channel = SimpleNamespace(id=7)
    alert = SimpleNamespace(id=41, status="firing")

    monkeypatch.setattr(slack_notifier, "is_alert_group_shelved", lambda _alert: False)
    block = notifier._actions(channel, alert)
    assert [item["action_id"] for item in block["elements"]] == [
        "incidentrelay_acknowledge",
        "incidentrelay_shelve",
        "incidentrelay_resolve",
    ]

    monkeypatch.setattr(slack_notifier, "is_alert_group_shelved", lambda _alert: True)
    block = notifier._actions(channel, alert)
    assert [item["action_id"] for item in block["elements"]] == [
        "incidentrelay_unshelve",
        "incidentrelay_resolve",
    ]


def test_mattermost_actions_switch_shelve_to_unshelve(monkeypatch):
    from app.notifiers.mattermost import notifier as mattermost_notifier

    notifier = MattermostNotifier()
    channel = SimpleNamespace(id=7, config={"callback_secret": "test-secret"})
    alert = SimpleNamespace(id=41, status="firing")

    monkeypatch.setattr(
        mattermost_notifier,
        "is_alert_group_shelved",
        lambda _alert: False,
    )
    actions = notifier._actions(channel, alert)
    assert [item["name"] for item in actions] == [
        "Acknowledge",
        "Shelve 1h",
        "Resolve",
    ]

    monkeypatch.setattr(
        mattermost_notifier,
        "is_alert_group_shelved",
        lambda _alert: True,
    )
    actions = notifier._actions(channel, alert)
    assert [item["name"] for item in actions] == ["Unshelve", "Resolve"]
