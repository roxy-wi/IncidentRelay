from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from app.modules.db import rotations_repo
from app.modules.common import as_utc_naive, utc_now


def _effective_layer_value(layer, field_name):
    value = getattr(layer, field_name, None)
    if value is not None:
        return value
    return getattr(layer.rotation, field_name)


def _to_layer_local(now, layer):
    timezone_name = _effective_layer_value(layer, "timezone") or "UTC"

    try:
        zone = ZoneInfo(timezone_name)
    except Exception:
        zone = ZoneInfo("UTC")

    now_utc = now
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=dt_timezone.utc)
    else:
        now_utc = now_utc.astimezone(dt_timezone.utc)

    return now_utc.astimezone(zone)


def _parse_hhmm(value):
    hour_raw, minute_raw = value.split(":", 1)
    return int(hour_raw), int(minute_raw)


def _minutes(value):
    hour, minute = _parse_hhmm(value)
    return hour * 60 + minute


def _restriction_matches(restriction, local_dt):
    start = _minutes(restriction.start_time)
    end = _minutes(restriction.end_time)
    current = local_dt.hour * 60 + local_dt.minute
    weekday = local_dt.weekday()

    if start == end:
        # 00:00-00:00 means full day.
        if restriction.weekday is None:
            return True
        return weekday == restriction.weekday

    if start < end:
        if restriction.weekday is not None and weekday != restriction.weekday:
            return False
        return start <= current < end

    # Overnight window, for example Monday 18:00-09:00.
    # It matches Monday evening and Tuesday morning.
    if restriction.weekday is None:
        return current >= start or current < end

    next_weekday = (restriction.weekday + 1) % 7

    return (
        weekday == restriction.weekday
        and current >= start
    ) or (
        weekday == next_weekday
        and current < end
    )


def is_layer_active_now(layer, now):
    if not layer.enabled or layer.deleted:
        return False

    restrictions = rotations_repo.list_rotation_layer_restrictions(layer.id)
    if not restrictions:
        return True

    local_dt = _to_layer_local(now, layer)

    return any(_restriction_matches(item, local_dt) for item in restrictions)


def get_scheduled_oncall_user_for_layer(layer, now=None):
    """Return scheduled user for one layer."""

    now = as_utc_naive(now or utc_now())

    members = rotations_repo.list_rotation_layer_members(
        layer.id,
        active_only=True,
        at=now,
        include_inactive_users=False,
    )
    if not members:
        return None

    start_at = _effective_layer_value(layer, "start_at")
    duration_seconds = _effective_layer_value(layer, "duration_seconds")

    if not start_at or not duration_seconds:
        return members[0].user

    start_at = as_utc_naive(start_at)
    elapsed = int((now - start_at).total_seconds())

    if elapsed < 0:
        return None

    slot = elapsed // int(duration_seconds)
    return members[slot % len(members)].user


def get_active_rotation_layer(rotation, now=None):
    """Return highest-priority active layer for a rotation."""

    if not rotation or not rotation.enabled or rotation.deleted:
        return None

    now = as_utc_naive(now or utc_now())

    layers = rotations_repo.list_rotation_layers(
        rotation.id,
        enabled_only=True,
    )

    for layer in layers:
        if not is_layer_active_now(layer, now):
            continue

        if get_scheduled_oncall_user_for_layer(layer, now):
            return layer

    return None


def get_scheduled_oncall_user(rotation, now=None):
    """Return scheduled user from active rotation layer."""
    if not rotation or not rotation.enabled or rotation.deleted:
        return None

    now = as_utc_naive(now or utc_now())

    layer = get_active_rotation_layer(rotation, now)
    if not layer:
        return None

    return get_scheduled_oncall_user_for_layer(layer, now)


def get_current_oncall_user(rotation, now=None):
    """Return effective on-call user.

    Rotation override still wins over all layers.
    """
    if not rotation or not rotation.enabled or rotation.deleted:
        return None

    now = as_utc_naive(now or utc_now())

    override = rotations_repo.get_active_override(rotation.id, now)

    if override:
        return override.user

    return get_scheduled_oncall_user(rotation, now)


def get_next_rotation_user(rotation, current_user=None, now=None):
    """Return next user in the active layer."""

    if not rotation or not rotation.enabled or rotation.deleted:
        return None

    now = as_utc_naive(now or utc_now())

    layer = get_active_rotation_layer(rotation, now)
    if not layer:
        return None

    members = rotations_repo.list_rotation_layer_members(
        layer.id,
        active_only=True,
        at=now,
        include_inactive_users=False,
    )

    if not members:
        return None

    if not current_user:
        return members[0].user

    for index, member in enumerate(members):
        if member.user.id == current_user.id:
            return members[(index + 1) % len(members)].user

    return members[0].user
