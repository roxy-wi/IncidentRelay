from app.modules.db import incidents_repo
from app.services.incidents.priority_policies.resolver import (
    resolve_incident_priority,
)
from tests.factories import (
    create_group,
    create_priority_policy,
    create_priority_policy_rule,
    create_service,
    create_team,
)


def _alert_data(**overrides):
    data = {
        "source": "alertmanager",
        "title": "Payment API errors",
        "message": "Error rate is above threshold",
        "severity": "warning",
        "status": "firing",
        "labels": {
            "alertname": "PaymentApiErrors",
            "environment": "production",
        },
        "payload": {},
    }
    data.update(overrides)
    return data


def test_resolver_uses_severity_mapping_without_policy():
    group = create_group()
    team = create_team(group)

    resolution = resolve_incident_priority(
        _alert_data(severity="critical"),
        team=team,
    )

    assert resolution.priority.slug == "p1"
    assert resolution.source == "severity_mapping"
    assert resolution.policy_id is None
    assert resolution.update_mode == "raise_only"


def test_team_default_policy_rule_matches_service_fields():
    group = create_group()
    team = create_team(group)
    incident_service = create_service(team)

    incident_service.environment = "production"
    incident_service.criticality = "critical"
    incident_service.save()

    p1 = incidents_repo.get_priority_by_slug("p1")
    policy = create_priority_policy(team, default_for_team=True)

    rule = create_priority_policy_rule(
        policy,
        p1,
        matchers={
            "severity": "critical",
            "fields": {
                "service.environment": "production",
                "service.criticality": "critical",
            },
        },
    )

    resolution = resolve_incident_priority(
        _alert_data(severity="critical"),
        team=team,
        service=incident_service,
    )

    assert resolution.priority.slug == "p1"
    assert resolution.source == "policy_rule"
    assert resolution.policy_id == policy.id
    assert resolution.rule_id == rule.id


def test_first_matching_rule_wins():
    group = create_group()
    team = create_team(group)

    p1 = incidents_repo.get_priority_by_slug("p1")
    p2 = incidents_repo.get_priority_by_slug("p2")

    policy = create_priority_policy(team, default_for_team=True)

    first = create_priority_policy_rule(
        policy,
        p2,
        position=1,
        matchers={"severity": "critical"},
    )

    create_priority_policy_rule(
        policy,
        p1,
        position=2,
        matchers={"severity": "critical"},
    )

    resolution = resolve_incident_priority(
        _alert_data(severity="critical"),
        team=team,
    )

    assert resolution.priority.slug == "p2"
    assert resolution.rule_id == first.id


def test_service_policy_overrides_team_default():
    group = create_group()
    team = create_team(group)
    incident_service = create_service(team)

    p1 = incidents_repo.get_priority_by_slug("p1")
    p3 = incidents_repo.get_priority_by_slug("p3")

    team_policy = create_priority_policy(team, default_for_team=True)
    create_priority_policy_rule(team_policy, p1, matchers={})

    service_policy = create_priority_policy(team)
    service_rule = create_priority_policy_rule(
        service_policy,
        p3,
        matchers={},
    )

    incident_service.priority_policy = service_policy
    incident_service.save()

    resolution = resolve_incident_priority(
        _alert_data(severity="critical"),
        team=team,
        service=incident_service,
    )

    assert resolution.priority.slug == "p3"
    assert resolution.policy_id == service_policy.id
    assert resolution.rule_id == service_rule.id


def test_preferred_source_priority_wins_over_policy_rule():
    group = create_group()
    team = create_team(group)

    p3 = incidents_repo.get_priority_by_slug("p3")

    policy = create_priority_policy(
        team,
        default_for_team=True,
        source_priority_mode="prefer",
    )
    create_priority_policy_rule(policy, p3, matchers={})

    alert_data = _alert_data(
        severity="warning",
        priority="p1",
    )

    resolution = resolve_incident_priority(alert_data, team=team)

    assert resolution.priority.slug == "p1"
    assert resolution.source == "source_priority"
    assert resolution.rule_id is None
    assert resolution.source_priority_value == "p1"


def test_source_priority_can_be_read_from_labels():
    group = create_group()
    team = create_team(group)

    create_priority_policy(
        team,
        default_for_team=True,
        source_priority_mode="prefer",
    )

    alert_data = _alert_data(
        labels={
            "alertname": "PaymentApiErrors",
            "priority": "p2",
        }
    )

    resolution = resolve_incident_priority(alert_data, team=team)

    assert resolution.priority.slug == "p2"
    assert resolution.source == "source_priority"


def test_ignored_source_priority_does_not_override_rule():
    group = create_group()
    team = create_team(group)

    p3 = incidents_repo.get_priority_by_slug("p3")

    policy = create_priority_policy(
        team,
        default_for_team=True,
        source_priority_mode="ignore",
    )
    rule = create_priority_policy_rule(policy, p3, matchers={})

    resolution = resolve_incident_priority(
        _alert_data(priority="p1"),
        team=team,
    )

    assert resolution.priority.slug == "p3"
    assert resolution.source == "policy_rule"
    assert resolution.rule_id == rule.id


def test_invalid_source_priority_falls_through_to_rule():
    group = create_group()
    team = create_team(group)

    p2 = incidents_repo.get_priority_by_slug("p2")

    policy = create_priority_policy(
        team,
        default_for_team=True,
        source_priority_mode="prefer",
    )
    rule = create_priority_policy_rule(policy, p2, matchers={})

    resolution = resolve_incident_priority(
        _alert_data(priority="urgent"),
        team=team,
    )

    assert resolution.priority.slug == "p2"
    assert resolution.rule_id == rule.id
    assert resolution.notes == ["invalid_source_priority"]


def test_fixed_priority_fallback():
    group = create_group()
    team = create_team(group)

    p4 = incidents_repo.get_priority_by_slug("p4")

    policy = create_priority_policy(
        team,
        default_for_team=True,
        fallback_mode="fixed_priority",
        fallback_priority=p4,
    )

    resolution = resolve_incident_priority(
        _alert_data(severity="critical"),
        team=team,
    )

    assert resolution.priority.slug == "p4"
    assert resolution.source == "fixed_fallback"
    assert resolution.policy_id == policy.id


def test_severity_mapping_is_used_when_no_rule_matches():
    group = create_group()
    team = create_team(group)

    p1 = incidents_repo.get_priority_by_slug("p1")

    policy = create_priority_policy(team, default_for_team=True)
    create_priority_policy_rule(
        policy,
        p1,
        matchers={"severity": "critical"},
    )

    resolution = resolve_incident_priority(
        _alert_data(severity="warning"),
        team=team,
    )

    assert resolution.priority.slug == "p3"
    assert resolution.source == "severity_mapping"


def test_disabled_rule_is_skipped():
    group = create_group()
    team = create_team(group)

    p1 = incidents_repo.get_priority_by_slug("p1")
    p4 = incidents_repo.get_priority_by_slug("p4")

    policy = create_priority_policy(
        team,
        default_for_team=True,
        fallback_mode="fixed_priority",
        fallback_priority=p4,
    )

    create_priority_policy_rule(
        policy,
        p1,
        matchers={},
        enabled=False,
    )

    resolution = resolve_incident_priority(
        _alert_data(severity="critical"),
        team=team,
    )

    assert resolution.priority.slug == "p4"
    assert resolution.source == "fixed_fallback"


def test_policy_update_mode_is_returned():
    group = create_group()
    team = create_team(group)

    policy = create_priority_policy(
        team,
        default_for_team=True,
        update_mode="initial_only",
    )

    resolution = resolve_incident_priority(
        _alert_data(),
        team=team,
    )

    assert resolution.policy_id == policy.id
    assert resolution.update_mode == "initial_only"
    