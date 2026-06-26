from app.modules.db.models import ServiceRunbook
from app.services.routing.service_context import get_alert_service_runbooks
from tests.factories import (
    create_group,
    create_matcher_preset,
    create_route,
    create_service,
    create_team,
    unique,
)
from tests.services.test_service_notification_context import (
    create_alert_for_service,
)


def test_create_service_runbook_with_matcher_preset(
    client,
    admin_headers,
    db,
):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    service = create_service(team)
    preset = create_matcher_preset(
        team,
        matchers={"labels": {"environment": "production"}},
    )

    response = client.post(
        f"/api/services/{service.id}/runbooks",
        headers=admin_headers,
        json={
            "title": "Production compute outage",
            "url": "https://docs.example.com/runbooks/compute",
            "severity": "critical",
            "matcher_preset_id": preset.id,
            "matchers": {"labels": {"role": "compute"}},
            "priority": 10,
            "enabled": True,
        },
    )

    assert response.status_code == 201, response.get_json()

    payload = response.get_json()

    assert payload["matcher_preset_id"] == preset.id
    assert payload["matcher_preset"]["name"] == preset.name
    assert payload["matcher_preset"]["matchers"] == {
        "labels": {"environment": "production"}
    }


def test_service_runbook_rejects_preset_from_another_team(
    client,
    admin_headers,
    db,
):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    other_team = create_team(group, slug=unique("other-team"))
    service = create_service(team)
    preset = create_matcher_preset(other_team)

    response = client.post(
        f"/api/services/{service.id}/runbooks",
        headers=admin_headers,
        json={
            "title": "Invalid preset",
            "url": "https://docs.example.com/runbooks/invalid",
            "matcher_preset_id": preset.id,
            "matchers": {},
            "priority": 10,
            "enabled": True,
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "matcher_preset_invalid"


def test_service_runbook_matches_preset_and_local_matchers(db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    service = create_service(team)
    route = create_route(team, service=service)
    preset = create_matcher_preset(
        team,
        matchers={"labels": {"environment": "production"}},
    )

    ServiceRunbook.create(
        service=service,
        title="Compute outage",
        url="https://docs.example.com/runbooks/compute",
        matcher_preset=preset,
        matchers={"labels": {"role": "compute"}},
        priority=10,
        enabled=True,
    )

    alert = create_alert_for_service(team, route, service)
    alert.labels = {
        "alertname": "NodeDown",
        "severity": "critical",
        "environment": "production",
        "role": "compute",
    }
    alert.save()

    matched = get_alert_service_runbooks(alert)

    assert [runbook.title for runbook in matched] == ["Compute outage"]

    alert.labels["environment"] = "staging"
    alert.save()

    assert get_alert_service_runbooks(alert) == []


def test_disabled_runbook_matcher_preset_does_not_match(db):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    service = create_service(team)
    route = create_route(team, service=service)
    preset = create_matcher_preset(
        team,
        matchers={"labels": {"role": "compute"}},
        enabled=False,
    )

    ServiceRunbook.create(
        service=service,
        title="Compute outage",
        url="https://docs.example.com/runbooks/compute",
        matcher_preset=preset,
        matchers={},
        priority=10,
        enabled=True,
    )

    alert = create_alert_for_service(team, route, service)
    alert.labels["role"] = "compute"
    alert.save()

    assert get_alert_service_runbooks(alert) == []


def test_matcher_preset_used_by_runbook_cannot_be_deleted(
    client,
    admin_headers,
    db,
):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"))
    service = create_service(team)
    preset = create_matcher_preset(team)

    ServiceRunbook.create(
        service=service,
        title="Generic runbook",
        url="https://docs.example.com/runbooks/generic",
        matcher_preset=preset,
        matchers={},
        priority=10,
        enabled=True,
    )

    response = client.delete(
        f"/api/matcher-presets/{preset.id}",
        headers=admin_headers,
    )

    assert response.status_code == 409
    assert response.get_json()["error"] == "matcher_preset_in_use"
