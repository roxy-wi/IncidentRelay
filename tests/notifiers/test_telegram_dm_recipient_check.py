"""Regression tests for DM recipient authorization checks.

The direct message recipient must be re-verified before sending or refreshing
alert details. The check covers current assignee, active account, team read
access, and unchanged Telegram binding.
"""

from types import SimpleNamespace

from app.modules.db import notifications_repo
from app.modules.db.models import AlertGroup
from app.notifiers.telegram import bot as bot_module
from app.notifiers.telegram.bot import send_telegram_alert, update_telegram_alert
from app.settings import Config
from tests.factories import (
    create_channel,
    create_group,
    create_route,
    create_team,
    create_user,
)


CHANNEL_CHAT_ID = "-100600"


class FakeTelegramBot:
    def __init__(self):
        self.sent = []
        self.edited_text = []

    def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return SimpleNamespace(
            message_id=1000 + len(self.sent),
            chat=SimpleNamespace(id=kwargs["chat_id"], username=None),
        )

    def edit_message_text(self, **kwargs):
        self.edited_text.append(kwargs)

    def direct_messages(self):
        return [item for item in self.sent if str(item["chat_id"]) != CHANNEL_CHAT_ID]

    def direct_edits(self):
        return [item for item in self.edited_text if str(item["chat_id"]) != CHANNEL_CHAT_ID]

    def channel_edits(self):
        return [item for item in self.edited_text if str(item["chat_id"]) == CHANNEL_CHAT_ID]


def _world(telegram_user_id="5050"):
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
        config={"bot_token": "123456:XYZ", "chat_id": CHANNEL_CHAT_ID},
    )
    alert = AlertGroup.create(
        team=team,
        route=route,
        assignee=assignee,
        source="pytest",
        group_key_hash=f"hash-recipient-{telegram_user_id}",
        group_key=f"key-recipient-{telegram_user_id}",
        title="RecipientCheckAlert",
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


def test_revoked_access_does_not_receive_dm_refresh(db, monkeypatch):
    """Revoke team access after the first DM. The refresh must not reach that chat."""

    monkeypatch.setattr(Config, "TELEGRAM_DM_PRIORITIES", "p1")
    world = _world()
    bot = FakeTelegramBot()
    monkeypatch.setattr(bot_module, "get_telegram_bot", lambda token: bot)

    result = send_telegram_alert(world.channel, world.alert, "firing text")

    direct_messages = bot.direct_messages()
    assert len(direct_messages) == 1
    assert direct_messages[0]["chat_id"] == "5050"
    assert "direct" in result["provider_payload"]

    notifications_repo.save_notification(
        group_id=world.alert.id,
        channel_id=world.channel.id,
        provider="telegram",
        external_message_id="20",
        external_channel_id=CHANNEL_CHAT_ID,
        event_type="notification",
        provider_payload=result["provider_payload"],
    )

    from app.modules.db.models import UserGroup

    membership = UserGroup.get_or_none(
        UserGroup.user == world.assignee,
        UserGroup.group == world.group,
    )
    assert membership is not None
    membership.active = False
    membership.save()

    world.alert.status = "acknowledged"
    world.alert.save()

    delivery = type("Delivery", (), {
        "external_channel_id": CHANNEL_CHAT_ID,
        "external_message_id": "20",
        "provider_payload": result["provider_payload"],
    })()

    update_telegram_alert(
        world.channel,
        world.alert,
        "acknowledged text",
        delivery,
        event_type="acknowledged",
    )

    channel_edits = bot.channel_edits()
    direct_edits = bot.direct_edits()

    assert len(channel_edits) == 1
    assert len(direct_edits) == 0


def test_deactivated_account_does_not_receive_dm_refresh(db, monkeypatch):
    """Deactivate the assignee account after the first DM. No refresh."""

    monkeypatch.setattr(Config, "TELEGRAM_DM_PRIORITIES", "p1")
    world = _world()
    bot = FakeTelegramBot()
    monkeypatch.setattr(bot_module, "get_telegram_bot", lambda token: bot)

    result = send_telegram_alert(world.channel, world.alert, "firing text")

    direct_messages = bot.direct_messages()
    assert len(direct_messages) == 1
    assert "direct" in result["provider_payload"]

    notifications_repo.save_notification(
        group_id=world.alert.id,
        channel_id=world.channel.id,
        provider="telegram",
        external_message_id="21",
        external_channel_id=CHANNEL_CHAT_ID,
        event_type="notification",
        provider_payload=result["provider_payload"],
    )

    world.assignee.active = False
    world.assignee.save()

    world.alert.status = "acknowledged"
    world.alert.save()

    delivery = type("Delivery", (), {
        "external_channel_id": CHANNEL_CHAT_ID,
        "external_message_id": "21",
        "provider_payload": result["provider_payload"],
    })()

    update_telegram_alert(
        world.channel,
        world.alert,
        "acknowledged text",
        delivery,
        event_type="acknowledged",
    )

    channel_edits = bot.channel_edits()
    direct_edits = bot.direct_edits()

    assert len(channel_edits) == 1
    assert len(direct_edits) == 0


def test_changed_telegram_id_does_not_receive_dm_refresh(db, monkeypatch):
    """Change the assignee's Telegram id after the first DM. No refresh."""

    monkeypatch.setattr(Config, "TELEGRAM_DM_PRIORITIES", "p1")
    world = _world()
    bot = FakeTelegramBot()
    monkeypatch.setattr(bot_module, "get_telegram_bot", lambda token: bot)

    result = send_telegram_alert(world.channel, world.alert, "firing text")

    direct_messages = bot.direct_messages()
    assert len(direct_messages) == 1
    assert direct_messages[0]["chat_id"] == "5050"
    assert "direct" in result["provider_payload"]

    notifications_repo.save_notification(
        group_id=world.alert.id,
        channel_id=world.channel.id,
        provider="telegram",
        external_message_id="22",
        external_channel_id=CHANNEL_CHAT_ID,
        event_type="notification",
        provider_payload=result["provider_payload"],
    )

    world.assignee.telegram_user_id = "9999"
    world.assignee.save()

    world.alert.status = "acknowledged"
    world.alert.save()

    delivery = type("Delivery", (), {
        "external_channel_id": CHANNEL_CHAT_ID,
        "external_message_id": "22",
        "provider_payload": result["provider_payload"],
    })()

    update_telegram_alert(
        world.channel,
        world.alert,
        "acknowledged text",
        delivery,
        event_type="acknowledged",
    )

    channel_edits = bot.channel_edits()
    direct_edits = bot.direct_edits()

    assert len(channel_edits) == 1
    assert len(direct_edits) == 0


def test_reassignment_does_not_refresh_former_assignee(db, monkeypatch):
    """Reassign the alert after the first DM. The old assignee receives no refresh."""

    monkeypatch.setattr(Config, "TELEGRAM_DM_PRIORITIES", "p1")
    world = _world()
    bot = FakeTelegramBot()
    monkeypatch.setattr(bot_module, "get_telegram_bot", lambda token: bot)

    result = send_telegram_alert(world.channel, world.alert, "firing text")

    direct_messages = bot.direct_messages()
    assert len(direct_messages) == 1
    assert "direct" in result["provider_payload"]

    notifications_repo.save_notification(
        group_id=world.alert.id,
        channel_id=world.channel.id,
        provider="telegram",
        external_message_id="23",
        external_channel_id=CHANNEL_CHAT_ID,
        event_type="notification",
        provider_payload=result["provider_payload"],
    )

    new_assignee = create_user(group=world.group, is_admin=True)
    new_assignee.telegram_user_id = "6060"
    new_assignee.save()

    world.alert.assignee = new_assignee
    world.alert.status = "acknowledged"
    world.alert.save()

    delivery = type("Delivery", (), {
        "external_channel_id": CHANNEL_CHAT_ID,
        "external_message_id": "23",
        "provider_payload": result["provider_payload"],
    })()

    update_telegram_alert(
        world.channel,
        world.alert,
        "acknowledged text",
        delivery,
        event_type="acknowledged",
    )

    channel_edits = bot.channel_edits()
    direct_edits = bot.direct_edits()

    assert len(channel_edits) == 1
    assert len(direct_edits) == 0


def test_unchanged_authorized_assignee_receives_refresh(db, monkeypatch):
    """The same active assignee receives the refresh. This is the happy path."""

    monkeypatch.setattr(Config, "TELEGRAM_DM_PRIORITIES", "p1")
    world = _world()
    bot = FakeTelegramBot()
    monkeypatch.setattr(bot_module, "get_telegram_bot", lambda token: bot)

    result = send_telegram_alert(world.channel, world.alert, "firing text")

    direct_messages = bot.direct_messages()
    assert len(direct_messages) == 1
    assert "direct" in result["provider_payload"]

    notifications_repo.save_notification(
        group_id=world.alert.id,
        channel_id=world.channel.id,
        provider="telegram",
        external_message_id="24",
        external_channel_id=CHANNEL_CHAT_ID,
        event_type="notification",
        provider_payload=result["provider_payload"],
    )

    world.alert.status = "acknowledged"
    world.alert.save()

    delivery = type("Delivery", (), {
        "external_channel_id": CHANNEL_CHAT_ID,
        "external_message_id": "24",
        "provider_payload": result["provider_payload"],
    })()

    update_telegram_alert(
        world.channel,
        world.alert,
        "acknowledged text",
        delivery,
        event_type="acknowledged",
    )

    channel_edits = bot.channel_edits()
    direct_edits = bot.direct_edits()

    assert len(channel_edits) == 1
    assert len(direct_edits) == 1
    assert "acknowledged" in direct_edits[0]["text"]
