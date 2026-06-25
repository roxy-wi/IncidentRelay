from app.modules.db.models import ServiceMatchRule
from app.services.routing.routing import find_route_for_alert
from app.services.routing.service_resolution import resolve_alert_service
from tests.factories import (
    create_group,
    create_matcher_preset,
    create_route,
    create_service,
    create_team,
    unique,
)


def route_payload(team, *, name=None, matcher_preset_id=None, matchers=None):
    return {
        "team_id": team.id,
        "name": name or unique("route"),
        "source": "alertmanager",
        "rotation_id": None,
        "escalation_policy_id": None,
        "channel_ids": [],
        "matcher_preset_id": matcher_preset_id,
        "matchers": matchers or {},
        "group_by": [],
        "enabled": True,
    }


def test_create_route_with_matcher_preset(client, admin_headers, db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    preset = create_matcher_preset(
        team,
        matchers={"labels": {"environment": "production"}},
    )

    response = client.post(
        "/api/routes",
        json=route_payload(
            team,
            matcher_preset_id=preset.id,
            matchers={"labels": {"role": "compute"}},
        ),
        headers=admin_headers,
    )

    assert response.status_code == 201, response.get_json()

    payload = response.get_json()

    assert payload["matcher_preset_id"] == preset.id
    assert payload["matcher_preset"]["name"] == preset.name


def test_route_rejects_matcher_preset_from_another_team(client, admin_headers, db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    other_team = create_team(group, slug=unique("other-team"))
    preset = create_matcher_preset(other_team)

    response = client.post(
        "/api/routes",
        json=route_payload(team, matcher_preset_id=preset.id),
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "matcher_preset_invalid"


def test_route_matches_preset_and_local_matchers(db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    preset = create_matcher_preset(
        team,
        matchers={"labels": {"environment": "production"}},
    )
    route = create_route(
        team,
        matcher_preset=preset,
        matchers={"labels": {"role": "compute"}},
    )

    matched = find_route_for_alert({
        "source": "alertmanager",
        "team_slug": team.slug,
        "title": "NodeDown",
        "labels": {
            "environment": "production",
            "role": "compute",
        },
    })

    not_matched = find_route_for_alert({
        "source": "alertmanager",
        "team_slug": team.slug,
        "title": "NodeDown",
        "labels": {
            "environment": "staging",
            "role": "compute",
        },
    })

    assert matched == route
    assert not_matched is None


def test_create_service_match_rule_with_matcher_preset_only(
    client,
    admin_headers,
    db,
):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    service = create_service(team)
    route = create_route(team)
    preset = create_matcher_preset(
        team,
        matchers={"labels": {"role": "compute"}},
    )

    response = client.post(
        f"/api/services/{service.id}/match-rules",
        json={
            "team_id": team.id,
            "route_id": route.id,
            "service_id": service.id,
            "name": "Compute nodes",
            "position": 10,
            "matcher_preset_id": preset.id,
            "matchers": {},
            "enabled": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 201, response.get_json()

    payload = response.get_json()

    assert payload["matcher_preset_id"] == preset.id
    assert payload["matcher_preset"]["name"] == preset.name


def test_service_match_rule_matches_preset_and_local_matchers(db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    route = create_route(team)
    service = create_service(team)
    preset = create_matcher_preset(
        team,
        matchers={"labels": {"environment": "production"}},
    )

    ServiceMatchRule.create(
        team=team,
        route=route,
        service=service,
        name="Critical compute",
        position=10,
        matcher_preset=preset,
        matchers={"severity": "critical"},
        enabled=True,
    )

    matched = resolve_alert_service(
        route,
        {
            "source": "alertmanager",
            "severity": "critical",
            "labels": {"environment": "production"},
        },
    )

    not_matched = resolve_alert_service(
        route,
        {
            "source": "alertmanager",
            "severity": "critical",
            "labels": {"environment": "staging"},
        },
    )

    assert matched == service
    assert not_matched is None


def test_matcher_preset_used_by_route_cannot_be_deleted(
    client,
    admin_headers,
    db,
):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    preset = create_matcher_preset(team)

    create_route(team, matcher_preset=preset)

    response = client.delete(
        f"/api/matcher-presets/{preset.id}",
        headers=admin_headers,
    )

    assert response.status_code == 409
    assert response.get_json()["error"] == "matcher_preset_in_use"
