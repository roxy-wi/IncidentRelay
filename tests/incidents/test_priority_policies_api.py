from app.modules.db import incidents_repo
from tests.factories import create_group, create_matcher_preset, create_priority_policy, create_priority_policy_rule, create_service, create_team


def test_create_and_get_priority_policy(client, admin_headers):
    group = create_group()
    team = create_team(group)

    response = client.post(
        "/api/priority-policies",
        headers=admin_headers,
        json={
            "team_id": team.id,
            "name": "Production priority",
            "description": "Automatic incident priority for production.",
            "default_for_team": True,
            "update_mode": "raise_only",
            "source_priority_mode": "ignore",
            "fallback_mode": "severity_mapping",
        },
    )

    assert response.status_code == 201

    created = response.get_json()

    assert created["team_id"] == team.id
    assert created["name"] == "Production priority"
    assert created["default_for_team"] is True
    assert created["rules_count"] == 0
    assert created["services_count"] == 0
    assert created["permissions"]["can_write"] is True

    response = client.get(f"/api/priority-policies/{created['id']}", headers=admin_headers)

    assert response.status_code == 200
    assert response.get_json()["rules"] == []


def test_list_priority_policies_by_team(client, admin_headers):
    group = create_group()
    first_team = create_team(group)
    second_team = create_team(group)

    create_priority_policy(first_team, name="First priority policy")
    create_priority_policy(second_team, name="Second priority policy")

    response = client.get(f"/api/priority-policies?team_id={first_team.id}", headers=admin_headers)

    assert response.status_code == 200

    policies = response.get_json()

    assert len(policies) == 1
    assert policies[0]["team_id"] == first_team.id
    assert policies[0]["name"] == "First priority policy"


def test_duplicate_priority_policy_returns_409(client, admin_headers):
    group = create_group()
    team = create_team(group)

    payload = {
        "team_id": team.id,
        "name": "Production priority",
        "update_mode": "raise_only",
        "source_priority_mode": "ignore",
        "fallback_mode": "severity_mapping",
    }

    assert client.post("/api/priority-policies", headers=admin_headers, json=payload).status_code == 201

    response = client.post("/api/priority-policies", headers=admin_headers, json=payload)

    assert response.status_code == 409
    assert response.get_json()["error"] == "priority_policy_conflict"


def test_update_priority_policy(client, admin_headers):
    group = create_group()
    team = create_team(group)
    policy = create_priority_policy(team)

    response = client.put(
        f"/api/priority-policies/{policy.id}",
        headers=admin_headers,
        json={
            "name": "Updated policy",
            "update_mode": "recalculate",
            "source_priority_mode": "prefer",
        },
    )

    assert response.status_code == 200

    result = response.get_json()

    assert result["name"] == "Updated policy"
    assert result["update_mode"] == "recalculate"
    assert result["source_priority_mode"] == "prefer"


def test_create_priority_policy_rule_with_matcher_preset(client, admin_headers):
    group = create_group()
    team = create_team(group)
    policy = create_priority_policy(team)
    preset = create_matcher_preset(team, matchers={"fields": {"service.environment": "production"}})
    priority = incidents_repo.get_priority_by_slug("p1")

    response = client.post(
        f"/api/priority-policies/{policy.id}/rules",
        headers=admin_headers,
        json={
            "name": "Critical production",
            "matcher_preset_id": preset.id,
            "matchers": {"severity": "critical"},
            "priority_id": priority.id,
            "enabled": True,
        },
    )

    assert response.status_code == 201

    rule = response.get_json()

    assert rule["policy_id"] == policy.id
    assert rule["matcher_preset_id"] == preset.id
    assert rule["matcher_preset"]["name"] == preset.name
    assert rule["priority"]["slug"] == "p1"
    assert rule["matchers"] == {"severity": "critical"}


def test_priority_rule_rejects_preset_from_another_team(client, admin_headers):
    group = create_group()
    first_team = create_team(group)
    second_team = create_team(group)
    policy = create_priority_policy(first_team)
    preset = create_matcher_preset(second_team)
    priority = incidents_repo.get_priority_by_slug("p1")

    response = client.post(
        f"/api/priority-policies/{policy.id}/rules",
        headers=admin_headers,
        json={
            "name": "Cross-team rule",
            "matcher_preset_id": preset.id,
            "matchers": {},
            "priority_id": priority.id,
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "priority_policy_invalid"
    assert "another team" in response.get_json()["message"]


def test_update_priority_policy_rule(client, admin_headers):
    group = create_group()
    team = create_team(group)
    policy = create_priority_policy(team)
    p1 = incidents_repo.get_priority_by_slug("p1")
    p2 = incidents_repo.get_priority_by_slug("p2")
    rule = create_priority_policy_rule(policy, p1, name="Original rule")

    response = client.put(
        f"/api/priority-policies/{policy.id}/rules/{rule.id}",
        headers=admin_headers,
        json={
            "name": "Updated rule",
            "priority_id": p2.id,
            "matchers": {"severity": "high"},
        },
    )

    assert response.status_code == 200

    result = response.get_json()

    assert result["name"] == "Updated rule"
    assert result["priority"]["slug"] == "p2"
    assert result["matchers"] == {"severity": "high"}


def test_reorder_priority_policy_rules(client, admin_headers):
    group = create_group()
    team = create_team(group)
    policy = create_priority_policy(team)
    priority = incidents_repo.get_priority_by_slug("p1")

    first = create_priority_policy_rule(policy, priority, name="First", position=1)
    second = create_priority_policy_rule(policy, priority, name="Second", position=2)

    response = client.put(
        f"/api/priority-policies/{policy.id}/rules/reorder",
        headers=admin_headers,
        json={"rule_ids": [second.id, first.id]},
    )

    assert response.status_code == 200

    rules = response.get_json()

    assert [rule["id"] for rule in rules] == [second.id, first.id]
    assert [rule["position"] for rule in rules] == [1, 2]


def test_delete_assigned_priority_policy_returns_409(client, admin_headers):
    group = create_group()
    team = create_team(group)
    policy = create_priority_policy(team)
    service = create_service(team)

    service.priority_policy = policy
    service.save()

    response = client.delete(f"/api/priority-policies/{policy.id}", headers=admin_headers)

    assert response.status_code == 409
    assert response.get_json()["error"] == "priority_policy_in_use"
