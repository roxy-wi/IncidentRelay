import re
import logging
from datetime import timedelta

from urllib.parse import urlsplit
from telebot.apihelper import ApiTelegramException
from requests import exceptions as requests_exceptions

from app.settings import Config
from app.db import database_proxy as db
from app.modules.db import alerts_repo, channels_repo, users_repo
from app.services.alerts.actions import acknowledge_alert, resolve_alert
from app.services.rbac import can_respond_team
from app.notifiers.telegram.templates import format_telegram_alert_message
from app.notifiers.telegram.actions import parse_telegram_action_data
from app.notifiers.telegram.bot import (
    answer_telegram_callback,
    get_telegram_bot,
    update_telegram_alert,
)
from app.modules.common import utc_now


logger = logging.getLogger("oncall.telegram")

_channel_offsets = {}
_channel_auth_failed_until = {}
_channel_transport_failed_until = {}

TELEGRAM_AUTH_RETRY_SECONDS = 300
TELEGRAM_TRANSPORT_RETRY_SECONDS = 60
_TOKEN_IN_URL_RE = re.compile(r"/bot[^/\s]+")
_PROXY_AUTH_RE = re.compile(r"://([^:@/\s]+):([^@/\s]+)@")


def _sanitize_error_message(message):
    """Return safe error text without Telegram bot token or proxy credentials."""
    message = str(message or "")
    message = _TOKEN_IN_URL_RE.sub("/bot***REDACTED***", message)
    message = _PROXY_AUTH_RE.sub("://***:***@", message)
    return message[:500]


def _safe_proxy_label():
    """Return proxy endpoint without credentials."""
    proxy_url = (getattr(Config, "TELEGRAM_PROXY_URL", "") or "").strip()

    if not proxy_url:
        return None

    parsed = urlsplit(proxy_url)

    if not parsed.scheme or not parsed.hostname:
        return "configured"

    port = f":{parsed.port}" if parsed.port else ""

    return f"{parsed.scheme}://{parsed.hostname}{port}"


def _friendly_transport_error(exc):
    """Convert transport exception into a short human-readable reason."""
    message = str(exc).lower()

    if "connection refused" in message and "socks" in message:
        return "telegram proxy refused connection"

    if "connection refused" in message:
        return "connection refused"

    if "timed out" in message or "timeout" in message:
        return "connection timed out"

    if "proxy" in message:
        return "telegram proxy connection failed"

    if "name or service not known" in message or "temporary failure in name resolution" in message:
        return "dns resolution failed"

    return exc.__class__.__name__


def _is_channel_transport_backoff_active(channel_id):
    retry_at = _channel_transport_failed_until.get(channel_id)
    return bool(retry_at and retry_at > utc_now())


def _mark_channel_transport_failed(channel_id):
    _channel_transport_failed_until[channel_id] = (
        utc_now() + timedelta(seconds=TELEGRAM_TRANSPORT_RETRY_SECONDS)
    )


def _telegram_exception_error_code(exc):
    return getattr(exc, "error_code", None) or (
        getattr(exc, "result_json", {}) or {}
    ).get("error_code")


def _is_telegram_unauthorized(exc):
    return _telegram_exception_error_code(exc) == 401


def _is_channel_auth_backoff_active(channel_id):
    retry_at = _channel_auth_failed_until.get(channel_id)
    return bool(retry_at and retry_at > utc_now())


def _mark_channel_auth_failed(channel_id):
    _channel_auth_failed_until[channel_id] = (
        utc_now() + timedelta(seconds=TELEGRAM_AUTH_RETRY_SECONDS)
    )


def list_polling_telegram_channels():
    """
    Return enabled Telegram channels with action polling enabled.
    """
    channels = channels_repo.list_channels(enabled_only=True)

    return [
        channel
        for channel in channels
        if channel.channel_type == "telegram"
        and (channel.config or {}).get("polling_enabled", True)
        and (channel.config or {}).get("actions_enabled", True)
        and (channel.config or {}).get("bot_token")
    ]


def poll_telegram_channels_once(timeout=20):
    """Poll all Telegram channels once."""
    processed = 0

    for channel in list_polling_telegram_channels():
        if _is_channel_auth_backoff_active(channel.id):
            continue

        if _is_channel_transport_backoff_active(channel.id):
            continue

        try:
            processed += poll_telegram_channel_once(channel, timeout=timeout)

        except ApiTelegramException as exc:
            if _is_telegram_unauthorized(exc):
                _mark_channel_auth_failed(channel.id)

                logger.error(
                    "telegram channel token is unauthorized; polling temporarily suspended",
                    extra={
                        "extra": {
                            "event_type": "telegram_poll_auth_error",
                            "channel_id": channel.id,
                            "channel_name": getattr(channel, "name", None),
                            "retry_after_seconds": TELEGRAM_AUTH_RETRY_SECONDS,
                            "telegram_error_code": _telegram_exception_error_code(exc),
                            "telegram_error": getattr(exc, "description", str(exc)),
                        }
                    },
                )
                continue

            logger.warning(
                "telegram api error while polling channel",
                extra={
                    "extra": {
                        "event_type": "telegram_poll_api_error",
                        "channel_id": channel.id,
                        "channel_name": getattr(channel, "name", None),
                        "telegram_error_code": _telegram_exception_error_code(exc),
                        "telegram_error": _sanitize_error_message(
                            getattr(exc, "description", str(exc))
                        ),
                    }
                },
            )
            continue

        except requests_exceptions.RequestException as exc:
            _mark_channel_transport_failed(channel.id)

            logger.warning(
                "telegram channel poll transport error; polling temporarily suspended",
                extra={
                    "extra": {
                        "event_type": "telegram_poll_transport_error",
                        "channel_id": channel.id,
                        "channel_name": getattr(channel, "name", None),
                        "reason": _friendly_transport_error(exc),
                        "retry_after_seconds": TELEGRAM_TRANSPORT_RETRY_SECONDS,
                        "proxy": _safe_proxy_label(),
                        "error_type": exc.__class__.__name__,
                        "error": _sanitize_error_message(exc),
                    }
                },
            )
            continue

        except Exception as exc:
            logger.exception(
                "telegram channel poll failed",
                extra={
                    "extra": {
                        "event_type": "telegram_poll_unexpected_error",
                        "channel_id": channel.id,
                        "channel_name": getattr(channel, "name", None),
                        "error": str(exc),
                    }
                },
            )

    return processed


def poll_telegram_channel_once(channel, timeout=20):
    """
    Poll one Telegram channel with getUpdates.
    """
    config = channel.config or {}
    bot = get_telegram_bot(config.get("bot_token"))
    offset = _channel_offsets.get(channel.id)

    updates = bot.get_updates(
        offset=offset,
        timeout=timeout,
        allowed_updates=["callback_query"],
    )

    processed = 0

    for update in updates:
        _channel_offsets[channel.id] = update.update_id + 1

        if not update.callback_query:
            continue

        handle_telegram_callback(channel, update.callback_query)
        processed += 1

    return processed


def handle_telegram_callback(channel, callback):
    """
    Handle Telegram ACK/Resolve callback.
    """
    if db.is_closed():
        db.connect(reuse_if_open=True)

    try:
        action_data = parse_telegram_action_data(callback.data)

        if not action_data:
            answer_telegram_callback(
                channel,
                callback.id,
                "Invalid action",
                show_alert=True,
            )
            return

        if int(action_data["channel_id"]) != int(channel.id):
            answer_telegram_callback(
                channel,
                callback.id,
                "Action belongs to another channel",
                show_alert=True,
            )
            return

        telegram_user_id = str(callback.from_user.id)
        user = users_repo.get_user_by_telegram_id(telegram_user_id)

        if not user:
            answer_telegram_callback(
                channel,
                callback.id,
                "Telegram user is not linked to IncidentRelay",
                show_alert=True,
            )
            return

        alert_id = int(action_data["alert_id"])
        action = action_data["action"]
        alert_group = alerts_repo.get_alert_group(alert_id)

        if (
            not alert_group.team_id
            or not getattr(channel, "team_id", None)
            or int(channel.team_id) != int(alert_group.team_id)
            or not can_respond_team(user, alert_group.team_id)
        ):
            answer_telegram_callback(
                channel,
                callback.id,
                "You are not authorized to act on this alert",
                show_alert=True,
            )
            return

        if action == "acknowledge":
            alert = acknowledge_alert(alert_id, user_id=user.id)
            event_type = "acknowledged"
            answer_text = f"Alert #{alert.id} acknowledged"
        elif action == "resolve":
            alert = resolve_alert(alert_id, user_id=user.id)
            event_type = "resolved"
            answer_text = f"Alert #{alert.id} resolved"
        else:
            answer_telegram_callback(
                channel,
                callback.id,
                "Unsupported action",
                show_alert=True,
            )
            return

        alerts_repo.create_alert_event(
            alert.id,
            f"telegram_{event_type}",
            f"Telegram action by {user.username}",
        )

        update_telegram_alert(
            channel=channel,
            alert=alert,
            text=format_telegram_alert_message(alert, event_type, actor=user),
            delivery=type("TelegramDelivery", (), {
                "external_channel_id": str(callback.message.chat.id),
                "external_message_id": str(callback.message.message_id),
            })(),
            event_type=event_type,
        )

        answer_telegram_callback(channel, callback.id, answer_text)

        logger.info(
            "telegram action processed",
            extra={
                "extra": {
                    "event_type": "telegram_action",
                    "alert_id": alert.id,
                    "channel_id": channel.id,
                    "action": action,
                    "user_id": user.id,
                    "telegram_user_id": telegram_user_id,
                    "processed_at": utc_now().isoformat(),
                }
            },
        )

    except Exception as exc:
        logger.exception(
            "telegram callback failed",
            extra={
                "extra": {
                    "channel_id": channel.id,
                    "callback_id": getattr(callback, "id", None),
                    "error": str(exc),
                }
            },
        )

        try:
            answer_telegram_callback(
                channel,
                callback.id,
                "IncidentRelay action failed",
                show_alert=True,
            )
        except Exception:
            logger.exception("failed to answer telegram callback after error")
