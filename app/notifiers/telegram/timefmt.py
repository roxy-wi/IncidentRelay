"""Display times for Telegram messages.

IncidentRelay stores naive UTC values. The ``[telegram] timezone`` option
selects one display zone. ``UTC`` keeps the historical
``dd.mm.YYYY HH:MM:SS UTC`` text.
"""

from datetime import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.settings import Config


def display_zone():
    """Return the configured display zone, or UTC when the name is unknown."""

    name = (getattr(Config, "TELEGRAM_TIMEZONE", None) or "UTC").strip()

    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def format_moment(value):
    """Return a local timestamp. UTC keeps seconds and the UTC suffix."""

    if not value:
        return "-"

    try:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        local = value.astimezone(display_zone())
    except (AttributeError, ValueError, OverflowError):
        return str(value)

    if getattr(display_zone(), "key", "UTC") == "UTC":
        return local.strftime("%d.%m.%Y %H:%M:%S UTC")

    return local.strftime("%d.%m.%Y %H:%M %Z")


def format_duration(delta):
    """Return a short duration: less than a minute, 45m, 3h 05m, 2d 3h."""

    seconds = max(int(delta.total_seconds()), 0)

    if seconds < 60:
        return "less than a minute"

    if seconds < 3600:
        return f"{seconds // 60}m"

    if seconds < 86400:
        return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"

    return f"{seconds // 86400}d {seconds % 86400 // 3600}h"
