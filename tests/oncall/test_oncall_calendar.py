from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from app.modules.db import rotations_repo
from app.services.calendar_service import build_rotation_calendar, parse_date_or_datetime
from app.services.oncall import get_current_oncall_user, get_next_rotation_user
from tests.factories import (
    add_user_to_team,
    create_group,
    create_rotation,
    create_rotation_override,
    create_team,
    create_user,
)


def test_get_current_oncall_user_rotates_by_duration(db):
    start = datetime(2026, 5, 18, 9, 0, 0)
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    alice = create_user("alice", group)
    bob = create_user("bob", group)
    add_user_to_team(team, alice)
    add_user_to_team(team, bob)
    rotation = create_rotation(
        team,
        users=[alice, bob],
        start_at=start,
        duration_seconds=3600,
    )

    assert get_current_oncall_user(rotation, start).username == "alice"
    assert get_current_oncall_user(rotation, start + timedelta(hours=1)).username == "bob"
    assert get_current_oncall_user(rotation, start + timedelta(hours=2)).username == "alice"


def test_get_current_oncall_user_prefers_active_override(db):
    start = datetime(2026, 5, 18, 9, 0, 0)
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    alice = create_user("alice", group)
    bob = create_user("bob", group)
    rotation = create_rotation(
        team,
        users=[alice],
        start_at=start,
        duration_seconds=3600,
    )
    create_rotation_override(
        rotation,
        bob,
        starts_at=start - timedelta(minutes=10),
        ends_at=start + timedelta(minutes=10),
    )

    assert get_current_oncall_user(rotation, start).username == "bob"


def test_get_next_rotation_user_returns_next_member(db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    alice = create_user("alice", group)
    bob = create_user("bob", group)
    rotation = create_rotation(team, users=[alice, bob])

    assert get_next_rotation_user(rotation, alice).username == "bob"
    assert get_next_rotation_user(rotation, bob).username == "alice"


def test_parse_date_or_datetime_accepts_date_and_datetime():
    assert parse_date_or_datetime("2026-05-18") == datetime(2026, 5, 18, 0, 0, 0)
    assert parse_date_or_datetime("2026-05-18T09:30:00") == datetime(2026, 5, 18, 9, 30, 0)


def test_build_rotation_calendar_returns_slots(db):
    start = datetime(2026, 5, 18, 9, 0, 0)
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    alice = create_user("alice", group)
    bob = create_user("bob", group)
    rotation = create_rotation(
        team,
        users=[alice, bob],
        start_at=start,
        duration_seconds=3600,
    )

    events = build_rotation_calendar(
        rotation,
        start,
        start + timedelta(hours=2),
    )

    assert [event["username"] for event in events] == ["alice", "bob"]
    assert events[0]["type"] == "layer"
    assert events[0]["layer_name"] == "Default layer"
    assert events[0]["team_slug"] == "sre"


def parse_calendar_event_datetime(value):
    value = str(value)

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    parsed = datetime.fromisoformat(value)

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt_timezone.utc)

    return parsed.astimezone(dt_timezone.utc)


def test_moscow_midnight_rotation_is_not_shifted_to_03(db):
    moscow = ZoneInfo("Europe/Moscow")

    group = create_group(slug="infra")
    team = create_team(group, slug="sre")

    alice = create_user("alice", group)
    add_user_to_team(team, alice)

    rotation = create_rotation(
        team,
        users=[alice],
        start_at=datetime(2026, 6, 1, 0, 0, 0),
        duration_seconds=86400,
        timezone="Europe/Moscow",
        handoff_time="00:00",
    )

    layer = rotations_repo.get_or_create_default_layer(rotation.id)
    assert layer.timezone == "Europe/Moscow"
    assert layer.handoff_time == "00:00"
    assert layer.start_at == datetime(2026, 6, 1, 0, 0, 0)
    assert layer.duration_seconds == 86400

    # 2026-06-01 00:00 Europe/Moscow == 2026-05-31 21:00 UTC.
    # Calendar service internally works with UTC-naive ranges.
    events = build_rotation_calendar(
        rotation,
        datetime(2026, 5, 31, 21, 0, 0),
        datetime(2026, 6, 2, 21, 0, 0),
    )

    assert events

    first_start = parse_calendar_event_datetime(events[0]["start"])
    first_start_moscow = first_start.astimezone(moscow)

    assert first_start_moscow.hour == 0
    assert first_start_moscow.minute == 0
