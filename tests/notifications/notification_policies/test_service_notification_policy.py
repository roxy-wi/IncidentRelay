from tests.factories import (
    create_group,
    create_notification_policy,
    create_team,
    unique,
)


def _service_payload(team, **overrides):
    payload = {
        "team_id": team.id,
        "slug": unique("service"),
        "name": unique("Service"),
        "description": None,
        "service_type": "other",
        "environment": "production",
        "criticality": "medium",
        "tier": "tier_3",
        "status": "operational",
        "status_source": "manual",
        "status_message": None,
        "default_rotation_id": None,
        "default_escalation_policy_id": None,
        "notification_policy_id": None,
        "labels": {},
        "tags": [],
        "metadata": {},
        "enabled": True,
        "public": False,
        "public_name": None,
        "public_description": None,
        "public_order": 100,
    }
    payload.update(overrides)
    return payload


def test_create_service_with_notification_policy(client, admin_headers):
    group = create_group()
    team = create_team(group)
    policy = create_notification_policy(team)

    response = client.post(
        "/api/services",
        headers=admin_headers,
        json=_service_payload(team, notification_policy_id=policy.id),
    )

    assert response.status_code == 201

    service = response.get_json()

    assert service["notification_policy_id"] == policy.id
    assert service["notification_policy_name"] == policy.name


def test_create_service_rejects_policy_from_another_team(
    client,
    admin_headers,
):
    group = create_group()
    service_team = create_team(group)
    policy_team = create_team(group)
    policy = create_notification_policy(policy_team)

    response = client.post(
        "/api/services",
        headers=admin_headers,
        json=_service_payload(
            service_team,
            notification_policy_id=policy.id,
        ),
    )

    assert response.status_code == 400

    result = response.get_json()

    assert result["error"] == "notification_policy_team_mismatch"
    assert result["notification_policy_id"] == policy.id
    assert result["policy_team_id"] == policy_team.id
    assert result["team_id"] == service_team.id


def test_create_service_rejects_disabled_notification_policy(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)
    policy = create_notification_policy(team, enabled=False)

    response = client.post(
        "/api/services",
        headers=admin_headers,
        json=_service_payload(team, notification_policy_id=policy.id),
    )

    assert response.status_code == 400

    result = response.get_json()

    assert result["error"] == "notification_policy_disabled"
    assert result["notification_policy_id"] == policy.id


def test_update_service_clears_notification_policy(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)
    policy = create_notification_policy(team)

    create_payload = _service_payload(
        team,
        notification_policy_id=policy.id,
    )

    create_response = client.post(
        "/api/services",
        headers=admin_headers,
        json=create_payload,
    )

    assert create_response.status_code == 201

    service = create_response.get_json()

    update_payload = {
        **create_payload,
        "notification_policy_id": None,
    }

    response = client.put(
        f"/api/services/{service['id']}",
        headers=admin_headers,
        json=update_payload,
    )

    assert response.status_code == 200

    updated = response.get_json()

    assert updated["notification_policy_id"] is None
    assert updated["notification_policy_name"] is None
