from app.services.routing.matcher.match_context import alert_rule_matches, build_alert_match_context
from tests.factories import create_group, create_route, create_service, create_team, create_matcher_preset


class Rule:
    def __init__(self, matchers):
        self.matchers = matchers


def test_build_match_context_from_dictionary():
    alert_data = {
        "source": "alertmanager",
        "title": "Disk full",
        "message": "Filesystem is almost full",
        "severity": "critical",
        "status": "firing",
        "labels": {
            "environment": "production",
        },
        "payload": {
            "annotations": {
                "summary": "Disk usage is high",
            },
        },
    }

    context = build_alert_match_context(alert_data)

    assert context["source"] == "alertmanager"
    assert context["severity"] == "critical"
    assert context["labels"]["environment"] == "production"
    assert context["labels"]["severity"] == "critical"
    assert context["annotations"]["summary"] == "Disk usage is high"


def test_build_match_context_from_alert_group():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    route = create_route(team, service=service)

    alert_group = type(
        "AlertGroupContext",
        (),
        {
            "id": 10,
            "team": team,
            "team_id": team.id,
            "route": route,
            "route_id": route.id,
            "service": service,
            "service_id": service.id,
            "source": "alertmanager",
            "title": "Disk full",
            "message": "Filesystem is almost full",
            "severity": "critical",
            "status": "firing",
            "labels": {
                "environment": "production",
            },
            "payload_summary": {},
        },
    )()

    context = build_alert_match_context(alert_group, priority="p1")

    assert context["priority"] == "p1"
    assert context["labels"]["priority"] == "p1"
    assert context["team"]["slug"] == team.slug
    assert context["route"]["id"] == route.id
    assert context["service"]["environment"] == service.environment


def test_shared_rule_matcher_uses_service_fields():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    service.environment = "production"
    service.criticality = "critical"
    service.save()

    rule = Rule({
        "severity": "critical",
        "fields": {
            "service.environment": "production",
            "service.criticality": "critical",
        },
    })

    alert_data = {
        "severity": "critical",
        "labels": {},
        "payload": {},
    }

    assert alert_rule_matches(
        alert_data,
        rule,
        team=team,
        service=service,
    )


def test_shared_rule_matcher_supports_priority_for_notifications():
    rule = Rule({
        "priority": ["p1", "p2"],
    })

    alert_data = {
        "severity": "warning",
        "labels": {},
        "payload": {},
    }

    assert alert_rule_matches(alert_data, rule, priority="p1")
    assert not alert_rule_matches(alert_data, rule, priority="p3")


def test_rule_requires_preset_and_local_matchers():
    group = create_group()
    team = create_team(group)

    preset = create_matcher_preset(
        team,
        matchers={
            "labels": {
                "environment": "production",
            },
        },
    )

    rule = type(
        "PresetRule",
        (),
        {
            "matcher_preset_id": preset.id,
            "matcher_preset": preset,
            "matchers": {"severity": "critical"},
        },
    )()

    assert alert_rule_matches(
        {
            "severity": "critical",
            "labels": {"environment": "production"},
        },
        rule,
        team=team,
    )

    assert not alert_rule_matches(
        {
            "severity": "warning",
            "labels": {"environment": "production"},
        },
        rule,
        team=team,
    )

    assert not alert_rule_matches(
        {
            "severity": "critical",
            "labels": {"environment": "staging"},
        },
        rule,
        team=team,
    )


def test_disabled_matcher_preset_does_not_match():
    group = create_group()
    team = create_team(group)
    preset = create_matcher_preset(team, enabled=False)

    rule = type(
        "PresetRule",
        (),
        {
            "matcher_preset_id": preset.id,
            "matcher_preset": preset,
            "matchers": {},
        },
    )()

    assert not alert_rule_matches(
        {"severity": "critical", "labels": {}},
        rule,
        team=team,
    )
