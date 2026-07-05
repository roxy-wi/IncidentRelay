from app.login import create_access_token
from app.modules.db.models import Alert, AlertEvent, AlertGroup
from tests.factories import (
    add_user_to_team,
    create_group,
    create_service,
    create_team,
    create_user,
)


def auth_headers_for(user):
    token, _ = create_access_token(user)
    return {
        "Authorization": f"Bearer {token}",
    }


def test_group_editor_can_create_manual_incident_for_group_team(client, db):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    user = create_user(
        group=group,
        group_role="editor",
    )

    response = client.post(
        "/api/incidents",
        json={
            "team_id": team.id,
            "service_id": service.id,
            "title": "Manual storage incident",
            "message": "Created from test",
            "severity": "critical",
            "priority": "p1",
            "notify": False,
        },
        headers=auth_headers_for(user),
    )

    assert response.status_code == 201
    data = response.get_json()

    assert data["id"]
    assert data["title"] == "Manual storage incident"
    assert data["source"] == "manual"
    assert data["status"] == "firing"
    assert data["severity"] == "critical"
    assert data["priority"]["slug"] == "p1"
    assert data["priority"]["set_manually"] is True

    group_row = AlertGroup.get_by_id(data["id"])
    assert group_row.team_id == team.id
    assert group_row.service_id == service.id
    assert group_row.source == "manual"
    assert group_row.notification_pending is False

    alerts = list(Alert.select().where(Alert.group == group_row.id))
    assert len(alerts) == 1
    assert alerts[0].source == "manual"
    assert alerts[0].status == "firing"
    assert alerts[0].labels["manual"] == "true"

    events = list(AlertEvent.select().where(AlertEvent.group == group_row.id))
    assert any(event.event_type == "manual_created" for event in events)


def test_team_responder_can_create_manual_incident(client, db):
    group = create_group()
    team = create_team(group)

    user = create_user(
        group=group,
        group_role="viewer",
    )
    add_user_to_team(team, user, role="responder")

    response = client.post(
        "/api/incidents",
        json={
            "team_id": team.id,
            "title": "Manual responder incident",
            "severity": "warning",
            "notify": False,
        },
        headers=auth_headers_for(user),
    )

    assert response.status_code == 201
    data = response.get_json()

    assert data["title"] == "Manual responder incident"
    assert data["source"] == "manual"
    assert data["status"] == "firing"
    assert data["severity"] == "warning"


def test_group_viewer_cannot_create_manual_incident(client, db):
    group = create_group()
    team = create_team(group)

    user = create_user(
        group=group,
        group_role="viewer",
    )

    response = client.post(
        "/api/incidents",
        json={
            "team_id": team.id,
            "title": "Viewer incident",
            "notify": False,
        },
        headers=auth_headers_for(user),
    )

    assert response.status_code == 403


def test_group_editor_cannot_create_manual_incident_for_foreign_team(client, db):
    group = create_group()
    foreign_group = create_group()

    create_team(group)
    foreign_team = create_team(foreign_group)

    user = create_user(
        group=group,
        group_role="editor",
    )

    response = client.post(
        "/api/incidents",
        json={
            "team_id": foreign_team.id,
            "title": "Foreign team incident",
            "notify": False,
        },
        headers=auth_headers_for(user),
    )

    assert response.status_code == 403


def test_manual_incident_rejects_service_from_another_team(client, db):
    group = create_group()
    team = create_team(group)
    foreign_team = create_team(group)
    foreign_service = create_service(foreign_team)

    user = create_user(
        group=group,
        group_role="editor",
    )

    response = client.post(
        "/api/incidents",
        json={
            "team_id": team.id,
            "service_id": foreign_service.id,
            "title": "Wrong service incident",
            "notify": False,
        },
        headers=auth_headers_for(user),
    )

    assert response.status_code == 400


def test_manual_incident_with_notify_true_schedules_notification(client, db):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    user = create_user(
        group=group,
        group_role="editor",
    )

    response = client.post(
        "/api/incidents",
        json={
            "team_id": team.id,
            "service_id": service.id,
            "title": "Notify manual incident",
            "message": "Should schedule notification",
            "severity": "critical",
            "notify": True,
        },
        headers=auth_headers_for(user),
    )

    assert response.status_code == 201
    data = response.get_json()

    group_row = AlertGroup.get_by_id(data["id"])
    assert group_row.notification_pending is True
    assert group_row.notification_reason == "notification"
    assert group_row.notification_due_at is not None
