from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from requests import exceptions as requests_exceptions

from app.modules.common import utc_now
from app.modules.db import notifications_repo
from app.modules.db.models import AlertGroup
from app.notifiers.telegram import bot as bot_module
from app.notifiers.telegram import direct, poller
from app.notifiers.telegram.actions import build_telegram_action_data
from app.notifiers.telegram.bot import send_telegram_alert
from app.notifiers.telegram.direct_policy import should_send_dm, telegram_chat_id
from app.notifiers.telegram.journal import format_offset, journal_lines
from app.notifiers.telegram.timefmt import format_moment
from app.settings import Config
from tests.factories import (
    create_channel,
    create_group,
    create_route,
    create_team,
    create_user,
)


CHANNEL_CHAT_ID = "-100500"


class FakeTelegramBot:
    def __init__(self):
        self.sent = []
        self.edited_text = []
        self.fail_direct = None
        self._next_message_id = 900

    def send_message(self, **kwargs):
        is_direct = str(kwargs["chat_id"]) != CHANNEL_CHAT_ID

        if is_direct and self.fail_direct:
            raise self.fail_direct

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


def _world(priority_slug="p1", telegram_user_id="4242"):
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
        config={"bot_token": "123456:ABC", "chat_id": CHANNEL_CHAT_ID},
    )
    now = utc_now()
    alert = AlertGroup.create(
        team=team,
        route=route,
        assignee=assignee,
        source="pytest",
        group_key_hash=f"hash-dm-{priority_slug}-{telegram_user_id}-{now.timestamp()}",
        group_key=f"key-dm-{priority_slug}-{telegram_user_id}",
        title="DiskFull",
        message="/var is 95% full",
        severity="critical",
        status="firing",
        first_seen_at=now,
        last_seen_at=now,
        priority_slug=priority_slug,
    )
    return SimpleNamespace(
        assignee=assignee,
        route=route,
        channel=channel,
        alert=alert,
    )


def test_direct_messages_stay_off_until_priorities_are_configured():
    alert = SimpleNamespace(priority_slug="p1", status="firing")
    assert should_send_dm(alert, "notification") is False
    assert should_send_dm(alert, "escalation") is False
    assert telegram_chat_id(SimpleNamespace(telegram_user_id="")) is None
    assert telegram_chat_id(SimpleNamespace(telegram_user_id="@name")) is None
    assert telegram_chat_id(SimpleNamespace(telegram_user_id="4242")) == "4242"


def test_escalation_pages_any_priority_when_direct_messages_are_enabled(monkeypatch):
    monkeypatch.setattr(Config, "TELEGRAM_DM_PRIORITIES", "p1,p2")
    warning = SimpleNamespace(priority_slug="p3")
    low = SimpleNamespace(priority_slug="p4")

    assert should_send_dm(warning, "notification") is False
    assert should_send_dm(low, "escalation") is True
    assert should_send_dm(low, "resolved") is False


def test_utc_keeps_the_historical_timestamp_and_another_zone_converts():
    moment = datetime(2026, 10, 22, 9, 25, tzinfo=timezone.utc)
    assert format_moment(moment) == "22.10.2026 09:25:00 UTC"


def test_configured_zone_drops_seconds(monkeypatch):
    monkeypatch.setattr(Config, "TELEGRAM_TIMEZONE", "Europe/Moscow")
    moment = datetime(2026, 10, 22, 9, 25)
    assert format_moment(moment) == "22.10.2026 12:25 MSK"


def test_unknown_zone_falls_back_to_utc(monkeypatch):
    monkeypatch.setattr(Config, "TELEGRAM_TIMEZONE", "Not/AZone")
    moment = datetime(2026, 10, 22, 9, 25, tzinfo=timezone.utc)
    assert format_moment(moment) == "22.10.2026 09:25:00 UTC"


def test_journal_offset_and_assignment_line(db):
    world = _world()
    start = world.alert.first_seen_at
    assert format_offset(start + timedelta(seconds=5), start) == "5s"
    assert format_offset(start + timedelta(minutes=5), start) == "5m"
    lines = journal_lines(world.alert)
    assert any("alert created" in line for line in lines)
    assert any(world.route.name in line and "on call" in line for line in lines)


def test_matching_priority_sends_a_private_message_with_the_channel_buttons(db, monkeypatch):
    monkeypatch.setattr(Config, "TELEGRAM_DM_PRIORITIES", "p1,p2")
    world = _world()
    bot = FakeTelegramBot()
    monkeypatch.setattr(bot_module, "get_telegram_bot", lambda token: bot)

    result = send_telegram_alert(world.channel, world.alert, "channel text")

    direct_messages = bot.direct_messages()
    assert len(direct_messages) == 1
    assert direct_messages[0]["chat_id"] == "4242"
    assert "assigned to you" in direct_messages[0]["text"]
    assert "<b>Journal:</b>" in direct_messages[0]["text"]
    labels = [
        button.text
        for row in direct_messages[0]["reply_markup"].keyboard
        for button in row
    ]
    assert "Acknowledge" in labels
    assert "Shelve 1h" in labels
    assert "Open alert in channel" in labels
    assert result["provider_payload"]["direct"]["chat_id"] == "4242"
    assert result["provider_payload"]["direct"]["post_url"] == "https://t.me/c/500/901"


def test_direct_message_failure_does_not_fail_the_channel_post(db, monkeypatch):
    monkeypatch.setattr(Config, "TELEGRAM_DM_PRIORITIES", "p1")
    world = _world()
    bot = FakeTelegramBot()
    bot.fail_direct = requests_exceptions.ConnectionError("refused")
    monkeypatch.setattr(bot_module, "get_telegram_bot", lambda token: bot)

    result = send_telegram_alert(world.channel, world.alert, "channel text")

    assert result["external_message_id"]
    assert "direct" not in result["provider_payload"]
    assert len(bot.sent) == 1


def test_ack_from_the_direct_message_updates_the_channel_post(db, monkeypatch):
    world = _world()
    notifications_repo.save_notification(
        group_id=world.alert.id,
        channel_id=world.channel.id,
        provider="telegram",
        external_message_id="10",
        external_channel_id=CHANNEL_CHAT_ID,
        event_type="notification",
        provider_payload={
            "chat_id": CHANNEL_CHAT_ID,
            "message_id": 10,
            "direct": {
                "chat_id": "4242",
                "message_id": 902,
                "post_url": "https://t.me/c/500/10",
            },
        },
    )
    bot = FakeTelegramBot()
    monkeypatch.setattr(bot_module, "get_telegram_bot", lambda token: bot)
    monkeypatch.setattr(poller, "get_telegram_bot", lambda token: bot)
    markup = direct.direct_keyboard(
        world.alert,
        "https://t.me/c/500/10",
        None,
    )
    callback = SimpleNamespace(
        id="cb-dm",
        data=build_telegram_action_data("ack", world.alert.id, world.channel.id),
        from_user=SimpleNamespace(id=4242),
        message=SimpleNamespace(
            chat=SimpleNamespace(id=4242),
            message_id=902,
            reply_markup=markup,
        ),
    )

    poller.handle_telegram_callback(world.channel, callback)

    world.alert = type(world.alert).get_by_id(world.alert.id)
    assert world.alert.status == "acknowledged"
    posts = [item for item in bot.edited_text if str(item["chat_id"]) == CHANNEL_CHAT_ID]
    private = [item for item in bot.edited_text if str(item["chat_id"]) == "4242"]
    assert posts
    assert private
    assert "acknowledged" in private[-1]["text"]
    assert "Team:" not in private[-1]["text"]
