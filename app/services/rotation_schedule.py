from datetime import timedelta

from app.modules.common import (
    as_utc_aware,
    as_utc_naive,
    local_datetime_to_utc_naive,
    timezone_or_utc,
)


def effective_layer_value(layer, field_name, default=None):
    """Return layer schedule value with fallback to the parent rotation."""
    value = getattr(layer, field_name, None)

    if value not in (None, ""):
        return value

    rotation = getattr(layer, "rotation", None)
    if rotation is not None:
        value = getattr(rotation, field_name, None)
        if value not in (None, ""):
            return value

    return default


def layer_timezone_name(layer):
    return effective_layer_value(layer, "timezone", "UTC") or "UTC"


def layer_timezone(layer):
    return timezone_or_utc(layer_timezone_name(layer))


def layer_start_local_naive(layer):
    """Return schedule anchor as local wall-clock time."""
    value = effective_layer_value(layer, "start_at")
    if value is None:
        return None

    zone = layer_timezone(layer)
    if value.tzinfo is None:
        return value

    return value.astimezone(zone).replace(tzinfo=None)


def layer_start_utc_naive(layer):
    """Return schedule anchor as naive UTC."""
    value = effective_layer_value(layer, "start_at")
    if value is None:
        return None

    return local_datetime_to_utc_naive(value, layer_timezone_name(layer))


def layer_duration_seconds(layer):
    value = effective_layer_value(layer, "duration_seconds", 86400)
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 86400
    return value if value > 0 else 86400


def _calendar_interval(layer):
    """Return local-wall-clock interval for day/week based schedules.

    Daily/weekly rotations and custom day/week intervals must preserve the
    local handoff clock across DST changes. Minute/hour custom intervals stay
    fixed-duration UTC intervals.
    """
    rotation_type = str(effective_layer_value(layer, "rotation_type", "daily") or "daily")

    if rotation_type == "daily":
        # Keep compatibility with legacy/internal rows that use a non-daily
        # duration while still carrying rotation_type="daily".
        if layer_duration_seconds(layer) == 86400:
            return timedelta(days=1)
        return None
    if rotation_type == "weekly":
        if layer_duration_seconds(layer) == 604800:
            return timedelta(weeks=1)
        return None

    if rotation_type != "custom":
        return None

    unit = str(effective_layer_value(layer, "interval_unit", "days") or "days")
    try:
        value = max(1, int(effective_layer_value(layer, "interval_value", 1) or 1))
    except (TypeError, ValueError):
        value = 1

    if unit == "days":
        return timedelta(days=value)
    if unit == "weeks":
        return timedelta(weeks=value)

    return None


def layer_slot_index(layer, at):
    """Return zero-based schedule slot for an absolute UTC instant.

    ``None`` means the layer schedule has not started yet. Calendar-day/week
    cadences are measured in local wall-clock time so DST does not move the
    handoff clock.
    """
    at = as_utc_naive(at)
    start_utc = layer_start_utc_naive(layer)

    if start_utc is None:
        return 0
    if at < start_utc:
        return None

    calendar_interval = _calendar_interval(layer)
    if calendar_interval is not None:
        start_local = layer_start_local_naive(layer)
        now_local = as_utc_aware(at).astimezone(layer_timezone(layer)).replace(tzinfo=None)
        elapsed = now_local - start_local
        return int(elapsed.total_seconds()) // int(calendar_interval.total_seconds())

    elapsed_seconds = int((at - start_utc).total_seconds())
    return elapsed_seconds // layer_duration_seconds(layer)


def next_layer_boundary_utc(layer, at):
    """Return next slot boundary as naive UTC."""
    at = as_utc_naive(at)
    start_utc = layer_start_utc_naive(layer)

    if start_utc is None:
        return None
    if at < start_utc:
        return start_utc

    slot = layer_slot_index(layer, at)
    calendar_interval = _calendar_interval(layer)

    if calendar_interval is not None:
        boundary_local = layer_start_local_naive(layer) + calendar_interval * (slot + 1)
        return local_datetime_to_utc_naive(boundary_local, layer_timezone_name(layer))

    return start_utc + timedelta(seconds=layer_duration_seconds(layer) * (slot + 1))
