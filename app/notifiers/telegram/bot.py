import logging

import telebot
from telebot import apihelper, types
from requests import exceptions as requests_exceptions
from telebot.apihelper import ApiTelegramException

from app.settings import Config
from app.notifiers.telegram.actions import (
    build_telegram_action_data,
    configured_shelve_durations,
)
from app.notifiers.telegram.direct import (
    DIRECT_PAYLOAD_KEY,
    channel_post_url,
    refresh_direct,
    send_direct,
)
from app.notifiers.telegram.direct_policy import should_send_dm, telegram_chat_id
from app.services.links import build_alert_web_url
from app.services.alerts.shelving import is_alert_group_shelved


logger = logging.getLogger("oncall.telegram")

_bots = {}
_proxy_configured = False


def ensure_polling_mode(bot):
    """Disable Telegram webhook before using getUpdates polling."""

    try:
        bot.remove_webhook()
    except requests_exceptions.RequestException as exc:
        logger.warning(
            "failed to remove telegram webhook before polling due to transport error",
            extra={
                "extra": {
                    "event_type": "telegram_remove_webhook_transport_error",
                    "error_type": exc.__class__.__name__,
                }
            },
        )
    except Exception:
        logger.exception("failed to remove telegram webhook before polling")


def configure_telegram_proxy():
    """
    Configure one global Telegram proxy for all bots.
    """
    global _proxy_configured

    if _proxy_configured:
        return

    proxy_url = getattr(Config, "TELEGRAM_PROXY_URL", "") or ""

    if proxy_url:
        apihelper.proxy = {
            "http": proxy_url,
            "https": proxy_url,
        }
    else:
        apihelper.proxy = None

    _proxy_configured = True


def get_telegram_bot(bot_token):
    """
    Return cached TeleBot instance.
    """
    configure_telegram_proxy()

    if not bot_token:
        raise RuntimeError("telegram bot_token is missing")

    if not is_valid_telegram_bot_token(bot_token):
        raise RuntimeError("telegram bot_token is invalid")

    bot = _bots.get(bot_token)

    if bot:
        return bot

    bot = telebot.TeleBot(bot_token, parse_mode=None, threaded=False)
    ensure_polling_mode(bot)
    _bots[bot_token] = bot

    return bot


def _shelve_buttons(alert, channel):
    """Inline buttons for the configured shelve durations."""

    return [
        types.InlineKeyboardButton(
            spec["button"],
            callback_data=build_telegram_action_data(
                spec["code"], alert.id, channel.id
            ),
        )
        for spec in configured_shelve_durations()
    ]


def _resolve_button(alert, channel):
    return types.InlineKeyboardButton(
        "Resolve",
        callback_data=build_telegram_action_data("resolve", alert.id, channel.id),
    )


def build_alert_keyboard(channel, alert):
    """
    Build Telegram inline keyboard for alert actions.
    """
    config = channel.config or {}
    actions_enabled = config.get("actions_enabled", True)
    alert_url = build_alert_web_url(alert)

    keyboard = types.InlineKeyboardMarkup(row_width=2)
    has_buttons = False

    if actions_enabled and alert.status in {"firing", "acknowledged"}:
        shelved = is_alert_group_shelved(alert)
        if shelved:
            keyboard.add(
                types.InlineKeyboardButton(
                    "Unshelve",
                    callback_data=build_telegram_action_data(
                        "uns", alert.id, channel.id
                    ),
                ),
                types.InlineKeyboardButton(
                    "Resolve",
                    callback_data=build_telegram_action_data(
                        "resolve", alert.id, channel.id
                    ),
                ),
            )
            has_buttons = True
        elif alert.status == "acknowledged":
            shelve_buttons = _shelve_buttons(alert, channel)

            if len(shelve_buttons) == 1:
                keyboard.row(shelve_buttons[0], _resolve_button(alert, channel))
            else:
                keyboard.row(_resolve_button(alert, channel))
                keyboard.row(*shelve_buttons)

            has_buttons = True
        else:
            keyboard.add(
                types.InlineKeyboardButton(
                    "Acknowledge",
                    callback_data=build_telegram_action_data(
                        "ack", alert.id, channel.id
                    ),
                ),
                _resolve_button(alert, channel),
            )
            keyboard.row(*_shelve_buttons(alert, channel))
            has_buttons = True

    if alert_url:
        keyboard.add(
            types.InlineKeyboardButton(
                "Open alert",
                url=alert_url,
            )
        )
        has_buttons = True

    if not has_buttons:
        return None

    return keyboard


def send_telegram_alert(channel, alert, text, event_type="notification"):
    """
    Send alert through Telegram Bot API.
    """
    config = channel.config or {}

    bot_token = config.get("bot_token")
    chat_id = config.get("chat_id")

    if not bot_token or not chat_id:
        raise RuntimeError("telegram bot_token or chat_id is missing")

    bot = get_telegram_bot(bot_token)

    message = bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=build_alert_keyboard(channel, alert),
        disable_web_page_preview=True,
        parse_mode="HTML",
    )

    provider_payload = {
        "chat_id": message.chat.id,
        "message_id": message.message_id,
        "event_type": event_type,
    }

    direct = _notify_assignee(bot, channel, alert, event_type, message)

    if direct:
        provider_payload[DIRECT_PAYLOAD_KEY] = direct

    return {
        "provider": "telegram",
        "external_message_id": str(message.message_id),
        "external_channel_id": str(message.chat.id),
        "provider_payload": provider_payload,
    }


def _notify_assignee(bot, channel, alert, event_type, post):
    """Page the assignee in a private chat. Never fails the channel delivery."""

    try:
        if getattr(alert, "status", None) != "firing":
            return None

        if not should_send_dm(alert, event_type):
            return None

        chat_id = telegram_chat_id(getattr(alert, "assignee", None))

        if chat_id is None:
            return None

        return send_direct(
            bot,
            chat_id,
            alert,
            event_type,
            channel_post_url(post),
            build_alert_keyboard(channel, alert),
        )
    except Exception:
        logger.exception(
            "telegram direct message failed",
            extra={
                "extra": {
                    "event_type": "telegram_direct_error",
                    "alert_group_id": getattr(alert, "id", None),
                }
            },
        )
        return None


def update_telegram_alert(channel, alert, text, delivery, event_type="resolved"):
    """
    Update previously sent Telegram alert message.
    """
    config = channel.config or {}

    bot_token = config.get("bot_token")
    chat_id = delivery.external_channel_id or config.get("chat_id")
    message_id = delivery.external_message_id

    if not bot_token or not chat_id or not message_id:
        raise RuntimeError("telegram bot_token, chat_id or message_id is missing")

    previous = dict(getattr(delivery, "provider_payload", None) or {})
    keyboard = build_alert_keyboard(channel, alert)
    reply_markup = None if alert.status == "resolved" else keyboard

    bot = get_telegram_bot(bot_token)
    post_changed = True

    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except ApiTelegramException as exc:
        if "message is not modified" not in str(exc).lower():
            raise

        post_changed = False

    _refresh_direct_message(bot, alert, previous, keyboard)

    if not post_changed:
        return False

    return {
        "provider": "telegram",
        "external_message_id": str(message_id),
        "external_channel_id": str(chat_id),
        "provider_payload": {
            **previous,
            "chat_id": chat_id,
            "message_id": message_id,
            "event_type": event_type,
            "updated": True,
        },
    }


def _refresh_direct_message(bot, alert, payload, keyboard):
    """Keep the stored direct message in step with the alert state."""

    stored = payload.get(DIRECT_PAYLOAD_KEY)

    if not stored:
        return

    try:
        refresh_direct(bot, alert, stored, keyboard)
    except Exception as exc:
        logger.warning(
            "telegram direct message was not refreshed",
            extra={
                "extra": {
                    "event_type": "telegram_direct_refresh_failed",
                    "alert_group_id": getattr(alert, "id", None),
                    "telegram_error": getattr(exc, "description", None)
                    or exc.__class__.__name__,
                }
            },
        )


def answer_telegram_callback(channel, callback_query_id, text, show_alert=False):
    """
    Answer Telegram callback query.
    """
    config = channel.config or {}
    bot = get_telegram_bot(config.get("bot_token"))

    bot.answer_callback_query(
        callback_query_id,
        text=text,
        show_alert=show_alert,
    )


def is_valid_telegram_bot_token(bot_token):
    return bool(bot_token and ":" in str(bot_token))
