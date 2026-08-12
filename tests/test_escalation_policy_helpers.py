from types import SimpleNamespace

from app.services.escalation_policies import (
    get_first_enabled_rule,
    get_rule_delay_seconds,
    resolve_rule_user,
)
from tests.factories import (
    create_escalation_policy,
    create_escalation_policy_rule,
    create_group,
    create_team,
    create_user,
    unique,
)


def test_first_enabled_rule_requires_enabled_policy(db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    policy = create_escalation_policy(team, enabled=False)
    create_escalation_policy_rule(
        policy,
        position=1,
        target_type="user",
        user=create_user(unique("user"), group),
    )

    assert get_first_enabled_rule(policy) is None


def test_first_enabled_rule_skips_disabled_rules(db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    user = create_user(unique("user"), group)
    policy = create_escalation_policy(team)
    create_escalation_policy_rule(
        policy,
        position=1,
        target_type="user",
        user=user,
        enabled=False,
    )
    expected = create_escalation_policy_rule(
        policy,
        position=2,
        target_type="user",
        user=user,
        enabled=True,
    )

    assert get_first_enabled_rule(policy).id == expected.id


def test_resolve_rule_user_rejects_disabled_rule_and_inactive_user(db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    user = create_user(unique("user"), group)
    policy = create_escalation_policy(team)
    rule = create_escalation_policy_rule(
        policy,
        target_type="user",
        user=user,
        enabled=False,
    )

    assert resolve_rule_user(rule) is None

    rule.enabled = True
    rule.save()
    user.active = False
    user.save()

    assert resolve_rule_user(rule) is None

    user.active = True
    user.save()

    assert resolve_rule_user(rule).id == user.id


def test_rule_delay_is_non_negative():
    assert get_rule_delay_seconds(None) == 0
    assert get_rule_delay_seconds(SimpleNamespace(delay_seconds=None)) == 0
    assert get_rule_delay_seconds(SimpleNamespace(delay_seconds=-30)) == 0
    assert get_rule_delay_seconds(SimpleNamespace(delay_seconds=90)) == 90
