from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.modules.db import rotations_repo
from app.modules.common import as_utc_aware, as_utc_naive
from app.services.rotation_schedule import (
    effective_layer_value,
    layer_slot_index,
    layer_start_utc_naive,
    next_layer_boundary_utc,
)


_OVERRIDE_PRIORITY = 1_000_000


def utc_isoformat(value):
    """Return UTC ISO datetime with Z suffix for browser-safe parsing."""
    return as_utc_aware(value).isoformat().replace("+00:00", "Z")


def parse_date_or_datetime(value):
    """Parse ISO date or datetime value."""

    if "T" in value:
        return datetime.fromisoformat(value)

    return datetime.fromisoformat(value + "T00:00:00")


def build_team_calendar(team_id, start_at, end_at):
    """Build final on-call calendar events for a team."""

    events = []

    rotations = rotations_repo.list_rotations(
        team_id=team_id,
        enabled_only=True,
    )

    for rotation in rotations:
        events.extend(build_rotation_calendar(rotation, start_at, end_at))

    return sorted(events, key=lambda item: item["start"])


def build_rotation_calendar(rotation, start_at, end_at):
    """Build final calendar events for one rotation.

    Layers produce candidate events.
    Overrides produce higher-priority candidate events.
    Final output contains only the winner for every time slice.
    """

    candidates = []

    layers = rotations_repo.list_rotation_layers(
        rotation.id,
        enabled_only=True,
    )

    for layer in layers:
        candidates.extend(
            build_layer_candidate_events(
                rotation=rotation,
                layer=layer,
                start_at=start_at,
                end_at=end_at,
            )
        )

    candidates.extend(
        build_override_candidate_events(
            rotation=rotation,
            start_at=start_at,
            end_at=end_at,
        )
    )

    return collapse_calendar_candidates(candidates, start_at, end_at)


def is_layer_member_effective_at(member, at):
    starts_at = as_utc_naive(member.starts_at) if member.starts_at else None
    ends_at = as_utc_naive(member.ends_at) if member.ends_at else None

    if starts_at is not None and starts_at > at:
        return False

    if ends_at is not None and ends_at <= at:
        return False

    return True


def get_effective_layer_members_at(members, at):
    return [
        member
        for member in members
        if is_layer_member_effective_at(member, at)
    ]


def get_next_layer_member_boundary(members, at, fallback):
    """Return next membership period boundary after current cursor."""

    boundary = fallback

    for member in members:
        for value in (member.starts_at, member.ends_at):
            if not value:
                continue

            value = as_utc_naive(value)

            if at < value < boundary:
                boundary = value

    return boundary


def build_layer_candidate_events(rotation, layer, start_at, end_at):
    """Build candidate events for one layer."""

    if not layer.enabled or layer.deleted:
        return []

    members = rotations_repo.list_rotation_layer_member_periods(
        layer.id,
        start_at=start_at,
        end_at=end_at,
        include_inactive_users=True,
    )

    if not members:
        return []

    layer_start_at = layer_start_utc_naive(layer)

    duration_seconds = int(
        effective_layer_value(layer, "duration_seconds", rotation.duration_seconds)
        or 86400
    )

    if duration_seconds <= 0:
        duration_seconds = 86400

    windows = get_layer_active_windows(layer, start_at, end_at)
    events = []

    for window_start, window_end in windows:
        cursor = max(window_start, layer_start_at, start_at)
        window_end = min(window_end, end_at)

        while cursor < window_end:
            user = get_layer_user_at(
                layer=layer,
                members=members,
                at=cursor,
            )

            next_boundary = next_layer_boundary_utc(layer, cursor)

            next_member_boundary = get_next_layer_member_boundary(
                members=members,
                at=cursor,
                fallback=window_end,
            )

            segment_end = min(next_boundary, next_member_boundary, window_end)

            if segment_end <= cursor:
                segment_end = min(
                    cursor + timedelta(seconds=duration_seconds),
                    window_end,
                )

            if user and segment_end > cursor:
                events.append(
                    {
                        "_start": cursor,
                        "_end": segment_end,
                        "_priority": int(layer.priority or 0),
                        "_order": int(layer.id),
                        "event": {
                            "rotation_id": rotation.id,
                            "rotation_name": rotation.name,
                            "team_id": rotation.team.id,
                            "team_slug": rotation.team.slug,
                            "team_name": rotation.team.name,
                            "layer_id": layer.id,
                            "layer_name": layer.name,
                            "layer_priority": layer.priority,
                            "timezone": effective_layer_value(
                                layer,
                                "timezone",
                                rotation.timezone,
                            ) or "UTC",
                            "user_id": user.id,
                            "username": user.username,
                            "display_name": user.display_name,
                            "type": "layer",
                        },
                    }
                )

            cursor = segment_end

    return events


def build_override_candidate_events(rotation, start_at, end_at):
    """Build override candidates.

    Overrides win over all layer candidates.
    """

    events = []

    for override in rotations_repo.list_rotation_overrides(rotation.id, start_at, end_at):
        event_start = max(as_utc_naive(override.starts_at), start_at)
        event_end = min(as_utc_naive(override.ends_at), end_at)

        if event_end <= event_start:
            continue

        events.append(
            {
                "_start": event_start,
                "_end": event_end,
                "_priority": _OVERRIDE_PRIORITY,
                "_order": int(override.id),
                "event": {
                    "override_id": override.id,
                    "rotation_id": rotation.id,
                    "rotation_name": rotation.name,
                    "team_id": rotation.team.id,
                    "team_slug": rotation.team.slug,
                    "team_name": rotation.team.name,
                    "layer_id": None,
                    "layer_name": None,
                    "layer_priority": None,
                    "timezone": rotation.timezone or "UTC",
                    "user_id": override.user.id,
                    "username": override.user.username,
                    "display_name": override.user.display_name,
                    "reason": override.reason,
                    "type": "override",
                },
            }
        )

    return events


def collapse_calendar_candidates(candidates, start_at, end_at):
    """Collapse overlapping candidates into final schedule events."""

    point_set = {start_at, end_at}
    normalized = []

    for candidate in candidates:
        item_start = max(candidate["_start"], start_at)
        item_end = min(candidate["_end"], end_at)

        if item_end <= item_start:
            continue

        candidate = dict(candidate)
        candidate["_start"] = item_start
        candidate["_end"] = item_end

        normalized.append(candidate)
        point_set.add(item_start)
        point_set.add(item_end)

    points = sorted(point_set)

    result = []

    for index in range(len(points) - 1):
        segment_start = points[index]
        segment_end = points[index + 1]

        if segment_end <= segment_start:
            continue

        active_candidates = [
            candidate
            for candidate in normalized
            if candidate["_start"] <= segment_start
            and candidate["_end"] >= segment_end
        ]

        if not active_candidates:
            continue

        winner = max(
            active_candidates,
            key=lambda candidate: (
                candidate["_priority"],
                candidate["_order"],
            ),
        )

        event = dict(winner["event"])
        event["start"] = utc_isoformat(segment_start)
        event["end"] = utc_isoformat(segment_end)

        append_or_merge_calendar_event(result, event)

    return result


def append_or_merge_calendar_event(events, event):
    """Merge adjacent equal events to avoid noisy calendar output."""

    if not events:
        events.append(event)
        return

    previous = events[-1]

    if (
        previous["end"] == event["start"]
        and calendar_event_identity(previous) == calendar_event_identity(event)
    ):
        previous["end"] = event["end"]
        return

    events.append(event)


def calendar_event_identity(event):
    """Return identity used for merging adjacent events."""

    return (
        event.get("type"),
        event.get("rotation_id"),
        event.get("layer_id"),
        event.get("override_id"),
        event.get("user_id"),
    )


def get_layer_active_windows(layer, start_at, end_at):
    """Return UTC-naive active windows for a layer."""

    restrictions = rotations_repo.list_rotation_layer_restrictions(layer.id)

    if not restrictions:
        return [(start_at, end_at)]

    timezone_name = effective_layer_value(
        layer,
        "timezone",
        getattr(layer.rotation, "timezone", "UTC"),
    ) or "UTC"

    try:
        zone = ZoneInfo(timezone_name)
    except Exception:
        zone = ZoneInfo("UTC")

    windows = []

    for local_day in iter_local_days(start_at, end_at, zone):
        for restriction in restrictions:
            window = restriction_window_for_day(
                restriction=restriction,
                local_day=local_day,
                zone=zone,
                range_start=start_at,
                range_end=end_at,
            )

            if window:
                windows.append(window)

    return merge_windows(windows)


def iter_local_days(start_at, end_at, zone):
    """Yield local dates covering the requested UTC range."""

    local_start = as_utc_aware(start_at).astimezone(zone).date() - timedelta(days=1)
    local_end = as_utc_aware(end_at).astimezone(zone).date() + timedelta(days=1)

    cursor = local_start

    while cursor <= local_end:
        yield cursor
        cursor = cursor + timedelta(days=1)


def restriction_window_for_day(restriction, local_day, zone, range_start, range_end):
    """Build one restriction window for a local day."""

    if restriction.weekday is not None and local_day.weekday() != restriction.weekday:
        return None

    start_minutes = minutes_from_hhmm(restriction.start_time)
    end_minutes = minutes_from_hhmm(restriction.end_time)

    if start_minutes == end_minutes:
        local_start = datetime.combine(local_day, time(0, 0), tzinfo=zone)
        local_end = local_start + timedelta(days=1)
    else:
        local_start = datetime.combine(
            local_day,
            time(start_minutes // 60, start_minutes % 60),
            tzinfo=zone,
        )

        if start_minutes < end_minutes:
            local_end_day = local_day
        else:
            local_end_day = local_day + timedelta(days=1)

        local_end = datetime.combine(
            local_end_day,
            time(end_minutes // 60, end_minutes % 60),
            tzinfo=zone,
        )

    window_start = as_utc_naive(local_start)
    window_end = as_utc_naive(local_end)

    window_start = max(window_start, range_start)
    window_end = min(window_end, range_end)

    if window_end <= window_start:
        return None

    return window_start, window_end


def merge_windows(windows):
    """Merge overlapping active windows."""

    if not windows:
        return []

    windows = sorted(windows, key=lambda item: item[0])
    merged = [windows[0]]

    for start_at, end_at in windows[1:]:
        previous_start, previous_end = merged[-1]

        if start_at <= previous_end:
            merged[-1] = (previous_start, max(previous_end, end_at))
        else:
            merged.append((start_at, end_at))

    return merged


def get_layer_user_at(layer, members, at):
    """Return scheduled user for a layer at a given UTC time."""

    effective_members = get_effective_layer_members_at(members, at)

    if not effective_members:
        return None

    slot = layer_slot_index(layer, at)
    if slot is None:
        return None

    return effective_members[slot % len(effective_members)].user


def minutes_from_hhmm(value):
    """Convert HH:MM to minutes from midnight."""

    hour_raw, minute_raw = str(value).split(":", 1)
    return int(hour_raw) * 60 + int(minute_raw)
