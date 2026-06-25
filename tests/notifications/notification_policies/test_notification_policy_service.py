import pytest

from app.modules.db import notification_policies_repo
from app.services.notifications.policies import (
    service as policy_service,
)
from tests.factories import (
    create_channel,
    create_group,
    create_service,
    create_team,
)


def test_create_notification_policy():
    group = create_group()
    team = create_team(group)

    policy = policy_service.create_policy(
        {
            "team_id": team.id,
            "name": "Production notifications",
            "description": "Production delivery policy.",
            "enabled": True,
        }
    )

    assert policy.team_id == team.id
    assert policy.name == "Production notifications"
    assert policy.enabled is True


def test_create_policy_rejects_duplicate_name():
    group = create_group()
    team = create_team(group)

    policy_service.create_policy(
        {
            "team_id": team.id,
            "name": "Production notifications",
        }
    )

    with pytest.raises(
        policy_service.NotificationPolicyConflictError,
        match="already exists",
    ):
        policy_service.create_policy(
            {
                "team_id": team.id,
                "name": "Production notifications",
            }
        )


def test_create_policy_restores_deleted_policy():
    group = create_group()
    team = create_team(group)

    original = policy_service.create_policy(
        {
            "team_id": team.id,
            "name": "Production notifications",
        }
    )

    policy_service.delete_policy(original.id)

    restored = policy_service.create_policy(
        {
            "team_id": team.id,
            "name": "Production notifications",
            "description": "Restored policy.",
        }
    )

    assert restored.id == original.id
    assert restored.deleted is False
    assert restored.enabled is True
    assert restored.description == "Restored policy."


def test_enabled_rule_requires_channel():
    group = create_group()
    team = create_team(group)

    policy = policy_service.create_policy(
        {
            "team_id": team.id,
            "name": "Production notifications",
        }
    )

    with pytest.raises(
        policy_service.NotificationPolicyError,
        match="requires at least one channel",
    ):
        policy_service.create_rule(
            policy.id,
            {
                "name": "Default rule",
                "event_types": ["notification"],
                "channel_ids": [],
                "enabled": True,
            },
        )


def test_rule_rejects_channel_from_another_team():
    group = create_group()

    first_team = create_team(group)
    second_team = create_team(group)

    foreign_channel = create_channel(
        group,
        second_team,
    )

    policy = policy_service.create_policy(
        {
            "team_id": first_team.id,
            "name": "Production notifications",
        }
    )

    with pytest.raises(
        policy_service.NotificationPolicyError,
        match="belongs to another team",
    ):
        policy_service.create_rule(
            policy.id,
            {
                "name": "Invalid channel",
                "event_types": ["notification"],
                "channel_ids": [foreign_channel.id],
            },
        )


def test_create_rule_inserts_requested_position():
    group = create_group()
    team = create_team(group)

    channel = create_channel(group, team)

    policy = policy_service.create_policy(
        {
            "team_id": team.id,
            "name": "Production notifications",
        }
    )

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
            "position": 1,
            "channel_ids": [channel.id],
        },
    )

    rules = (
        notification_policies_repo
        .list_policy_rules(policy.id)
    )

    assert [rule.id for rule in rules] == [
        second.id,
        first.id,
    ]

    assert [rule.position for rule in rules] == [1, 2]


def test_update_rule_moves_position():
    group = create_group()
    team = create_team(group)

    channel = create_channel(group, team)

    policy = policy_service.create_policy(
        {
            "team_id": team.id,
            "name": "Production notifications",
        }
    )

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

    policy_service.update_rule(
        second.id,
        {
            "position": 1,
        },
    )

    rules = (
        notification_policies_repo
        .list_policy_rules(policy.id)
    )

    assert [rule.id for rule in rules] == [
        second.id,
        first.id,
    ]

    assert [rule.position for rule in rules] == [1, 2]


def test_delete_rule_normalizes_positions():
    group = create_group()
    team = create_team(group)

    channel = create_channel(group, team)

    policy = policy_service.create_policy(
        {
            "team_id": team.id,
            "name": "Production notifications",
        }
    )

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

    policy_service.delete_rule(first.id)

    rules = (
        notification_policies_repo
        .list_policy_rules(policy.id)
    )

    assert len(rules) == 1
    assert rules[0].id == second.id
    assert rules[0].position == 1


def test_delete_policy_rejects_policy_used_by_service():
    group = create_group()
    team = create_team(group)

    policy = policy_service.create_policy(
        {
            "team_id": team.id,
            "name": "Production notifications",
        }
    )

    service = create_service(team)
    service.notification_policy = policy
    service.save()

    with pytest.raises(
        policy_service.NotificationPolicyInUseError,
        match="assigned to 1 service",
    ):
        policy_service.delete_policy(policy.id)
