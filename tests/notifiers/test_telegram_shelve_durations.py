from types import SimpleNamespace

from app.notifiers.telegram.actions import (
    build_telegram_action_data,
    parse_shelve_duration_list,
    parse_telegram_action_data,
    shelve_duration_label,
)
from app.notifiers.telegram.bot import build_alert_keyboard
from app.settings import Config


def _button_texts(keyboard):
    return [button.text for row in keyboard.keyboard for button in row]


def test_unknown_shelve_tokens_fall_back_to_one_hour():
    assert [item["token"] for item in parse_shelve_duration_list("")] == ["1h"]
    assert [item["token"] for item in parse_shelve_duration_list("nope")] == ["1h"]
    assert [item["token"] for item in parse_shelve_duration_list("4h, nope, 4h, 7d")] == [
        "4h",
        "7d",
    ]


def test_extra_shelve_callbacks_round_trip():
    four_hours = parse_telegram_action_data(build_telegram_action_data("s4h", 41, 7))
    assert four_hours["action"] == "shelve"
    assert four_hours["duration_seconds"] == 4 * 3600
    assert shelve_duration_label(four_hours["duration_seconds"]) == "4 hours"

    seven_days = parse_telegram_action_data(build_telegram_action_data("s7d", 41, 7))
    assert seven_days["duration_seconds"] == 7 * 24 * 3600
    assert shelve_duration_label(seven_days["duration_seconds"]) == "7 days"


def test_configured_shelve_buttons_share_one_row(monkeypatch):
    from app.notifiers.telegram import bot as telegram_bot

    monkeypatch.setattr(Config, "TELEGRAM_SHELVE_DURATIONS", "1h,4h,7d")
    monkeypatch.setattr(telegram_bot, "build_alert_web_url", lambda _alert: None)
    monkeypatch.setattr(telegram_bot, "is_alert_group_shelved", lambda _alert: False)

    channel = SimpleNamespace(id=7, config={"actions_enabled": True})
    firing = SimpleNamespace(id=41, status="firing")
    keyboard = build_alert_keyboard(channel, firing)

    assert _button_texts(keyboard) == [
        "Acknowledge",
        "Resolve",
        "Shelve 1h",
        "Shelve 4h",
        "Shelve 7d",
    ]
    assert [button.text for button in keyboard.keyboard[-1]] == [
        "Shelve 1h",
        "Shelve 4h",
        "Shelve 7d",
    ]

    acknowledged = SimpleNamespace(id=41, status="acknowledged")
    keyboard = build_alert_keyboard(channel, acknowledged)
    assert _button_texts(keyboard) == [
        "Resolve",
        "Shelve 1h",
        "Shelve 4h",
        "Shelve 7d",
    ]
