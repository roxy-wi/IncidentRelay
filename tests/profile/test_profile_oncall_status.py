from datetime import datetime, timedelta

from app.services.user_oncall_status import get_user_oncall_status
from tests.factories import (
    add_user_to_team,
    create_group,
    create_rotation,
    create_team,
    create_user,
)


def test_user_oncall_status_reports_current_shift():
    start = datetime(2026, 5, 30, 9, 0, 0)

    group = create_group(slug="infra")
    team = create_team(group, slug="sre", name="SRE")
    alice = create_user("alice", group, email="alice@example.com")
    add_user_to_team(team, alice)

    create_rotation(
        team,
        name="Primary",
        users=[alice],
        start_at=start,
        duration_seconds=3600,
    )

    data = get_user_oncall_status(
        alice,
        now=start + timedelta(minutes=10),
        lookahead_days=7,
    )

    assert data["is_oncall"] is True
    assert data["status"] == "primary"
    assert len(data["current"]) == 1
    assert data["current"][0]["team_name"] == "SRE"
    assert data["current"][0]["rotation_name"] == "Primary"

    # One-person rotation is continuous, so there may be no separate next slot.
    assert data["next"] == []


def test_user_oncall_status_reports_next_shift_when_not_oncall():
    start = datetime(2026, 5, 30, 9, 0, 0)

    group = create_group(slug="infra")
    team = create_team(group, slug="sre", name="SRE")
    alice = create_user("alice", group, email="alice@example.com")
    bob = create_user("bob", group, email="bob@example.com")

    add_user_to_team(team, alice)
    add_user_to_team(team, bob)

    create_rotation(
        team,
        name="Primary",
        users=[alice, bob],
        start_at=start,
        duration_seconds=3600,
    )

    data = get_user_oncall_status(
        bob,
        now=start + timedelta(minutes=10),
        lookahead_days=7,
    )

    assert data["is_oncall"] is False
    assert data["current"] == []
    assert len(data["next"]) >= 1
    assert data["next"][0]["rotation_name"] == "Primary"


def test_profile_oncall_endpoint_returns_current_user_status(client, auth_headers):
    response = client.get(
        "/api/profile/oncall?days=7",
        headers=auth_headers,
    )

    assert response.status_code == 200

    data = response.get_json()
    assert "is_oncall" in data
    assert "current" in data
    assert "next" in data
    assert "lookahead_days" in data
