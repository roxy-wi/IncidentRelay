from app.modules.db import incidents_repo
from tests.factories import (
    create_group,
    create_matcher_preset,
    create_priority_policy,
    create_priority_policy_rule,
    create_team,
)


def test_create_and_get_matcher_preset(client, admin_headers):
    group = create_group()
    team = create_team(group)

    response = client.post(
        "/api/matcher-presets",
        headers=admin_headers,
        json={
            "team_id": team.id,
            "name": "Production services",
            "description": "Matches production services.",
            "matchers": {
                "fields": {
                    "service.environment": "production",
                },
            },
        },
    )

    assert response.status_code == 201

    created = response.get_json()

    assert created["team_id"] == team.id
    assert created["name"] == "Production services"
    assert created["version"] == 1
    assert created["usage_count"] == 0
    assert created["permissions"]["can_write"] is True

    response = client.get(
        f"/api/matcher-presets/{created['id']}",
        headers=admin_headers,
    )

    assert response.status_code == 200

    loaded = response.get_json()

    assert loaded["id"] == created["id"]
    assert loaded["usages"]["notification_policy_rules"] == []
    assert loaded["usages"]["priority_policy_rules"] == []


def test_list_matcher_presets_by_team(client, admin_headers):
    group = create_group()
    first_team = create_team(group)
    second_team = create_team(group)

    create_matcher_preset(first_team, name="First preset")
    create_matcher_preset(second_team, name="Second preset")

    response = client.get(
        f"/api/matcher-presets?team_id={first_team.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200

    presets = response.get_json()

    assert len(presets) == 1
    assert presets[0]["name"] == "First preset"
    assert presets[0]["team_id"] == first_team.id


def test_duplicate_matcher_preset_returns_409(client, admin_headers):
    group = create_group()
    team = create_team(group)

    payload = {
        "team_id": team.id,
        "name": "Production services",
        "matchers": {},
    }

    first_response = client.post(
        "/api/matcher-presets",
        headers=admin_headers,
        json=payload,
    )

    assert first_response.status_code == 201

    second_response = client.post(
        "/api/matcher-presets",
        headers=admin_headers,
        json=payload,
    )

    assert second_response.status_code == 409
    assert second_response.get_json()["error"] == "matcher_preset_conflict"


def test_update_matcher_preset_increments_version(client, admin_headers):
    group = create_group()
    team = create_team(group)
    preset = create_matcher_preset(team)

    response = client.put(
        f"/api/matcher-presets/{preset.id}",
        headers=admin_headers,
        json={"matchers": {"severity": "critical"}},
    )

    assert response.status_code == 200

    updated = response.get_json()

    assert updated["version"] == 2
    assert updated["matchers"] == {"severity": "critical"}


def test_unchanged_update_does_not_increment_version(client, admin_headers):
    group = create_group()
    team = create_team(group)

    preset = create_matcher_preset(
        team,
        matchers={"severity": "critical"},
    )

    response = client.put(
        f"/api/matcher-presets/{preset.id}",
        headers=admin_headers,
        json={"matchers": {"severity": "critical"}},
    )

    assert response.status_code == 200
    assert response.get_json()["version"] == 1


def test_delete_used_matcher_preset_returns_409(client, admin_headers):
    group = create_group()
    team = create_team(group)
    preset = create_matcher_preset(team)
    policy = create_priority_policy(team)
    priority = incidents_repo.get_priority_by_slug("p1")

    create_priority_policy_rule(
        policy,
        priority,
        matcher_preset=preset,
    )

    response = client.delete(
        f"/api/matcher-presets/{preset.id}",
        headers=admin_headers,
    )

    assert response.status_code == 409

    result = response.get_json()

    assert result["error"] == "matcher_preset_in_use"
    assert "matcher preset is used by 1 resource(s)" in result["message"]


def test_get_matcher_preset_includes_usage_details(client, admin_headers):
    group = create_group()
    team = create_team(group)
    preset = create_matcher_preset(team)
    policy = create_priority_policy(team, name="Production priority")
    priority = incidents_repo.get_priority_by_slug("p1")

    rule = create_priority_policy_rule(
        policy,
        priority,
        name="Critical production",
        matcher_preset=preset,
    )

    response = client.get(
        f"/api/matcher-presets/{preset.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200

    result = response.get_json()
    usages = result["usages"]["priority_policy_rules"]

    assert result["usage_count"] == 1
    assert result["priority_policy_rules_count"] == 1
    assert usages == [
        {
            "id": rule.id,
            "name": "Critical production",
            "policy_id": policy.id,
            "policy_name": "Production priority",
        }
    ]
