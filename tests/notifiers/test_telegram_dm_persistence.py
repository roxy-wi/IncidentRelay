"""Regression tests for DM reference persistence across alert updates.

A firing alert can go through notification → update → resolved. The first send
records the DM. The update sends a new channel post but must preserve the DM
reference so that Resolve can edit both the latest channel post and the
original private message.
"""

from types import SimpleNamespace

from app.modules.db import notifications_repo
from app.modules.db.models import AlertGroup
from app.notifiers.telegram import bot as bot_module
from app.notifiers.telegram.bot import send_telegram_alert, update_telegram_alert
from app.notifiers.telegram.direct import DIRECT_PAYLOAD_KEY
from app.settings import Config
from tests.factories import (
    create_channel,
    create_group,
    create_route,
    create_team,
    create_user,
)


CHANNEL_CHAT_ID = "-100700"


class FakeTelegramBot:
    def __init__(self):
        self.sent = []
        self.edited_text = []
        self._next_message_id = 2000

    def send_message(self, **kwargs):
        self.sent.append(kwargs)
        self._next_message_id += 1
        return SimpleNamespace(
            message_id=self._next_message_id,
            chat=SimpleNamespace(id=kwargs["chat_id"], username=None),
        )

    def edit_message_text(self, **kwargs):
        self.edited_text.append(kwargs)

    def direct_messages(self):
        return [item for item in self.sent if str(item["chat_id"]) != CHANNEL_CHAT_ID]

    def direct_edits(self):
        return [item for item in self.edited_text if str(item["chat_id"]) != CHANNEL_CHAT_ID]

    def channel_posts(self):
        return [item for item in self.sent if str(item["chat_id"]) == CHANNEL_CHAT_ID]

    def channel_edits(self):
        return [item for item in self.edited_text if str(item["chat_id"]) == CHANNEL_CHAT_ID]


def _world():
    group = create_group()
    team = create_team(group)
    assignee = create_user(group=group, is_admin=True)
    assignee.telegram_user_id = "7070"
    assignee.save()
    route = create_route(team)
    channel = create_channel(
        group,
        team,
        channel_type="telegram",
        config={"bot_token": "123456:PERSIST", "chat_id": CHANNEL_CHAT_ID},
    )
    alert = AlertGroup.create(
        team=team,
        route=route,
        assignee=assignee,
        source="pytest",
        group_key_hash="hash-persist",
        group_key="key-persist",
        title="PersistenceAlert",
        message="test",
        severity="critical",
        status="firing",
        priority_slug="p1",
    )
    return SimpleNamespace(
        group=group,
        team=team,
        assignee=assignee,
        route=route,
        channel=channel,
        alert=alert,
    )


def test_update_does_not_send_second_dm_and_preserves_reference(db, monkeypatch):
    """notification → update → resolved. No second DM. Resolve edits both messages."""

    monkeypatch.setattr(Config, "TELEGRAM_DM_PRIORITIES", "p1")
    world = _world()
    bot = FakeTelegramBot()
    monkeypatch.setattr(bot_module, "get_telegram_bot", lambda token: bot)

    notification_result = send_telegram_alert(world.channel, world.alert, "firing text")

    direct_messages = bot.direct_messages()
    channel_posts = bot.channel_posts()

    assert len(channel_posts) == 1
    assert len(direct_messages) == 1
    assert DIRECT_PAYLOAD_KEY in notification_result["provider_payload"]

    first_dm_chat_id = notification_result["provider_payload"][DIRECT_PAYLOAD_KEY]["chat_id"]
    first_dm_message_id = notification_result["provider_payload"][DIRECT_PAYLOAD_KEY]["message_id"]

    assert first_dm_chat_id == "7070"

    notifications_repo.save_notification(
        group_id=world.alert.id,
        channel_id=world.channel.id,
        provider="telegram",
        external_message_id=channel_posts[0]["chat_id"],
        external_channel_id=str(channel_posts[0]["chat_id"]),
        event_type="notification",
        provider_payload=notification_result["provider_payload"],
    )

    world.alert.message = "updated message"
    world.alert.save()

    delivery = type("Delivery", (), {
        "external_channel_id": CHANNEL_CHAT_ID,
        "external_message_id": str(channel_posts[0]["chat_id"]),
        "provider_payload": notification_result["provider_payload"],
    })()

    update_result = update_telegram_alert(
        world.channel,
        world.alert,
        "updated text",
        delivery,
        event_type="notification",
    )

    assert len(bot.direct_messages()) == 1
    assert len(bot.channel_posts()) == 1

    assert DIRECT_PAYLOAD_KEY in update_result["provider_payload"]
    assert update_result["provider_payload"][DIRECT_PAYLOAD_KEY]["chat_id"] == first_dm_chat_id
    assert update_result["provider_payload"][DIRECT_PAYLOAD_KEY]["message_id"] == first_dm_message_id

    notifications_repo.save_notification(
        group_id=world.alert.id,
        channel_id=world.channel.id,
        provider="telegram",
        external_message_id=CHANNEL_CHAT_ID,
        external_channel_id=CHANNEL_CHAT_ID,
        event_type="notification",
        provider_payload=update_result["provider_payload"],
    )

    world.alert.status = "resolved"
    world.alert.save()

    delivery = type("Delivery", (), {
        "external_channel_id": CHANNEL_CHAT_ID,
        "external_message_id": CHANNEL_CHAT_ID,
        "provider_payload": update_result["provider_payload"],
    })()

    update_telegram_alert(
        world.channel,
        world.alert,
        "resolved text",
        delivery,
        event_type="resolved",
    )

    channel_edits = bot.channel_edits()
    direct_edits = bot.direct_edits()

    assert len(channel_edits) >= 1
    assert len(direct_edits) >= 1

    assert str(direct_edits[-1]["chat_id"]) == first_dm_chat_id
    assert direct_edits[-1]["message_id"] == first_dm_message_id
    assert "resolved" in direct_edits[-1]["text"].lower()
