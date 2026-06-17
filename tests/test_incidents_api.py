from uuid import uuid4

from app.api.schemas.roles import GROUP_USER_ADMIN_ROLE
from app.login import create_access_token
from app.modules.db import incidents_repo
from app.modules.db.models import AlertEvent, AlertGroup, IncidentResponder
from tests.factories import (
    add_user_to_team,
    create_group,
    create_route,
    create_team,
    create_user,
)


def disable_responder_notifications(monkeypatch):
    monkeypatch.setattr(
        "app.services.incidents.responders."
        "notify_incident_responder_requested",
        lambda responder: {"status": "sent", "sent": 1, "error": None},
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
        "app.services.incidents.priorities.update_alert_messages",
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
        "app.services.incidents.priorities.update_alert_messages",
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
        "app.services.incidents.priorities.update_alert_messages",
        lambda group, event_type: 1,
    )

    monkeypatch.setattr(
        "app.services.incidents.stakeholders.send_stakeholder_email",
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
        "app.services.incidents.priorities.update_alert_messages",
        lambda group, event_type: 1,
    )

    monkeypatch.setattr(
        "app.services.incidents.stakeholders.send_stakeholder_email",
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


def test_add_duplicate_open_responder_is_rejected(client, db, monkeypatch):
    disable_responder_notifications(monkeypatch)

    group, team, route, incident = create_incident_fixture()
    headers, requester = create_responder_headers(group, team)

    target = create_user(
        username=unique_slug("target"),
        group=group,
        group_role="viewer",
    )
    add_user_to_team(team, target, role="responder")

    payload = {
        "target_type": "user",
        "target_user_id": target.id,
        "expires_after_minutes": 30,
    }

    first_response = client.post(
        f"/api/incidents/{incident.id}/responders",
        json=payload,
        headers=headers,
    )
    assert first_response.status_code == 201, first_response.get_json()

    second_response = client.post(
        f"/api/incidents/{incident.id}/responders",
        json=payload,
        headers=headers,
    )
    assert second_response.status_code == 400
    assert second_response.get_json()["error"] == "validation_error"
    assert (
        second_response.get_json()["message"]
        == "active responder request already exists for this target"
    )


def test_responder_declined_cannot_be_accepted_later(client, db, monkeypatch):
    disable_responder_notifications(monkeypatch)

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

    decline_response = client.put(
        f"/api/incidents/{incident.id}/responders/{responder_id}",
        json={
            "status": "declined",
            "response_message": "Busy",
        },
        headers=headers,
    )
    assert decline_response.status_code == 200, decline_response.get_json()
    assert decline_response.get_json()["status"] == "declined"

    accept_response = client.put(
        f"/api/incidents/{incident.id}/responders/{responder_id}",
        json={
            "status": "accepted",
            "response_message": "Actually joining",
        },
        headers=headers,
    )
    assert accept_response.status_code == 400
    assert accept_response.get_json()["error"] == "validation_error"
    assert (
        "cannot change responder status from declined to accepted"
        in accept_response.get_json()["message"]
    )


def test_target_user_can_accept_own_responder_request(client, db, monkeypatch):
    disable_responder_notifications(monkeypatch)

    group, team, route, incident = create_incident_fixture()
    requester_headers, requester = create_responder_headers(group, team)

    target = create_user(
        username=unique_slug("target"),
        group=group,
        group_role="viewer",
    )
    target.display_name = "Alice Smith"
    target.save(only=[target.__class__.display_name])
    add_user_to_team(team, target, role="viewer")

    create_response = client.post(
        f"/api/incidents/{incident.id}/responders",
        json={
            "target_type": "user",
            "target_user_id": target.id,
        },
        headers=requester_headers,
    )
    assert create_response.status_code == 201, create_response.get_json()
    responder_id = create_response.get_json()["id"]

    target_headers = make_headers(target)

    accept_response = client.put(
        f"/api/incidents/{incident.id}/responders/{responder_id}",
        json={
            "status": "accepted",
            "response_message": "I am joining",
        },
        headers=target_headers,
    )
    assert accept_response.status_code == 200, accept_response.get_json()

    payload = accept_response.get_json()
    assert payload["status"] == "accepted"
    assert payload["accepted_by_id"] == target.id

    event = (
        AlertEvent
        .select()
        .where(
            AlertEvent.group == incident,
            AlertEvent.event_type == "responder_accepted",
        )
        .order_by(AlertEvent.id.desc())
        .get()
    )

    assert "Alice Smith accepted responder request" in event.message
    assert "I am joining" in event.message


def test_non_target_viewer_cannot_accept_responder_request(client, db, monkeypatch):
    disable_responder_notifications(monkeypatch)

    group, team, route, incident = create_incident_fixture()
    requester_headers, requester = create_responder_headers(group, team)

    target = create_user(
        username=unique_slug("target"),
        group=group,
        group_role="viewer",
    )
    add_user_to_team(team, target, role="viewer")

    stranger = create_user(
        username=unique_slug("stranger"),
        group=group,
        group_role="viewer",
    )
    add_user_to_team(team, stranger, role="viewer")

    create_response = client.post(
        f"/api/incidents/{incident.id}/responders",
        json={
            "target_type": "user",
            "target_user_id": target.id,
        },
        headers=requester_headers,
    )
    assert create_response.status_code == 201, create_response.get_json()
    responder_id = create_response.get_json()["id"]

    response = client.put(
        f"/api/incidents/{incident.id}/responders/{responder_id}",
        json={
            "status": "accepted",
        },
        headers=make_headers(stranger),
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "access_denied"


def test_add_responder_rejects_extra_target_id(client, db, monkeypatch):
    disable_responder_notifications(monkeypatch)

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
            "target_team_id": team.id,
        },
        headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


def test_expire_due_incident_responders_expires_requested(db, monkeypatch):
    disable_responder_notifications(monkeypatch)

    from datetime import datetime, timedelta

    from app.modules.db import incidents_repo
    from app.services.incidents.responders import expire_due_incident_responders

    group, team, route, incident = create_incident_fixture()

    target = create_user(
        username=unique_slug("target"),
        group=group,
        group_role="viewer",
    )
    target.display_name = "Alice Smith"
    target.save(only=[target.__class__.display_name])
    add_user_to_team(team, target, role="responder")

    responder = incidents_repo.create_incident_responder(
        incident.id,
        {
            "target_type": "user",
            "target_user_id": target.id,
            "requested_by_id": None,
            "message": None,
            "expires_after_minutes": 30,
            "status": "requested",
        },
    )

    responder.expires_at = datetime.utcnow() - timedelta(seconds=1)
    responder.save(only=[IncidentResponder.expires_at])

    result = expire_due_incident_responders(limit=10)

    assert result["expired"] == 1
    assert result["skipped"] == 0

    responder = incidents_repo.get_incident_responder(responder.id)
    assert responder.status == "expired"
    assert responder.response_message == "Responder request expired"

    event = (
        AlertEvent
        .select()
        .where(
            AlertEvent.group == incident,
            AlertEvent.event_type == "responder_expired",
        )
        .get_or_none()
    )
    assert event is not None
    assert "Responder request expired for Alice Smith" in event.message


def test_incident_details_responder_contains_target_label(
    client,
    db,
    monkeypatch,
):
    disable_responder_notifications(monkeypatch)

    group, team, route, incident = create_incident_fixture()
    headers, requester = create_responder_headers(group, team)

    target = create_user(
        username=unique_slug("target"),
        group=group,
        group_role="viewer",
    )
    target.display_name = "Alice Smith"
    target.save(only=[target.__class__.display_name])
    add_user_to_team(team, target, role="responder")

    response = client.post(
        f"/api/incidents/{incident.id}/responders",
        json={
            "target_type": "user",
            "target_user_id": target.id,
            "message": "Please help with this incident.",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.get_json()

    details_response = client.get(
        f"/api/incidents/{incident.id}",
        headers=headers,
    )
    assert details_response.status_code == 200, details_response.get_json()

    payload = details_response.get_json()
    responders = payload["responders"]

    assert len(responders) == 1
    assert responders[0]["target"]["type"] == "user"
    assert responders[0]["target"]["id"] == target.id
    assert responders[0]["target"]["label"] == "Alice Smith"
    assert responders[0]["target"]["user"]["id"] == target.id


def test_add_responder_event_mentions_target_name(
    client,
    db,
    monkeypatch,
):
    disable_responder_notifications(monkeypatch)

    group, team, route, incident = create_incident_fixture()
    headers, requester = create_responder_headers(group, team)

    target = create_user(
        username=unique_slug("target"),
        group=group,
        group_role="viewer",
    )
    target.display_name = "Alice Smith"
    target.save(only=[target.__class__.display_name])
    add_user_to_team(team, target, role="responder")

    response = client.post(
        f"/api/incidents/{incident.id}/responders",
        json={
            "target_type": "user",
            "target_user_id": target.id,
            "message": "Please help with this incident.",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.get_json()

    event = (
        AlertEvent
        .select()
        .where(
            AlertEvent.group == incident,
            AlertEvent.event_type == "responder_requested",
        )
        .order_by(AlertEvent.id.desc())
        .get()
    )

    assert "Responder requested: Alice Smith" in event.message
    assert "Please help with this incident." in event.message


def test_decline_responder_event_mentions_actor_and_target(
    client,
    db,
    monkeypatch,
):
    disable_responder_notifications(monkeypatch)

    group, team, route, incident = create_incident_fixture()
    requester_headers, requester = create_responder_headers(group, team)

    target = create_user(
        username=unique_slug("target"),
        group=group,
        group_role="viewer",
    )
    target.display_name = "Alice Smith"
    target.save(only=[target.__class__.display_name])
    add_user_to_team(team, target, role="responder")

    response = client.post(
        f"/api/incidents/{incident.id}/responders",
        json={
            "target_type": "user",
            "target_user_id": target.id,
            "message": "Please help with this incident.",
        },
        headers=requester_headers,
    )
    assert response.status_code == 201, response.get_json()

    responder_id = response.get_json()["id"]

    target_headers = make_headers(target)

    decline_response = client.put(
        f"/api/incidents/{incident.id}/responders/{responder_id}",
        json={
            "status": "declined",
            "response_message": "Busy now",
        },
        headers=target_headers,
    )
    assert decline_response.status_code == 200, decline_response.get_json()

    event = (
        AlertEvent
        .select()
        .where(
            AlertEvent.group == incident,
            AlertEvent.event_type == "responder_declined",
        )
        .order_by(AlertEvent.id.desc())
        .get()
    )

    assert "Alice Smith declined responder request for Alice Smith" in event.message
    assert "Busy now" in event.message


def test_list_incident_responders_contains_target_label(
    client,
    db,
    monkeypatch,
):
    disable_responder_notifications(monkeypatch)

    group, team, route, incident = create_incident_fixture()
    headers, requester = create_responder_headers(group, team)

    target = create_user(
        username=unique_slug("target"),
        group=group,
        group_role="viewer",
    )
    target.display_name = "Alice Smith"
    target.save(only=[target.__class__.display_name])
    add_user_to_team(team, target, role="responder")

    create_response = client.post(
        f"/api/incidents/{incident.id}/responders",
        json={
            "target_type": "user",
            "target_user_id": target.id,
            "message": "Please help with this incident.",
        },
        headers=headers,
    )
    assert create_response.status_code == 201, create_response.get_json()

    response = client.get(
        f"/api/incidents/{incident.id}/responders",
        headers=headers,
    )
    assert response.status_code == 200, response.get_json()

    payload = response.get_json()

    assert len(payload) == 1
    assert payload[0]["target"]["type"] == "user"
    assert payload[0]["target"]["id"] == target.id
    assert payload[0]["target"]["label"] == "Alice Smith"
    assert payload[0]["target"]["user"]["id"] == target.id


def test_notification_center_shows_pending_responder_request(
    client,
    db,
    monkeypatch,
):
    disable_responder_notifications(monkeypatch)

    group, team, route, incident = create_incident_fixture()
    requester_headers, requester = create_responder_headers(group, team)

    target = create_user(
        username=unique_slug("target"),
        group=group,
        group_role="viewer",
    )
    target.display_name = "Alice Smith"
    target.save(only=[target.__class__.display_name])
    add_user_to_team(team, target, role="responder")

    create_response = client.post(
        f"/api/incidents/{incident.id}/responders",
        json={
            "target_type": "user",
            "target_user_id": target.id,
            "message": "Please help with database.",
        },
        headers=requester_headers,
    )
    assert create_response.status_code == 201, create_response.get_json()

    response = client.get(
        "/api/notification-center",
        headers=make_headers(target),
    )
    assert response.status_code == 200, response.get_json()

    payload = response.get_json()

    assert payload["unread_count"] == 1
    assert len(payload["items"]) == 1

    item = payload["items"][0]

    assert item["type"] == "responder_request"
    assert item["incident_id"] == incident.id
    assert item["responder"]["id"] == create_response.get_json()["id"]
    assert item["responder"]["target"]["label"] == "Alice Smith"
    assert "Please help with database." in item["body"]

    action_statuses = {
        action["status"]
        for action in item["actions"]
    }
    assert action_statuses == {"accepted", "declined"}


def test_notification_center_hides_responder_request_after_accept(
    client,
    db,
    monkeypatch,
):
    disable_responder_notifications(monkeypatch)

    group, team, route, incident = create_incident_fixture()
    requester_headers, requester = create_responder_headers(group, team)

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
        headers=requester_headers,
    )
    assert create_response.status_code == 201, create_response.get_json()

    responder_id = create_response.get_json()["id"]
    target_headers = make_headers(target)

    before_response = client.get(
        "/api/notification-center",
        headers=target_headers,
    )
    assert before_response.status_code == 200, before_response.get_json()
    assert before_response.get_json()["unread_count"] == 1

    accept_response = client.put(
        f"/api/incidents/{incident.id}/responders/{responder_id}",
        json={
            "status": "accepted",
        },
        headers=target_headers,
    )
    assert accept_response.status_code == 200, accept_response.get_json()

    after_response = client.get(
        "/api/notification-center",
        headers=target_headers,
    )
    assert after_response.status_code == 200, after_response.get_json()

    payload = after_response.get_json()

    assert payload["unread_count"] == 0
    assert payload["items"] == []
