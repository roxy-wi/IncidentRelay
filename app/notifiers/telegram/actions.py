import hashlib
import hmac

from app.settings import Config


ALLOWED_TELEGRAM_ACTIONS = {
    "ack": "acknowledge",
    "resolve": "resolve",
    "s1h": "shelve",
    "uns": "unshelve",
}


def build_telegram_action_data(action, alert_id, channel_id):
    """
    Build compact signed Telegram callback data.
    """
    action = str(action or "").strip()

    if action not in ALLOWED_TELEGRAM_ACTIONS:
        raise ValueError(f"unsupported telegram action: {action}")

    payload = f"ir:{action}:{int(alert_id)}:{int(channel_id)}"
    signature = hmac.new(
        Config.SECRET_KEY.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:12]

    return f"{payload}:{signature}"


def parse_telegram_action_data(value):
    """
    Validate Telegram callback data and return parsed action.
    """
    parts = str(value or "").split(":")

    if len(parts) != 5 or parts[0] != "ir":
        return None

    _, action, alert_id, channel_id, signature = parts

    if action not in ALLOWED_TELEGRAM_ACTIONS:
        return None

    payload = f"ir:{action}:{alert_id}:{channel_id}"
    expected = hmac.new(
        Config.SECRET_KEY.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:12]

    if not hmac.compare_digest(signature, expected):
        return None

    result = {
        "action": ALLOWED_TELEGRAM_ACTIONS[action],
        "alert_id": int(alert_id),
        "channel_id": int(channel_id),
    }
    if action == "s1h":
        result["duration_seconds"] = 3600
    return result
