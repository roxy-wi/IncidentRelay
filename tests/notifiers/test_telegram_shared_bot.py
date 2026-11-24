"""One Telegram bot can serve several channels.

getUpdates belongs to the bot, not to a channel. The press has to be handled
by the channel id stored in the button, and the message has to keep its buttons.
"""

from types import SimpleNamespace

import pytest

from app.modules.common import utc_now
from app.modules.db.models import AlertGroup
from app.notifiers.telegram import bot as bot_module
from app.notifiers.telegram import poller
from app.notifiers.telegram.actions import build_telegram_action_data
from app.services.alerts.shelving import is_alert_group_shelved
from app.settings import Config
from tests.factories import create_channel, create_group, create_route, create_team, create_user


SHARED = "123456:SHARED"


class PollBot:
    """getUpdates that keeps an update until a later call confirms its offset."""

    def __init__(self):
        self.updates = []
        self.polls = []
        self.answers = []
        self.edited_text = []

    def get_updates(self, offset=None, timeout=None, allowed_updates=None):
        self.polls.append(
            {"offset": offset, "timeout": timeout, "allowed_updates": allowed_updates}
        )
        pending = self.updates
        if offset is not None:
            pending = [item for item in self.updates if item.update_id >= offset]
        return list(pending)

    def answer_callback_query(self, callback_id, text=None, show_alert=False):
        self.answers.append(text)

    def edit_message_text(self, **kwargs):
        self.edited_text.append(kwargs)


@pytest.fixture(autouse=True)
def reset_poll_state():
    poller._token_offsets.clear()
    poller._channel_auth_failed_until.clear()
    poller._channel_transport_failed_until.clear()
    yield


def _world(telegram_user_id, token, chat_id):
    group = create_group()
    team = create_team(group)
    assignee = create_user(group=group, is_admin=True)
    assignee.telegram_user_id = telegram_user_id
    assignee.save()
    route = create_route(team)
    channel = create_channel(
        group,
        team,
        channel_type="telegram",
        config={
            "bot_token": token,
            "chat_id": str(chat_id),
            "polling_enabled": True,
            "actions_enabled": True,
        },
    )
    now = utc_now()
    alert = AlertGroup.create(
        team=team,
        route=route,
        assignee=assignee,
        source="pytest",
        group_key_hash=f"hash-{telegram_user_id}-{chat_id}",
        group_key=f"key-{telegram_user_id}-{chat_id}",
        title="DiskFull",
        message="/var is 95% full",
        severity="critical",
        status="firing",
        first_seen_at=now,
        last_seen_at=now,
        priority_slug="p1",
    )
    return SimpleNamespace(
        assignee=assignee,
        channel=channel,
        alert=alert,
    )


def _press(world, action, *, update_id):
    chat_id = int(world.channel.config["chat_id"])
    return SimpleNamespace(
        update_id=update_id,
        callback_query=SimpleNamespace(
            id=f"cb-{update_id}",
            data=build_telegram_action_data(action, world.alert.id, world.channel.id),
            from_user=SimpleNamespace(id=int(world.assignee.telegram_user_id)),
            message=SimpleNamespace(
                chat=SimpleNamespace(id=chat_id),
                message_id=20 + update_id,
            ),
        ),
    )


def _install_bots(monkeypatch, *tokens):
    bots = {token: PollBot() for token in tokens}

    def get(token):
        return bots[token]

    monkeypatch.setattr(poller, "get_telegram_bot", get)
    monkeypatch.setattr(bot_module, "get_telegram_bot", get)
    return bots


def _callback_buttons(markup):
    if markup is None:
        return []
    return [
        button.callback_data
        for row in markup.keyboard
        for button in row
        if button.callback_data
    ]


def test_shared_bot_press_reaches_the_channel_named_in_the_button(db, monkeypatch):
    first = _world("4242", SHARED, -100111)
    second = _world("4243", SHARED, -100222)
    bots = _install_bots(monkeypatch, SHARED)
    bots[SHARED].updates.append(_press(second, "ack", update_id=7))

    processed = poller.poll_telegram_channels_once(timeout=20)

    second.alert = type(second.alert).get_by_id(second.alert.id)
    first.alert = type(first.alert).get_by_id(first.alert.id)
    assert processed == 1
    assert second.alert.status == "acknowledged"
    assert first.alert.status == "firing"
    assert len(bots[SHARED].polls) == 1
    assert bots[SHARED].polls[0]["allowed_updates"] == ["callback_query"]
    assert bots[SHARED].answers == [f"Alert #{second.alert.id} acknowledged"]
    edits = [item for item in bots[SHARED].edited_text if int(item["message_id"]) == 27]
    assert edits
    buttons = _callback_buttons(edits[-1]["reply_markup"])
    assert any(":resolve:" in item for item in buttons)
    assert any(":s1h:" in item for item in buttons)
    assert not any(":ack:" in item for item in buttons)

    poller.poll_telegram_channels_once(timeout=20)
    assert bots[SHARED].polls[-1]["offset"] == 8


def test_shelve_on_a_shared_bot_keeps_the_button_keyboard(db, monkeypatch):
    monkeypatch.setattr(Config, "TELEGRAM_SHELVE_DURATIONS", "1h,4h,7d")
    _world("4242", SHARED, -100111)
    second = _world("4243", SHARED, -100222)
    bots = _install_bots(monkeypatch, SHARED)
    bots[SHARED].updates.append(_press(second, "s4h", update_id=8))

    poller.poll_telegram_channels_once(timeout=20)

    second.alert = type(second.alert).get_by_id(second.alert.id)
    assert is_alert_group_shelved(second.alert)
    assert bots[SHARED].answers == [f"Alert #{second.alert.id} shelved for 4 hours"]
    for item in bots[SHARED].edited_text:
        assert item["reply_markup"] is not None
        assert _callback_buttons(item["reply_markup"])


def test_press_for_another_bots_channel_is_still_rejected(db, monkeypatch):
    _world("4242", SHARED, -100111)
    other = _world("4243", "999:OTHER", -100333)
    bots = _install_bots(monkeypatch, SHARED, "999:OTHER")
    bots[SHARED].updates.append(_press(other, "ack", update_id=9))

    poller.poll_telegram_channels_once(timeout=20)

    other.alert = type(other.alert).get_by_id(other.alert.id)
    assert other.alert.status == "firing"
    assert bots[SHARED].answers == ["Action belongs to another channel"]
    assert bots["999:OTHER"].polls
    assert bots[SHARED].edited_text == []


def test_distinct_bot_tokens_are_polled_separately(db, monkeypatch):
    _world("4242", SHARED, -100111)
    _world("4243", "999:OTHER", -100333)
    bots = _install_bots(monkeypatch, SHARED, "999:OTHER")

    poller.poll_telegram_channels_once(timeout=20)

    assert len(bots[SHARED].polls) == 1
    assert len(bots["999:OTHER"].polls) == 1
