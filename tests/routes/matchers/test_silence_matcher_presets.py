from datetime import datetime, timedelta

from app.services.silences import find_active_silence
from tests.factories import (
    create_group,
    create_matcher_preset,
    create_silence,
    create_team,
    unique,
)
from app.modules.common import utc_now


def silence_payload(team, *, matcher_preset_id=None, matchers=None):
    now = utc_now()

    return {
        "team_id": team.id,
        "name": "Compute silence",
        "reason": "Maintenance",
        "matcher_preset_id": matcher_preset_id,
        "matchers": matchers or {},
        "starts_at": (now - timedelta(minutes=5)).isoformat(),
        "ends_at": (now + timedelta(hours=1)).isoformat(),
        "created_by": None,
    }


def test_create_silence_with_matcher_preset(
    client,
    admin_headers,
    db,
):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    preset = create_matcher_preset(
        team,
        matchers={"labels": {"role": "compute"}},
    )

    response = client.post(
        "/api/silences",
        headers=admin_headers,
        json=silence_payload(
            team,
            matcher_preset_id=preset.id,
            matchers={"severity": "critical"},
        ),
    )

    assert response.status_code == 201, response.get_json()

    payload = response.get_json()

    assert payload["matcher_preset_id"] == preset.id
    assert payload["matcher_preset"]["name"] == preset.name
    assert payload["matchers"] == {"severity": "critical"}


def test_silence_rejects_matcher_preset_from_another_team(
    client,
    admin_headers,
    db,
):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    other_team = create_team(group, slug=unique("other-team"))
    preset = create_matcher_preset(other_team)

    response = client.post(
        "/api/silences",
        headers=admin_headers,
        json=silence_payload(
            team,
            matcher_preset_id=preset.id,
        ),
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "matcher_preset_invalid"


def test_silence_matches_preset_and_local_matchers(db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    preset = create_matcher_preset(
        team,
        matchers={"labels": {"environment": "production"}},
    )
    silence = create_silence(
        team,
        matcher_preset=preset,
        matchers={"severity": "critical"},
    )

    matched = find_active_silence(
        team.id,
        {
            "severity": "critical",
            "labels": {
                "environment": "production",
            },
        },
    )

    wrong_environment = find_active_silence(
        team.id,
        {
            "severity": "critical",
            "labels": {
                "environment": "staging",
            },
        },
    )

    wrong_severity = find_active_silence(
        team.id,
        {
            "severity": "warning",
            "labels": {
                "environment": "production",
            },
        },
    )

    assert matched == silence
    assert wrong_environment is None
    assert wrong_severity is None


def test_disabled_silence_matcher_preset_does_not_match(db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    preset = create_matcher_preset(
        team,
        matchers={"labels": {"role": "compute"}},
        enabled=False,
    )

    create_silence(
        team,
        matcher_preset=preset,
        matchers={},
    )

    found = find_active_silence(
        team.id,
        {
            "labels": {
                "role": "compute",
            },
        },
    )

    assert found is None


def test_matcher_preset_used_by_silence_cannot_be_deleted(
    client,
    admin_headers,
    db,
):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    preset = create_matcher_preset(team)

    create_silence(
        team,
        matcher_preset=preset,
    )

    response = client.delete(
        f"/api/matcher-presets/{preset.id}",
        headers=admin_headers,
    )

    assert response.status_code == 409
    assert response.get_json()["error"] == "matcher_preset_in_use"
