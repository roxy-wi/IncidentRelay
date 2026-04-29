from datetime import datetime, timedelta

from app.modules.db import rotations_repo
from app.services.oncall import get_current_oncall_user


def parse_date_or_datetime(value):
    """
    Parse ISO date or datetime value.
    """

    if "T" in value:
        return datetime.fromisoformat(value)
    return datetime.fromisoformat(value + "T00:00:00")


def build_team_calendar(team_id, start_at, end_at):
    """
    Build rotation calendar events for a team.
    """

    events = []
    rotations = rotations_repo.list_rotations(team_id=team_id, enabled_only=True)

    for rotation in rotations:
        events.extend(build_rotation_calendar(rotation, start_at, end_at))

    return sorted(events, key=lambda item: item["start"])


def build_rotation_calendar(rotation, start_at, end_at):
    """
    Build calendar events for one rotation.
    """

    events = []
    cursor = max(start_at, rotation.start_at)

    while cursor < end_at:
        slot_user = get_current_oncall_user(rotation, cursor)
        slot_end = min(cursor + timedelta(seconds=rotation.duration_seconds), end_at)

        if slot_user:
            events.append({
                "rotation_id": rotation.id,
                "rotation_name": rotation.name,
                "team_id": rotation.team.id,
                "team_slug": rotation.team.slug,
                "user_id": slot_user.id,
                "username": slot_user.username,
                "display_name": slot_user.display_name,
                "start": cursor.isoformat(),
                "end": slot_end.isoformat(),
                "type": "rotation",
            })

        cursor = slot_end

    events.extend(build_override_events(rotation, start_at, end_at))
    return events


def build_override_events(rotation, start_at, end_at):
    """
    Build calendar events for rotation overrides.
    """

    events = []
    for override in rotations_repo.list_rotation_overrides(rotation.id, start_at, end_at):
        events.append({
            "rotation_id": rotation.id,
            "rotation_name": rotation.name,
            "team_id": rotation.team.id,
            "team_slug": rotation.team.slug,
            "user_id": override.user.id,
            "username": override.user.username,
            "display_name": override.user.display_name,
            "start": max(override.starts_at, start_at).isoformat(),
            "end": min(override.ends_at, end_at).isoformat(),
            "reason": override.reason,
            "type": "override",
        })
    return events
