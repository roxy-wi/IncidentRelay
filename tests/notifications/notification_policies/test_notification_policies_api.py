from app.services.notifications.policies import service as policy_service
from tests.factories import (
    create_channel,
    create_group,
    create_service,
    create_team,
)


def test_create_and_get_notification_policy(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)

    response = client.post(
        "/api/notification-policies",
        headers=admin_headers,
        json={
            "team_id": team.id,
            "name": "Production notifications",
            "description": "Production delivery policy.",
        },
    )

    assert response.status_code == 201

    created = response.get_json()

    assert created["team_id"] == team.id
    assert created["name"] == "Production notifications"
    assert created["enabled"] is True
    assert created["services_count"] == 0

    response = client.get(
        f"/api/notification-policies/{created['id']}",
        headers=admin_headers,
    )

    assert response.status_code == 200

    loaded = response.get_json()

    assert loaded["id"] == created["id"]
    assert loaded["rules"] == []


def test_list_notification_policies_by_team(
    client,
    admin_headers,
):
    group = create_group()
    first_team = create_team(group)
    second_team = create_team(group)

    policy_service.create_policy({
        "team_id": first_team.id,
        "name": "First policy",
    })

    policy_service.create_policy({
        "team_id": second_team.id,
        "name": "Second policy",
    })

    response = client.get(
        f"/api/notification-policies?team_id={first_team.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200

    policies = response.get_json()

    assert len(policies) == 1
    assert policies[0]["team_id"] == first_team.id
    assert policies[0]["name"] == "First policy"


def test_create_notification_policy_rejects_duplicate_name(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)

    payload = {
        "team_id": team.id,
        "name": "Production notifications",
    }

    first_response = client.post(
        "/api/notification-policies",
        headers=admin_headers,
        json=payload,
    )

    assert first_response.status_code == 201

    second_response = client.post(
        "/api/notification-policies",
        headers=admin_headers,
        json=payload,
    )

    assert second_response.status_code == 409
    assert second_response.get_json()["error"] == (
        "notification_policy_conflict"
    )


def test_create_notification_policy_rule(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)
    channel = create_channel(group, team)

    policy = policy_service.create_policy({
        "team_id": team.id,
        "name": "Production notifications",
    })

    response = client.post(
        f"/api/notification-policies/{policy.id}/rules",
        headers=admin_headers,
        json={
            "name": "Critical alerts",
            "event_types": [
                "notification",
                "escalation",
            ],
            "matchers": {
                "priority": ["p1", "p2"],
            },
            "channel_ids": [channel.id],
            "continue_matching": False,
        },
    )

    assert response.status_code == 201

    rule = response.get_json()

    assert rule["policy_id"] == policy.id
    assert rule["position"] == 1
    assert rule["channel_ids"] == [channel.id]
    assert rule["matchers"] == {
        "priority": ["p1", "p2"],
    }


def test_create_enabled_rule_requires_channel(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)

    policy = policy_service.create_policy({
        "team_id": team.id,
        "name": "Production notifications",
    })

    response = client.post(
        f"/api/notification-policies/{policy.id}/rules",
        headers=admin_headers,
        json={
            "name": "Invalid rule",
            "event_types": ["notification"],
            "channel_ids": [],
            "enabled": True,
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == (
        "notification_policy_invalid"
    )


def test_reorder_notification_policy_rules(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)
    channel = create_channel(group, team)

    policy = policy_service.create_policy({
        "team_id": team.id,
        "name": "Production notifications",
    })

    first = policy_service.create_rule(
        policy.id,
        {
            "name": "First",
            "channel_ids": [channel.id],
        },
    )

    second = policy_service.create_rule(
        policy.id,
        {
            "name": "Second",
            "channel_ids": [channel.id],
        },
    )

    response = client.put(
        f"/api/notification-policies/{policy.id}/rules/order",
        headers=admin_headers,
        json={
            "rule_ids": [
                second.id,
                first.id,
            ],
        },
    )

    assert response.status_code == 200

    rules = response.get_json()

    assert [rule["id"] for rule in rules] == [
        second.id,
        first.id,
    ]

    assert [rule["position"] for rule in rules] == [1, 2]


def test_rule_from_another_policy_returns_404(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)
    channel = create_channel(group, team)

    first_policy = policy_service.create_policy({
        "team_id": team.id,
        "name": "First policy",
    })

    second_policy = policy_service.create_policy({
        "team_id": team.id,
        "name": "Second policy",
    })

    rule = policy_service.create_rule(
        second_policy.id,
        {
            "name": "Second policy rule",
            "channel_ids": [channel.id],
        },
    )

    response = client.put(
        (
            f"/api/notification-policies/{first_policy.id}"
            f"/rules/{rule.id}"
        ),
        headers=admin_headers,
        json={
            "name": "Changed",
        },
    )

    assert response.status_code == 404


def test_delete_policy_rejects_policy_used_by_service(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)

    policy = policy_service.create_policy({
        "team_id": team.id,
        "name": "Production notifications",
    })

    service = create_service(team)
    service.notification_policy = policy
    service.save()

    response = client.delete(
        f"/api/notification-policies/{policy.id}",
        headers=admin_headers,
    )

    assert response.status_code == 409
    assert response.get_json()["error"] == (
        "notification_policy_in_use"
    )
