from tests.factories import create_alert, create_group, create_route, create_team, unique


def test_matcher_suggestions_returns_recent_label_values(client, admin_headers, db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    route = create_route(team, source="alertmanager")

    first = create_alert(route)
    first.labels = {
        "alertname": "DiskFull",
        "instance": "host1",
        "environment": "production",
    }
    first.severity = "critical"
    first.priority_slug = "p1"
    first.save()

    second = create_alert(route)
    second.labels = {
        "alertname": "DiskFull",
        "instance": "host2",
        "environment": "production",
    }
    second.severity = "warning"
    second.priority_slug = "p3"
    second.save()

    response = client.get(
        f"/api/matchers/suggestions?team_id={team.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()

    assert payload["team_id"] == team.id
    assert payload["sample_size"] == 2
    assert payload["labels"]["alertname"] == ["DiskFull"]
    assert payload["labels"]["environment"] == ["production"]
    assert set(payload["labels"]["instance"]) == {"host1", "host2"}
    assert set(payload["labels"]["severity"]) == {"critical", "warning"}
    assert set(payload["labels"]["priority"]) == {"p1", "p3"}
    assert payload["fields"]["source"] == ["alertmanager"]


def test_matcher_suggestions_does_not_include_other_teams(client, admin_headers, db):
    first_group = create_group(slug=unique("group"))
    first_team = create_team(first_group, slug=unique("team"))
    first_route = create_route(first_team, source="alertmanager")

    second_group = create_group(slug=unique("group"))
    second_team = create_team(second_group, slug=unique("team"))
    second_route = create_route(second_team, source="zabbix")

    first_alert = create_alert(first_route)
    first_alert.labels = {"environment": "production"}
    first_alert.save()

    second_alert = create_alert(second_route)
    second_alert.labels = {"environment": "development", "secret_label": "hidden"}
    second_alert.save()

    response = client.get(
        f"/api/matchers/suggestions?team_id={first_team.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()

    assert payload["labels"]["environment"] == ["production"]
    assert "secret_label" not in payload["labels"]
    assert payload["fields"]["source"] == ["alertmanager"]


def test_matcher_suggestions_requires_team_id(client, admin_headers, db):
    response = client.get(
        "/api/matchers/suggestions",
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "team_id is required"
