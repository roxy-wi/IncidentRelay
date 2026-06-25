import pytest

from app.services.routing.matcher import service
from tests.factories import (
    create_group,
    create_matcher_preset,
    create_notification_policy,
    create_notification_policy_rule,
    create_team,
)


def test_create_matcher_preset():
    group = create_group()
    team = create_team(group)

    preset = service.create_preset({
        "team_id": team.id,
        "name": "Production services",
        "matchers": {
            "fields": {
                "service.environment": "production",
            },
        },
    })

    assert preset.team_id == team.id
    assert preset.version == 1
    assert preset.enabled is True


def test_duplicate_matcher_preset_name_is_rejected():
    group = create_group()
    team = create_team(group)

    service.create_preset({
        "team_id": team.id,
        "name": "Production services",
    })

    with pytest.raises(service.MatcherPresetConflictError, match="already exists"):
        service.create_preset({
            "team_id": team.id,
            "name": "Production services",
        })


def test_matcher_preset_update_increments_version():
    group = create_group()
    team = create_team(group)
    preset = create_matcher_preset(team)

    updated = service.update_preset(
        preset.id,
        {"matchers": {"severity": "critical"}},
    )

    assert updated.version == 2
    assert updated.matchers == {"severity": "critical"}


def test_unchanged_matcher_preset_does_not_increment_version():
    group = create_group()
    team = create_team(group)

    preset = create_matcher_preset(
        team,
        matchers={"severity": "critical"},
    )

    updated = service.update_preset(
        preset.id,
        {"matchers": {"severity": "critical"}},
    )

    assert updated.version == 1


def test_matcher_preset_assignment_rejects_another_team():
    group = create_group()
    first_team = create_team(group)
    second_team = create_team(group)
    preset = create_matcher_preset(second_team)

    with pytest.raises(
        service.MatcherPresetError,
        match="belongs to another team",
    ):
        service.validate_preset_assignment(
            preset.id,
            team_id=first_team.id,
        )


def test_disabled_matcher_preset_cannot_be_assigned():
    group = create_group()
    team = create_team(group)
    preset = create_matcher_preset(team, enabled=False)

    with pytest.raises(service.MatcherPresetError, match="disabled"):
        service.validate_preset_assignment(preset.id, team_id=team.id)


def test_used_matcher_preset_cannot_be_deleted():
    group = create_group()
    team = create_team(group)
    preset = create_matcher_preset(team)
    policy = create_notification_policy(team)

    create_notification_policy_rule(
        policy,
        matcher_preset=preset,
    )

    with pytest.raises(service.MatcherPresetInUseError) as exc_info:
        service.delete_preset(preset.id)

    assert str(exc_info.value) == "matcher preset is used by 1 resource(s)"
