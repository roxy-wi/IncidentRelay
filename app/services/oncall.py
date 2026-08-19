from app.modules.db import rotations_repo
from app.modules.common import as_utc_aware, as_utc_naive, utc_now
from app.services.rotation_schedule import (
    layer_slot_index,
    layer_timezone,
)


def _to_layer_local(now, layer):
    return as_utc_aware(now).astimezone(layer_timezone(layer))


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

    slot = layer_slot_index(layer, now)
    if slot is None:
        return None

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
