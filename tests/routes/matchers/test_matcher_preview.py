from tests.factories import (
    create_alert,
    create_group,
    create_matcher_preset,
    create_route,
    create_team,
    unique,
)


def test_matcher_preview_returns_matching_recent_alerts(client, admin_headers, db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    route = create_route(team, source="alertmanager")

    first = create_alert(route)
    first.labels = {
        "alertname": "DiskFull",
        "instance": "host1",
        "environment": "production",
    }
    first.save()

    second = create_alert(route)
    second.labels = {
        "alertname": "DiskFull",
        "instance": "host2",
        "environment": "production",
    }
    second.save()

    response = client.post(
        "/api/matchers/preview",
        headers=admin_headers,
        json={
            "team_id": team.id,
            "matchers": {
                "instance": "host1",
            },
        },
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()

    assert payload["sample_size"] == 2
    assert payload["matched_count"] == 1
    assert payload["truncated"] is False
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == first.id
    assert payload["items"][0]["labels"]["instance"] == "host1"


def test_matcher_preview_combines_preset_and_local_matchers(client, admin_headers, db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    route = create_route(team, source="alertmanager")
    preset = create_matcher_preset(
        team,
        matchers={
            "environment": "production",
        },
    )

    critical = create_alert(route)
    critical.labels = {
        "alertname": "DiskFull",
        "environment": "production",
    }
    critical.severity = "critical"
    critical.save()

    warning = create_alert(route)
    warning.labels = {
        "alertname": "DiskFull",
        "environment": "production",
    }
    warning.severity = "warning"
    warning.save()

    response = client.post(
        "/api/matchers/preview",
        headers=admin_headers,
        json={
            "team_id": team.id,
            "matcher_preset_id": preset.id,
            "matchers": {
                "severity": "critical",
            },
        },
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()

    assert payload["matcher_preset_id"] == preset.id
    assert payload["matched_count"] == 1
    assert payload["items"][0]["id"] == critical.id


def test_matcher_preview_does_not_include_other_teams(client, admin_headers, db):
    first_group = create_group(slug=unique("group"))
    first_team = create_team(first_group, slug=unique("team"))
    first_route = create_route(first_team, source="alertmanager")

    second_group = create_group(slug=unique("group"))
    second_team = create_team(second_group, slug=unique("team"))
    second_route = create_route(second_team, source="alertmanager")

    first_alert = create_alert(first_route)
    first_alert.labels = {"environment": "production"}
    first_alert.save()

    second_alert = create_alert(second_route)
    second_alert.labels = {"environment": "production"}
    second_alert.save()

    response = client.post(
        "/api/matchers/preview",
        headers=admin_headers,
        json={
            "team_id": first_team.id,
            "matchers": {
                "environment": "production",
            },
        },
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()

    assert payload["matched_count"] == 1
    assert payload["items"][0]["id"] == first_alert.id


def test_matcher_preview_rejects_invalid_regex(client, admin_headers, db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    route = create_route(team, source="alertmanager")

    create_alert(route)

    response = client.post(
        "/api/matchers/preview",
        headers=admin_headers,
        json={
            "team_id": team.id,
            "matchers": {
                "instance": {
                    "regex": "[",
                },
            },
        },
    )

    assert response.status_code == 400

    payload = response.get_json()

    assert payload["error"] == "validation_error"
    assert payload["message"] == "Matchers are invalid."


def test_matcher_preview_requires_team_id(client, admin_headers, db):
    response = client.post(
        "/api/matchers/preview",
        headers=admin_headers,
        json={
            "matchers": {},
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"
