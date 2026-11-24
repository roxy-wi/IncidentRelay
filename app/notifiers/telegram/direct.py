"""Direct message to the assignee.

The private message names the alert, repeats the channel keyboard, and links
back to the channel post. Sending is best effort: a user who never pressed
Start in the bot must not break the channel delivery.
"""

import logging
from html import escape

from requests import exceptions as requests_exceptions
from telebot import types
from telebot.apihelper import ApiTelegramException

from app.notifiers.telegram.journal import journal_lines
from app.services.alerts.priority import format_alert_title_with_priority
from app.services.alerts.shelving import is_alert_group_shelved
from app.services.links import build_alert_web_url


logger = logging.getLogger("oncall.telegram")

DIRECT_PAYLOAD_KEY = "direct"
POST_BUTTON_TEXT = "Open alert in channel"

_TITLE_LIMIT = 180


def direct_text(alert, event_type, shelved=False, journal=()):
    """Return the HTML text of the direct message for the alert state."""

    alert_id = getattr(alert, "id", None)
    title = escape(_short(format_alert_title_with_priority(alert)))
    status = str(getattr(alert, "status", "") or "").lower()

    if status == "resolved":
        icon, line = "🟢", f"Alert #{alert_id} resolved."
    elif status == "acknowledged":
        who = _person(getattr(alert, "acknowledged_by", None))
        icon, line = "👀", f"Alert #{alert_id} acknowledged: {who}."
    elif shelved:
        icon, line = "🔕", f"Alert #{alert_id} shelved."
    elif event_type == "reminder":
        icon, line = "⏰", f"Alert #{alert_id} is still unacknowledged."
    elif event_type == "escalation":
        icon, line = "🔔", f"Alert #{alert_id} was handed to you."
    else:
        icon, line = "🔔", f"Alert #{alert_id} assigned to you."

    text = f"{icon} <b>{title}</b>\n{line}"

    if journal:
        text += "\n\n<b>Journal:</b>\n<pre>" + "\n".join(journal) + "</pre>"

    return text


def channel_post_url(message):
    """Return the t.me link of a channel post, or None for a private chat."""

    chat = message.chat
    message_id = int(message.message_id)
    username = getattr(chat, "username", None)

    if username:
        return f"https://t.me/{username}/{message_id}"

    raw = str(chat.id)

    if not raw.startswith("-100"):
        return None

    return f"https://t.me/c/{raw[4:]}/{message_id}"


def direct_keyboard(alert, post_url, actions=None):
    """Action buttons, then the link to the channel post, then the web link.

    ``actions`` is the channel keyboard, so Acknowledge, Resolve and Shelve
    do the same thing in both places.
    """

    keyboard = types.InlineKeyboardMarkup(row_width=3)
    rows = list(actions.keyboard) if actions else []
    action_rows = [row for row in rows if any(button.callback_data for button in row)]
    link_rows = [row for row in rows if row not in action_rows]

    for row in action_rows:
        keyboard.row(*row)

    if post_url:
        keyboard.row(types.InlineKeyboardButton(POST_BUTTON_TEXT, url=post_url))

    for row in link_rows:
        keyboard.row(*row)

    if not link_rows and actions is None:
        alert_url = build_alert_web_url(alert)

        if alert_url:
            keyboard.row(types.InlineKeyboardButton("Open alert", url=alert_url))

    return keyboard if keyboard.keyboard else None


def send_direct(bot, chat_id, alert, event_type, post_url, actions=None):
    """Write to the assignee. Returns the stored message data, or None."""

    try:
        sent = bot.send_message(
            chat_id=chat_id,
            text=_text(alert, event_type),
            parse_mode="HTML",
            reply_markup=direct_keyboard(alert, post_url, actions),
            disable_web_page_preview=True,
        )
    except (ApiTelegramException, requests_exceptions.RequestException) as exc:
        logger.warning(
            "telegram direct message was not sent",
            extra={
                "extra": {
                    "event_type": "telegram_direct_failed",
                    "alert_group_id": getattr(alert, "id", None),
                    "telegram_error": getattr(exc, "description", None)
                    or exc.__class__.__name__,
                }
            },
        )
        return None

    return {
        "chat_id": str(chat_id),
        "message_id": int(sent.message_id),
        "post_url": post_url,
    }


def refresh_direct(bot, alert, stored, actions=None):
    """Rewrite the direct message for the current alert state.

    Returns False when Telegram reports that nothing changed.
    """

    try:
        bot.edit_message_text(
            chat_id=stored["chat_id"],
            message_id=int(stored["message_id"]),
            text=_text(alert, "refresh"),
            parse_mode="HTML",
            reply_markup=direct_keyboard(alert, stored.get("post_url"), actions),
            disable_web_page_preview=True,
        )
    except ApiTelegramException as exc:
        if "message is not modified" in str(exc).lower():
            return False

        raise

    return True


def post_url_from_message(message):
    """Read the channel post link back from the buttons of a direct message."""

    markup = getattr(message, "reply_markup", None)

    for row in getattr(markup, "keyboard", None) or []:
        for button in row:
            if getattr(button, "text", None) == POST_BUTTON_TEXT:
                return getattr(button, "url", None)

    return None


def _text(alert, event_type):
    return direct_text(
        alert,
        event_type,
        shelved=is_alert_group_shelved(alert),
        journal=_journal(alert, event_type),
    )


def _journal(alert, event_type):
    """The log is a nicety: a failure here must not stop the page."""

    try:
        return journal_lines(alert, event_type)
    except Exception:
        logger.warning("telegram direct journal was not built", exc_info=True)
        return []


def _person(user):
    if not user:
        return "-"

    return escape(
        str(
            getattr(user, "display_name", None)
            or getattr(user, "username", None)
            or "-"
        )
    )


def _short(value, limit=_TITLE_LIMIT):
    text = str(value or "").strip()

    if len(text) <= limit:
        return text

    return text[: limit - 1] + "…"
