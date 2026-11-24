import hashlib
import hmac

from app.settings import Config


# Shelve buttons the callback payload can carry. 7 days is the longest
# duration the shelving service accepts.
SHELVE_DURATION_SPECS = (
    {
        "token": "1h",
        "code": "s1h",
        "seconds": 3600,
        "button": "Shelve 1h",
        "label": "1 hour",
    },
    {
        "token": "4h",
        "code": "s4h",
        "seconds": 4 * 3600,
        "button": "Shelve 4h",
        "label": "4 hours",
    },
    {
        "token": "7d",
        "code": "s7d",
        "seconds": 7 * 24 * 3600,
        "button": "Shelve 7d",
        "label": "7 days",
    },
)

_SPECS_BY_TOKEN = {item["token"]: item for item in SHELVE_DURATION_SPECS}
_SPECS_BY_CODE = {item["code"]: item for item in SHELVE_DURATION_SPECS}

ALLOWED_TELEGRAM_ACTIONS = {
    "ack": "acknowledge",
    "resolve": "resolve",
    "uns": "unshelve",
    **{item["code"]: "shelve" for item in SHELVE_DURATION_SPECS},
}


def parse_shelve_duration_list(value):
    """Return shelve specs for a comma-separated config value.

    Unknown tokens are ignored. An empty or fully invalid value keeps the
    single 1 hour button, which is the historical keyboard.
    """

    chosen = []
    seen = set()

    for raw in str(value or "").split(","):
        token = raw.strip().lower()

        if not token or token in seen or token not in _SPECS_BY_TOKEN:
            continue

        seen.add(token)
        chosen.append(_SPECS_BY_TOKEN[token])

    if not chosen:
        return [_SPECS_BY_TOKEN["1h"]]

    return chosen


def configured_shelve_durations():
    """Return the shelve buttons enabled in the service config."""

    return parse_shelve_duration_list(
        getattr(Config, "TELEGRAM_SHELVE_DURATIONS", "1h")
    )


def shelve_duration_label(seconds):
    """Return a short human label for a shelve duration."""

    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "unknown duration"

    for item in SHELVE_DURATION_SPECS:
        if item["seconds"] == seconds:
            return item["label"]

    return f"{seconds} seconds"


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
    spec = _SPECS_BY_CODE.get(action)

    if spec:
        result["duration_seconds"] = spec["seconds"]

    return result
