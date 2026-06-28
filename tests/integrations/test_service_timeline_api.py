from app.modules.db.models import ServiceEvent
from tests.factories import create_group, create_service, create_team


def test_service_timeline_returns_events(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    ServiceEvent.create(
        service=service,
        group=group,
        team=team,
        category="configuration",
        event_type="service.updated",
        title="Service updated",
        summary="Description changed",
        source="test",
        actor_type="system",
        payload={"field": "description"},
    )

    response = client.get(
        f"/api/services/{service.id}/timeline",
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()
    assert payload["next_cursor"] is None
    assert len(payload["items"]) == 1
    assert payload["items"][0]["event_type"] == "service.updated"
    assert payload["items"][0]["title"] == "Service updated"
    assert payload["items"][0]["payload"] == {"field": "description"}


def test_service_timeline_supports_category_filter(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    ServiceEvent.create(
        service=service,
        group=group,
        team=team,
        category="configuration",
        event_type="service.updated",
        title="Service updated",
    )
    ServiceEvent.create(
        service=service,
        group=group,
        team=team,
        category="status",
        event_type="service.status_changed",
        title="Service status changed",
    )

    response = client.get(
        f"/api/services/{service.id}/timeline?category=status",
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()
    assert [item["event_type"] for item in payload["items"]] == [
        "service.status_changed",
    ]


def test_service_timeline_returns_404_for_missing_service(client, admin_headers):
    response = client.get(
        "/api/services/999999/timeline",
        headers=admin_headers,
    )

    assert response.status_code == 404
    assert response.get_json()["error"] == "service_not_found"


def test_service_timeline_rejects_invalid_cursor_datetime(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    response = client.get(
        f"/api/services/{service.id}/timeline?before=not-a-date",
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "timeline_before_invalid"
