from app.modules.db import incidents_repo
from app.modules.db.models import (
    MatcherPreset,
    NotificationPolicyRule,
    PriorityPolicyRule,
)
from tests.factories import (
    create_group,
    create_notification_policy,
    create_priority_policy,
    create_team,
)


def test_create_matcher_preset():
    group = create_group()
    team = create_team(group)

    preset = MatcherPreset.create(
        team=team,
        name="Production services",
        description="Matches production services.",
        matchers={
            "fields": {
                "service.environment": "production",
            },
        },
    )

    assert preset.team_id == team.id
    assert preset.enabled is True
    assert preset.version == 1
    assert preset.matchers == {
        "fields": {
            "service.environment": "production",
        },
    }


def test_notification_policy_rule_can_reference_matcher_preset():
    group = create_group()
    team = create_team(group)

    preset = MatcherPreset.create(
        team=team,
        name="Production services",
        matchers={"labels": {"environment": "production"}},
    )

    policy = create_notification_policy(team)

    rule = NotificationPolicyRule.create(
        policy=policy,
        name="Critical alerts",
        position=1,
        event_types=["notification"],
        matcher_preset=preset,
        matchers={"severity": "critical"},
    )

    assert rule.matcher_preset_id == preset.id


def test_priority_policy_rule_can_reference_matcher_preset():
    group = create_group()
    team = create_team(group)

    preset = MatcherPreset.create(
        team=team,
        name="Production services",
        matchers={"labels": {"environment": "production"}},
    )

    policy = create_priority_policy(team)
    priority = incidents_repo.get_priority_by_slug("p1")

    rule = PriorityPolicyRule.create(
        policy=policy,
        name="Critical production",
        position=1,
        matcher_preset=preset,
        matchers={"severity": "critical"},
        priority=priority,
    )

    assert rule.matcher_preset_id == preset.id
