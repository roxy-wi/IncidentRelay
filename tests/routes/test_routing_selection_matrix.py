import pytest

from app.services.routing.routing import find_route_for_alert
from tests.factories import create_group, create_route, create_team, unique


def _alert_data(**overrides):
    data = {
        "source": "alertmanager",
        "title": "DiskFull on host1",
        "message": "/var is 95% full on host1",
        "labels": {
            "alertname": "DiskFull",
            "environment": "production",
            "instance": "host1",
            "severity": "critical",
            "team": "sre",
        },
        "payload": {
            "annotations": {
                "summary": "Disk usage is high on host1",
            },
            "custom": {
                "cluster": "core",
            },
        },
        "dedup_key": unique("dedup"),
    }
    data.update(overrides)
    return data


def test_forced_route_id_matches_route_without_team_slug(db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    route = create_route(
        team,
        source="alertmanager",
        matchers={"labels": {"environment": "production"}},
    )

    alert_data = _alert_data(forced_route_id=route.id)

    assert find_route_for_alert(alert_data) == route
    assert "routing_error" not in alert_data


def test_forced_route_id_still_requires_matchers_to_match(db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    route = create_route(
        team,
        source="alertmanager",
        matchers={"labels": {"environment": "production"}},
    )

    alert_data = _alert_data(
        forced_route_id=route.id,
        labels={"environment": "staging", "alertname": "DiskFull"},
    )

    assert find_route_for_alert(alert_data) is None
    assert alert_data["routing_error"] == "alert does not match route matchers"


def test_forced_route_id_rejects_source_mismatch(db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    route = create_route(team, source="grafana")

    alert_data = _alert_data(forced_route_id=route.id, source="alertmanager")

    assert find_route_for_alert(alert_data) is None
    assert alert_data["routing_error"] == (
        "route source 'grafana' does not match alert source 'alertmanager'"
    )


def test_forced_route_id_rejects_disabled_route(db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    route = create_route(team, source="alertmanager")
    route.enabled = False
    route.save()

    alert_data = _alert_data(forced_route_id=route.id)

    assert find_route_for_alert(alert_data) is None
    assert alert_data["routing_error"] == "route from intake token is disabled or inactive"


def test_forced_team_id_limits_route_search_to_that_team(db):
    group = create_group(slug=unique("group"))
    first_team = create_team(group, slug=unique("team"))
    second_team = create_team(group, slug=unique("team"))

    first_route = create_route(
        first_team,
        source="alertmanager",
        matchers={"labels": {"environment": "production"}},
    )
    create_route(
        second_team,
        source="alertmanager",
        matchers={"labels": {"environment": "production"}},
    )

    alert_data = _alert_data(forced_team_id=first_team.id)

    assert find_route_for_alert(alert_data) == first_route
    assert "routing_error" not in alert_data


def test_forced_team_id_does_not_fall_back_to_other_matching_team(db):
    group = create_group(slug=unique("group"))
    first_team = create_team(group, slug=unique("team"))
    second_team = create_team(group, slug=unique("team"))

    create_route(
        first_team,
        source="alertmanager",
        matchers={"labels": {"environment": "staging"}},
    )
    create_route(
        second_team,
        source="alertmanager",
        matchers={"labels": {"environment": "production"}},
    )

    alert_data = _alert_data(forced_team_id=first_team.id)

    assert find_route_for_alert(alert_data) is None
    assert alert_data["routing_error"] == "no enabled route matched alert labels"


@pytest.mark.parametrize(
    ("matchers", "labels", "expected"),
    [
        (
            {"labels": {"instance": {"regex": r"^host-[0-9]+$"}}},
            {"instance": "host-42"},
            True,
        ),
        (
            {"labels": {"instance": {"regex": r"^host-[0-9]+$"}}},
            {"instance": "db-primary"},
            False,
        ),
        (
            {"labels": {"alertname": {"contains": "Disk"}}},
            {"alertname": "DiskFull"},
            True,
        ),
        (
            {"labels": {"environment": {"not": "staging"}}},
            {"environment": "production"},
            True,
        ),
        (
            {"labels": {"environment": {"not": "production"}}},
            {"environment": "production"},
            False,
        ),
        (
            {"labels": {"severity": ["critical", "warning"]}},
            {"severity": "critical"},
            True,
        ),
        (
            {"labels": {"severity": ["critical", "warning"]}},
            {"severity": "info"},
            False,
        ),
    ],
)
def test_find_route_for_alert_applies_matcher_operators(db, matchers, labels, expected):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    route = create_route(team, source="alertmanager", matchers=matchers)

    alert_labels = {"alertname": "DiskFull", "environment": "production"}
    alert_labels.update(labels)
    alert_data = _alert_data(team_slug=team.slug, labels=alert_labels)

    if expected:
        assert find_route_for_alert(alert_data) == route
        assert "routing_error" not in alert_data
    else:
        assert find_route_for_alert(alert_data) is None
        assert alert_data["routing_error"] == "no enabled route matched alert labels"


def test_find_route_for_alert_applies_title_regex_and_payload_field_matchers(db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    route = create_route(
        team,
        source="alertmanager",
        matchers={
            "title_regex": r"DiskFull .* host1",
            "fields": {
                "payload.custom.cluster": "core",
                "annotations.summary": {"contains": "Disk usage"},
            },
        },
    )

    alert_data = _alert_data(team_slug=team.slug)

    assert find_route_for_alert(alert_data) == route
    assert "routing_error" not in alert_data


def test_find_route_for_alert_uses_first_matching_route_by_id(db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))

    first_route = create_route(
        team,
        source="alertmanager",
        matchers={"labels": {"environment": "production"}},
    )
    create_route(
        team,
        source="alertmanager",
        matchers={"labels": {"environment": "production"}},
    )

    alert_data = _alert_data(team_slug=team.slug)

    assert find_route_for_alert(alert_data) == first_route
