from uuid import uuid4

from app.api.schemas.roles import GROUP_USER_ADMIN_ROLE
from app.login import create_access_token
from app.modules.db import incidents_repo
from app.modules.db.models import AlertEvent, AlertGroup
from tests.factories import (
    add_user_to_team,
    create_group,
    create_route,
    create_team,
    create_user,
)


def unique_slug(prefix):
    return f"{prefix}-{uuid4().hex[:12]}"


def make_headers(user):
    token, _ = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def create_incident_for_route(
    team,
    route,
    *,
    priority_slug="p3",
    title="DiskFull",
    severity="warning",
    status="firing",
):
    priority = incidents_repo.get_priority_by_slug(priority_slug)

    return AlertGroup.create(
        team=team,
        route=route,
        service=route.service,
        rotation=route.rotation,
        escalation_policy=route.escalation_policy,
        source=route.source,
        group_key_hash=unique_slug("group-hash"),
        group_key=unique_slug("group-key"),
        title=title,
        message="/var is 95% full",
        severity=severity,
        status=status,
        alert_count=0,
        firing_count=0,
        priority=priority.id if priority else None,
        priority_slug=priority.slug if priority else priority_slug,
        priority_order=priority.level if priority else 3,
        priority_set_manually=False,
        common_labels={
            "alertname": title,
            "instance": "host1",
        },
        label_values={},
        payload_summary={},
    )


def create_incident_fixture(
    *,
    priority_slug="p3",
    title="DiskFull",
    severity="warning",
):
    group = create_group(slug=unique_slug("group"))
    team = create_team(group=group, slug=unique_slug("team"), name="Platform Team")
    route = create_route(team=team)

    incident = create_incident_for_route(
        team,
        route,
        priority_slug=priority_slug,
        title=title,
        severity=severity,
    )

    return group, team, route, incident


def create_responder_headers(group, team):
    user = create_user(
        username=unique_slug("responder"),
        group=group,
        group_role=GROUP_USER_ADMIN_ROLE,
    )
    add_user_to_team(team, user, role="responder")
    return make_headers(user), user


def create_viewer_headers(group, team):
    user = create_user(
        username=unique_slug("viewer"),
        group=group,
        group_role="viewer",
    )
    add_user_to_team(team, user, role="viewer")
    return make_headers(user), user


def test_list_incident_priorities(client, db):
    group = create_group(slug=unique_slug("group"))
    user = create_user(
        username=unique_slug("user"),
        group=group,
        group_role="viewer",
    )

    response = client.get(
        "/api/incidents/priorities",
        headers=make_headers(user),
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    slugs = {item["slug"] for item in payload}

    assert {"p1", "p2", "p3", "p4", "p5"}.issubset(slugs)


def test_list_incidents_returns_incident_shape(client, db):
    group, team, route, incident = create_incident_fixture()
    headers, user = create_viewer_headers(group, team)

    response = client.get(
        f"/api/incidents?team_id={team.id}",
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    assert "items" in payload

    item = payload["items"][0]
    assert item["id"] == incident.id
    assert item["incident_id"] == incident.id
    assert item["priority"]["slug"] == "p3"
    assert item["maintenance"]["suppressed"] is False


def test_get_incident_includes_responders_and_stakeholders(client, db):
    group, team, route, incident = create_incident_fixture()
    headers, user = create_viewer_headers(group, team)

    response = client.get(
        f"/api/incidents/{incident.id}",
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    assert payload["incident_id"] == incident.id
    assert "responders" in payload
    assert "stakeholders" in payload
    assert "events" in payload
    assert "alerts" in payload


def test_update_incident_priority(client, db):
    group, team, route, incident = create_incident_fixture()
    headers, user = create_responder_headers(group, team)

    response = client.put(
        f"/api/incidents/{incident.id}/priority",
        json={"priority": "p1"},
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    assert payload["priority"]["slug"] == "p1"
    assert payload["priority"]["set_manually"] is True

    event = (
        AlertEvent
        .select()
        .where(
            AlertEvent.group == incident,
            AlertEvent.event_type == "priority_changed",
        )
        .get_or_none()
    )

    assert event is not None


def test_update_incident_priority_rejects_unknown_priority(client, db):
    group, team, route, incident = create_incident_fixture()
    headers, user = create_responder_headers(group, team)

    response = client.put(
        f"/api/incidents/{incident.id}/priority",
        json={"priority": "p99"},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


def test_viewer_cannot_update_incident_priority(client, db):
    group, team, route, incident = create_incident_fixture()
    headers, user = create_viewer_headers(group, team)

    response = client.put(
        f"/api/incidents/{incident.id}/priority",
        json={"priority": "p1"},
        headers=headers,
    )

    assert response.status_code == 403


def test_add_user_responder_to_incident(client, db):
    group, team, route, incident = create_incident_fixture()
    headers, requester = create_responder_headers(group, team)

    target = create_user(
        username=unique_slug("target"),
        group=group,
        group_role="viewer",
    )
    add_user_to_team(team, target, role="responder")

    response = client.post(
        f"/api/incidents/{incident.id}/responders",
        json={
            "target_type": "user",
            "target_user_id": target.id,
            "message": "Please help with database checks",
            "expires_after_minutes": 30,
        },
        headers=headers,
    )

    assert response.status_code == 201, response.get_json()

    payload = response.get_json()
    assert payload["incident_id"] == incident.id
    assert payload["target_type"] == "user"
    assert payload["target_user_id"] == target.id
    assert payload["status"] == "requested"

    event = (
        AlertEvent
        .select()
        .where(
            AlertEvent.group == incident,
            AlertEvent.event_type == "responder_requested",
        )
        .get_or_none()
    )

    assert event is not None


def test_add_responder_requires_matching_target_id(client, db):
    group, team, route, incident = create_incident_fixture()
    headers, requester = create_responder_headers(group, team)

    response = client.post(
        f"/api/incidents/{incident.id}/responders",
        json={
            "target_type": "user",
        },
        headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


def test_update_responder_status(client, db):
    group, team, route, incident = create_incident_fixture()
    headers, requester = create_responder_headers(group, team)

    target = create_user(
        username=unique_slug("target"),
        group=group,
        group_role="viewer",
    )
    add_user_to_team(team, target, role="responder")

    create_response = client.post(
        f"/api/incidents/{incident.id}/responders",
        json={
            "target_type": "user",
            "target_user_id": target.id,
        },
        headers=headers,
    )

    assert create_response.status_code == 201, create_response.get_json()

    responder_id = create_response.get_json()["id"]

    response = client.put(
        f"/api/incidents/{incident.id}/responders/{responder_id}",
        json={
            "status": "accepted",
            "response_message": "I am joining",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    assert payload["status"] == "accepted"
    assert payload["accepted_by_id"] == requester.id

    event = (
        AlertEvent
        .select()
        .where(
            AlertEvent.group == incident,
            AlertEvent.event_type == "responder_accepted",
        )
        .get_or_none()
    )

    assert event is not None


def test_add_email_stakeholder_to_incident(client, db):
    group, team, route, incident = create_incident_fixture()
    headers, user = create_responder_headers(group, team)

    response = client.post(
        f"/api/incidents/{incident.id}/stakeholders",
        json={
            "email": "manager@example.com",
            "display_name": "Manager",
            "role": "business_owner",
            "notify_on_created": True,
            "notify_on_priority_change": True,
            "notify_on_status_change": True,
            "notify_on_resolved": True,
        },
        headers=headers,
    )

    assert response.status_code == 201, response.get_json()

    payload = response.get_json()
    assert payload["incident_id"] == incident.id
    assert payload["email"] == "manager@example.com"
    assert payload["role"] == "business_owner"
    assert payload["active"] is True


def test_remove_incident_stakeholder(client, db):
    group, team, route, incident = create_incident_fixture()
    headers, user = create_responder_headers(group, team)

    create_response = client.post(
        f"/api/incidents/{incident.id}/stakeholders",
        json={
            "email": "manager@example.com",
            "display_name": "Manager",
            "role": "stakeholder",
        },
        headers=headers,
    )

    assert create_response.status_code == 201, create_response.get_json()

    stakeholder_id = create_response.get_json()["id"]

    response = client.delete(
        f"/api/incidents/{incident.id}/stakeholders/{stakeholder_id}",
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["deleted"] is True

    list_response = client.get(
        f"/api/incidents/{incident.id}/stakeholders",
        headers=headers,
    )

    assert list_response.status_code == 200
    assert list_response.get_json() == []


def test_list_incidents_filters_by_priority(client, db):
    group, team, route, p1_incident = create_incident_fixture(
        priority_slug="p1",
        title="DatabaseDown",
        severity="critical",
    )
    p3_incident = create_incident_for_route(
        team,
        route,
        priority_slug="p3",
        title="DiskFull",
        severity="warning",
    )

    headers, user = create_viewer_headers(group, team)

    response = client.get(
        f"/api/incidents?team_id={team.id}&priority=p1",
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    ids = [item["id"] for item in payload["items"]]

    assert ids == [p1_incident.id]
    assert p3_incident.id not in ids
    assert payload["items"][0]["priority"]["slug"] == "p1"


def test_list_incidents_filters_by_multiple_priorities(client, db):
    group, team, route, p1_incident = create_incident_fixture(
        priority_slug="p1",
        title="DatabaseDown",
        severity="critical",
    )
    p3_incident = create_incident_for_route(
        team,
        route,
        priority_slug="p3",
        title="DiskFull",
        severity="warning",
    )
    p5_incident = create_incident_for_route(
        team,
        route,
        priority_slug="p5",
        title="DeployNotice",
        severity="info",
    )

    headers, user = create_viewer_headers(group, team)

    response = client.get(
        f"/api/incidents?team_id={team.id}&priority=p1,p3",
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    ids = {item["id"] for item in response.get_json()["items"]}

    assert p1_incident.id in ids
    assert p3_incident.id in ids
    assert p5_incident.id not in ids


def test_list_incidents_sorts_by_priority(client, db):
    group, team, route, p3_incident = create_incident_fixture(
        priority_slug="p3",
        title="DiskFull",
        severity="warning",
    )
    p1_incident = create_incident_for_route(
        team,
        route,
        priority_slug="p1",
        title="DatabaseDown",
        severity="critical",
    )
    p5_incident = create_incident_for_route(
        team,
        route,
        priority_slug="p5",
        title="DeployNotice",
        severity="info",
    )

    headers, user = create_viewer_headers(group, team)

    response = client.get(
        f"/api/incidents?team_id={team.id}&sort=priority&order=asc",
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    ids = [item["id"] for item in payload["items"]]
    priorities = [item["priority"]["slug"] for item in payload["items"]]

    assert ids == [
        p1_incident.id,
        p3_incident.id,
        p5_incident.id,
    ]
    assert priorities == ["p1", "p3", "p5"]
    assert payload["sort"] == {
        "field": "priority",
        "order": "asc",
    }


def test_update_incident_priority_updates_existing_messages(client, db, monkeypatch):
    group, team, route, incident = create_incident_fixture(
        priority_slug="p3",
        title="DiskFull",
        severity="warning",
    )

    headers, user = create_responder_headers(group, team)

    calls = []

    monkeypatch.setattr(
        "app.services.incidents.update_alert_messages",
        lambda group, event_type: calls.append((group.id, event_type)) or 1,
    )

    response = client.put(
        f"/api/incidents/{incident.id}/priority",
        json={
            "priority": "p1",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()

    assert payload["priority"]["slug"] == "p1"
    assert calls == [
        (incident.id, "priority_changed"),
    ]


def test_update_incident_priority_does_not_update_messages_when_unchanged(
    client,
    db,
    monkeypatch,
):
    group, team, route, incident = create_incident_fixture(
        priority_slug="p1",
        title="DiskFull",
        severity="critical",
    )

    headers, user = create_responder_headers(group, team)

    calls = []

    monkeypatch.setattr(
        "app.services.incidents.update_alert_messages",
        lambda group, event_type: calls.append((group.id, event_type)) or 1,
    )

    response = client.put(
        f"/api/incidents/{incident.id}/priority",
        json={
            "priority": "p1",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["priority"]["slug"] == "p1"
    assert calls == []


def test_update_incident_priority_notifies_stakeholders(client, db, monkeypatch):
    group, team, route, incident = create_incident_fixture(
        priority_slug="p3",
        title="DiskFull",
        severity="warning",
    )

    stakeholder = create_user(
        unique_slug("stakeholder"),
        group=group,
        email="stakeholder@example.com",
    )

    incidents_repo.create_incident_stakeholder(
        incident.id,
        {
            "user_id": stakeholder.id,
            "role": "business_owner",
            "source": "manual",
            "notify_on_priority_change": True,
        },
    )

    headers, user = create_responder_headers(group, team)

    emails = []

    monkeypatch.setattr(
        "app.services.incidents.update_alert_messages",
        lambda group, event_type: 1,
    )

    monkeypatch.setattr(
        "app.services.incidents.send_stakeholder_email",
        lambda recipient, subject, body: emails.append(
            {
                "recipient": recipient,
                "subject": subject,
                "body": body,
            }
        ),
    )

    response = client.put(
        f"/api/incidents/{incident.id}/priority",
        json={
            "priority": "p1",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["priority"]["slug"] == "p1"

    assert len(emails) == 1
    assert emails[0]["recipient"] == "stakeholder@example.com"
    assert "[P1] DiskFull priority changed" in emails[0]["subject"]
    assert "Incident priority changed: P3 Medium -> P1 Critical" in emails[0]["body"]
    assert "Priority: P1 Critical" in emails[0]["body"]


def test_update_incident_priority_does_not_notify_opted_out_stakeholders(
    client,
    db,
    monkeypatch,
):
    group, team, route, incident = create_incident_fixture(
        priority_slug="p3",
        title="DiskFull",
        severity="warning",
    )

    stakeholder = create_user(
        unique_slug("stakeholder"),
        group=group,
        email="stakeholder@example.com",
    )

    incidents_repo.create_incident_stakeholder(
        incident.id,
        {
            "user_id": stakeholder.id,
            "role": "business_owner",
            "source": "manual",
            "notify_on_priority_change": False,
        },
    )

    headers, user = create_responder_headers(group, team)

    emails = []

    monkeypatch.setattr(
        "app.services.incidents.update_alert_messages",
        lambda group, event_type: 1,
    )

    monkeypatch.setattr(
        "app.services.incidents.send_stakeholder_email",
        lambda recipient, subject, body: emails.append(recipient),
    )

    response = client.put(
        f"/api/incidents/{incident.id}/priority",
        json={
            "priority": "p1",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()
    assert emails == []
