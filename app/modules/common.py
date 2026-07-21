import datetime as dt
from datetime import datetime, timezone as dt_timezone


class SafeFormatDict(dict):
    """Keep unknown template placeholders unchanged."""

    def __missing__(self, key):
        return "{" + key + "}"


def parse_datetime(value):
    """Parse datetime or ISO datetime string."""
    if value is None:
        return None

    if isinstance(value, str):
        text = value.strip()

        if not text:
            return None

        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"

        try:
            return datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("datetime must be ISO datetime") from exc

    if isinstance(value, datetime):
        return value

    raise ValueError("datetime must be ISO datetime")


def as_utc_aware(value):
    """Return aware UTC datetime from datetime or ISO string."""
    value = parse_datetime(value)

    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=dt_timezone.utc)

    return value.astimezone(dt_timezone.utc)


def as_naive_datetime(value):
    """Return naive wall-clock datetime.

    Used by Maintenance Windows where starts_at/ends_at are interpreted
    in the window.timezone, not as UTC instants.
    """
    value = parse_datetime(value)

    if value is None:
        return None

    if value.tzinfo is not None:
        return value.replace(tzinfo=None)

    return value


def truncate_text(value, limit=500):
    value = str(value or "").strip()

    if len(value) <= limit:
        return value

    return value[: limit - 1].rstrip() + "…"



UTC = getattr(dt, "UTC", dt.timezone.utc)


def utc_now() -> dt.datetime:
    """Return current UTC time without tzinfo.

    IncidentRelay stores timestamps as naive UTC values.
    """
    return dt.datetime.now(UTC).replace(tzinfo=None)
