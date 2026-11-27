"""Regression tests for public channel callbacks configured via @username.

Telegram accepts a channel username for sending, but the callback carries
a numeric chat.id. The callback must recognize the channel post and use the
channel template, not the private-message template with its journal.
"""

from types import SimpleNamespace

from app.modules.db import notifications_repo
from app.modules.db.models import AlertGroup
from app.notifiers.telegram import bot as bot_module
from app.notifiers.telegram import poller as poller_module
from app.notifiers.telegram.actions import build_telegram_action_data
from app.settings import Config
from tests.factories import (
    create_channel,
    create_group,
    create_route,
    create_team,
    create_user,
)


CHANNEL_NUMERIC_ID = "-1001234567890"


class FakeTelegramBot:
    def __init__(self):
        self.sent = []
        self.edited_text = []
        self._next_message_id = 3000

    def send_message(self, **kwargs):
        self.sent.append(kwargs)
        self._next_message_id += 1
        return SimpleNamespace(
            message_id=self._next_message_id,
            chat=SimpleNamespace(id=kwargs["chat_id"], username="testchannel"),
        )

    def edit_message_text(self, **kwargs):
        self.edited_text.append(kwargs)

    def answer_callback_query(self, callback_query_id, text, show_alert=False):
        pass


def _world():
    group = create_group()
    team = create_team(group)
    assignee = create_user(group=group, is_admin=True)
    assignee.telegram_user_id = "8080"
    assignee.save()
    route = create_route(team)
    channel = create_channel(
        group,
        team,
        channel_type="telegram",
        config={"bot_token": "123456:USERNAME", "chat_id": "@testchannel"},
    )
    alert = AlertGroup.create(
        team=team,
        route=route,
        assignee=assignee,
        source="pytest",
        group_key_hash="hash-username",
        group_key="key-username",
        title="UsernameChannelAlert",
        message="test",
        severity="critical",
        status="firing",
        priority_slug="p3",
    )
    return SimpleNamespace(
        group=group,
        team=team,
        assignee=assignee,
        route=route,
        channel=channel,
        alert=alert,
    )


def test_channel_username_callback_uses_channel_template_not_dm(db, monkeypatch):
    """Public channel configured via @username. ACK callback uses channel template."""

    monkeypatch.setattr(Config, "TELEGRAM_DM_PRIORITIES", "")
    world = _world()
    bot = FakeTelegramBot()
    monkeypatch.setattr(bot_module, "get_telegram_bot", lambda token: bot)
    monkeypatch.setattr(poller_module, "get_telegram_bot", lambda token: bot)

    notifications_repo.save_notification(
        group_id=world.alert.id,
        channel_id=world.channel.id,
        provider="telegram",
        external_message_id="3001",
        external_channel_id=CHANNEL_NUMERIC_ID,
        event_type="notification",
        provider_payload={
            "chat_id": CHANNEL_NUMERIC_ID,
            "message_id": 3001,
        },
    )

    callback = SimpleNamespace(
        id="cb-username",
        data=build_telegram_action_data("ack", world.alert.id, world.channel.id),
        from_user=SimpleNamespace(id=8080),
        message=SimpleNamespace(
            chat=SimpleNamespace(id=CHANNEL_NUMERIC_ID, type="channel", username="testchannel"),
            message_id=3001,
            reply_markup=None,
        ),
    )

    poller_module.handle_telegram_callback(world.channel, callback)

    world.alert = type(world.alert).get_by_id(world.alert.id)
    assert world.alert.status == "acknowledged"

    assert len(bot.edited_text) == 1

    edited = bot.edited_text[0]
    assert str(edited["chat_id"]) == CHANNEL_NUMERIC_ID
    assert str(edited["message_id"]) == "3001"
    assert "<b>Journal:</b>" not in edited["text"]
    assert "Team:" in edited["text"]


def test_private_chat_callback_uses_dm_template(db, monkeypatch):
    """Private chat callback uses the DM template. This is the control case."""

    monkeypatch.setattr(Config, "TELEGRAM_DM_PRIORITIES", "p1")
    world = _world()
    world.alert.priority_slug = "p1"
    world.alert.save()

    bot = FakeTelegramBot()
    monkeypatch.setattr(bot_module, "get_telegram_bot", lambda token: bot)
    monkeypatch.setattr(poller_module, "get_telegram_bot", lambda token: bot)

    notifications_repo.save_notification(
        group_id=world.alert.id,
        channel_id=world.channel.id,
        provider="telegram",
        external_message_id="3002",
        external_channel_id=CHANNEL_NUMERIC_ID,
        event_type="notification",
        provider_payload={
            "chat_id": CHANNEL_NUMERIC_ID,
            "message_id": 3002,
            "direct": {
                "chat_id": "8080",
                "message_id": 9001,
                "post_url": "https://t.me/c/1234567890/3002",
            },
        },
    )

    callback = SimpleNamespace(
        id="cb-private",
        data=build_telegram_action_data("ack", world.alert.id, world.channel.id),
        from_user=SimpleNamespace(id=8080),
        message=SimpleNamespace(
            chat=SimpleNamespace(id="8080", type="private"),
            message_id=9001,
            reply_markup=SimpleNamespace(
                keyboard=[[SimpleNamespace(text="Open alert in channel", url="https://t.me/c/1234567890/3002")]]
            ),
        ),
    )

    poller_module.handle_telegram_callback(world.channel, callback)

    world.alert = type(world.alert).get_by_id(world.alert.id)
    assert world.alert.status == "acknowledged"

    direct_edits = [item for item in bot.edited_text if str(item["chat_id"]) == "8080"]

    assert len(direct_edits) >= 1
    assert "<b>Journal:</b>" in direct_edits[-1]["text"] or "acknowledged" in direct_edits[-1]["text"].lower()
