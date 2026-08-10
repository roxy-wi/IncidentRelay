import datetime as dt
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo


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


def as_utc_naive(value):
    """Return naive UTC datetime from datetime or ISO string.

    IncidentRelay stores timestamps as naive UTC values. Naive inputs are
    therefore interpreted as UTC for backward compatibility.
    """
    value = as_utc_aware(value)

    if value is None:
        return None

    return value.replace(tzinfo=None)


def as_utc_naive_seconds(value):
    """Return naive UTC datetime normalized to whole seconds."""
    value = as_utc_naive(value)

    if value is None:
        return None

    return value.replace(microsecond=0)


def timezone_or_utc(timezone_name):
    """Return requested IANA timezone, falling back to UTC."""
    try:
        return ZoneInfo(str(timezone_name or "UTC"))
    except Exception:
        return ZoneInfo("UTC")


def local_datetime_to_utc_naive(value, timezone_name):
    """Convert a local wall-clock datetime to IncidentRelay naive UTC.

    Naive values are interpreted in ``timezone_name``. Aware values already
    represent an absolute instant and are converted directly to UTC.
    """
    value = parse_datetime(value)

    if value is None:
        return None

    if value.tzinfo is not None:
        return value.astimezone(dt_timezone.utc).replace(tzinfo=None)

    zone = timezone_or_utc(timezone_name)
    return value.replace(tzinfo=zone).astimezone(dt_timezone.utc).replace(tzinfo=None)


def utc_datetime_to_local_naive(value, timezone_name):
    """Convert an absolute UTC datetime to naive local wall-clock time."""
    value = as_utc_aware(value)

    if value is None:
        return None

    return value.astimezone(timezone_or_utc(timezone_name)).replace(tzinfo=None)


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


def utc_now_seconds() -> dt.datetime:
    """Return current naive UTC time normalized to whole seconds."""
    return utc_now().replace(microsecond=0)
