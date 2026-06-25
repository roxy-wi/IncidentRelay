from tests.factories import create_group, create_priority_policy, create_team


def service_payload(team, **overrides):
    payload = {
        "team_id": team.id,
        "slug": "payments-api",
        "name": "Payments API",
    }
    payload.update(overrides)
    return payload


def test_create_service_with_priority_policy(client, admin_headers):
    group = create_group()
    team = create_team(group)
    policy = create_priority_policy(team, name="Production priority")

    response = client.post(
        "/api/services",
        headers=admin_headers,
        json=service_payload(team, priority_policy_id=policy.id),
    )

    assert response.status_code == 201

    result = response.get_json()

    assert result["priority_policy_id"] == policy.id
    assert result["priority_policy_name"] == "Production priority"


def test_service_rejects_priority_policy_from_another_team(client, admin_headers):
    group = create_group()
    service_team = create_team(group)
    policy_team = create_team(group)
    policy = create_priority_policy(policy_team)

    response = client.post(
        "/api/services",
        headers=admin_headers,
        json=service_payload(service_team, priority_policy_id=policy.id),
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "priority_policy_team_mismatch"


def test_service_rejects_disabled_priority_policy(client, admin_headers):
    group = create_group()
    team = create_team(group)
    policy = create_priority_policy(team)
    policy.enabled = False
    policy.save()

    response = client.post(
        "/api/services",
        headers=admin_headers,
        json=service_payload(team, priority_policy_id=policy.id),
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "priority_policy_disabled"


def test_service_priority_policy_can_be_cleared(client, admin_headers):
    group = create_group()
    team = create_team(group)
    policy = create_priority_policy(team)

    response = client.post(
        "/api/services",
        headers=admin_headers,
        json=service_payload(team, priority_policy_id=policy.id),
    )

    assert response.status_code == 201
    service = response.get_json()

    response = client.put(
        f"/api/services/{service['id']}",
        headers=admin_headers,
        json=service_payload(team, priority_policy_id=None),
    )

    assert response.status_code == 200
    assert response.get_json()["priority_policy_id"] is None
    assert response.get_json()["priority_policy_name"] is None
