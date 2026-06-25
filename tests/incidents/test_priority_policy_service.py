import pytest

from app.modules.db import incidents_repo, priority_policies_repo
from app.services.incidents.priority_policies import service
from tests.factories import (
    create_group,
    create_priority_policy,
    create_service,
    create_team,
)


def test_create_default_priority_policy():
    group = create_group()
    team = create_team(group)

    policy = service.create_policy({
        "team_id": team.id,
        "name": "Production priorities",
        "default_for_team": True,
    })

    assert policy.team_id == team.id
    assert policy.enabled is True
    assert policy.default_for_team is True


def test_only_one_default_policy_per_team():
    group = create_group()
    team = create_team(group)

    first = service.create_policy({
        "team_id": team.id,
        "name": "First policy",
        "default_for_team": True,
    })

    second = service.create_policy({
        "team_id": team.id,
        "name": "Second policy",
        "default_for_team": True,
    })

    first = priority_policies_repo.get_priority_policy(first.id)

    assert first.default_for_team is False
    assert second.default_for_team is True


def test_disabled_policy_cannot_be_team_default():
    group = create_group()
    team = create_team(group)

    with pytest.raises(
        service.PriorityPolicyError,
        match="must be enabled",
    ):
        service.create_policy({
            "team_id": team.id,
            "name": "Disabled default",
            "enabled": False,
            "default_for_team": True,
        })


def test_disabling_default_policy_clears_default_flag():
    group = create_group()
    team = create_team(group)

    policy = service.create_policy({
        "team_id": team.id,
        "name": "Production priorities",
        "default_for_team": True,
    })

    updated = service.update_policy(policy.id, {"enabled": False})

    assert updated.enabled is False
    assert updated.default_for_team is False


def test_create_policy_restores_deleted_policy():
    group = create_group()
    team = create_team(group)

    policy = service.create_policy({
        "team_id": team.id,
        "name": "Production priorities",
    })

    service.delete_policy(policy.id)

    restored = service.create_policy({
        "team_id": team.id,
        "name": "Production priorities",
        "description": "Restored policy",
    })

    assert restored.id == policy.id
    assert restored.deleted is False
    assert restored.description == "Restored policy"


def test_fixed_fallback_requires_priority():
    group = create_group()
    team = create_team(group)

    with pytest.raises(
        service.PriorityPolicyError,
        match="requires fallback_priority_id",
    ):
        service.create_policy({
            "team_id": team.id,
            "name": "Fixed fallback",
            "fallback_mode": "fixed_priority",
        })


def test_fixed_fallback_uses_enabled_priority():
    group = create_group()
    team = create_team(group)
    priority = incidents_repo.get_priority_by_slug("p2")

    policy = service.create_policy({
        "team_id": team.id,
        "name": "Fixed fallback",
        "fallback_mode": "fixed_priority",
        "fallback_priority_id": priority.id,
    })

    assert policy.fallback_priority_id == priority.id


def test_service_policy_override_wins_over_team_default():
    group = create_group()
    team = create_team(group)
    incident_service = create_service(team)

    team_policy = create_priority_policy(
        team,
        default_for_team=True,
    )
    service_policy = create_priority_policy(team)

    incident_service.priority_policy = service_policy
    incident_service.save()

    effective = service.get_effective_policy(
        team_id=team.id,
        service=incident_service,
    )

    assert effective.id == service_policy.id
    assert effective.id != team_policy.id


def test_team_default_is_used_without_service_override():
    group = create_group()
    team = create_team(group)
    incident_service = create_service(team)

    policy = create_priority_policy(
        team,
        default_for_team=True,
    )

    effective = service.get_effective_policy(
        team_id=team.id,
        service=incident_service,
    )

    assert effective.id == policy.id


def test_policy_assignment_rejects_another_team():
    group = create_group()
    first_team = create_team(group)
    second_team = create_team(group)
    policy = create_priority_policy(second_team)

    with pytest.raises(
        service.PriorityPolicyError,
        match="belongs to another team",
    ):
        service.validate_policy_assignment(
            policy.id,
            team_id=first_team.id,
        )


def test_delete_policy_rejects_policy_used_by_service():
    group = create_group()
    team = create_team(group)
    policy = create_priority_policy(team)
    incident_service = create_service(team)

    incident_service.priority_policy = policy
    incident_service.save()

    with pytest.raises(
        service.PriorityPolicyInUseError,
        match="assigned to 1 service",
    ):
        service.delete_policy(policy.id)


def test_create_rule_inserts_requested_position():
    group = create_group()
    team = create_team(group)
    p1 = incidents_repo.get_priority_by_slug("p1")
    p2 = incidents_repo.get_priority_by_slug("p2")

    policy = create_priority_policy(team)

    first = service.create_rule(
        policy.id,
        {
            "name": "First",
            "priority_id": p2.id,
        },
    )

    second = service.create_rule(
        policy.id,
        {
            "name": "Second",
            "priority_id": p1.id,
            "position": 1,
        },
    )

    rules = priority_policies_repo.list_priority_policy_rules(policy.id)

    assert [rule.id for rule in rules] == [second.id, first.id]
    assert [rule.position for rule in rules] == [1, 2]


def test_update_rule_moves_position():
    group = create_group()
    team = create_team(group)
    priority = incidents_repo.get_priority_by_slug("p2")
    policy = create_priority_policy(team)

    first = service.create_rule(
        policy.id,
        {
            "name": "First",
            "priority_id": priority.id,
        },
    )

    second = service.create_rule(
        policy.id,
        {
            "name": "Second",
            "priority_id": priority.id,
        },
    )

    service.update_rule(second.id, {"position": 1})

    rules = priority_policies_repo.list_priority_policy_rules(policy.id)

    assert [rule.id for rule in rules] == [second.id, first.id]
    assert [rule.position for rule in rules] == [1, 2]


def test_delete_rule_normalizes_positions():
    group = create_group()
    team = create_team(group)
    priority = incidents_repo.get_priority_by_slug("p2")
    policy = create_priority_policy(team)

    first = service.create_rule(
        policy.id,
        {
            "name": "First",
            "priority_id": priority.id,
        },
    )

    second = service.create_rule(
        policy.id,
        {
            "name": "Second",
            "priority_id": priority.id,
        },
    )

    service.delete_rule(first.id)

    rules = priority_policies_repo.list_priority_policy_rules(policy.id)

    assert len(rules) == 1
    assert rules[0].id == second.id
    assert rules[0].position == 1
