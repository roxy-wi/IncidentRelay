from app.login import create_access_token
from app.modules.db import incidents_repo
from app.modules.db.models import AlertGroup, ServiceOwner
from app.services.alerts.alert_comments import create_group_comment
from app.services.alerts.lifecycle import upsert_alert
from tests.factories import (
    add_user_to_team,
    create_group,
    create_route,
    create_service,
    create_team,
    create_user,
    unique,
)
import app.notifiers.browser_push.service as browser_push
from app.services.alerts.actions import acknowledge_alert, resolve_alert


def create_upsert_alert_data(route, *, status="firing", dedup_key=None):
    dedup_key = dedup_key or unique("disk-full")

    labels = {
        "alertname": "DiskFull",
        "severity": "critical",
        "instance": "host1",
    }

    annotations = {
        "summary": "DiskFull",
        "description": "/var is 95% full",
    }

    return {
        "source": route.source,
        "forced_route_id": route.id,
        "dedup_key": dedup_key,
        "external_id": dedup_key,
        "title": "DiskFull",
        "message": "/var is 95% full",
        "severity": "critical",
        "status": status,
        "labels": labels,
        "annotations": annotations,
        "payload": {
            "status": status,
            "labels": labels,
            "annotations": annotations,
            "fingerprint": dedup_key,
        },
    }


def auth_headers(user):
    token, _ = create_access_token(user)

    return {
        "Authorization": f"Bearer {token}",
    }


def create_service_owner_fixture():
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"), name="Platform Team")
    service = create_service(team, name="Cloud OPS", slug=unique("service"))
    route = create_route(team=team, service=service)

    manager = create_user(
        unique("manager"),
        group=group,
        email=f"{unique('manager')}@example.com",
    )
    add_user_to_team(team, manager, role="manager")

    owner = create_user(
        unique("owner"),
        group=group,
        email=f"{unique('owner')}@example.com",
    )

    return group, team, service, route, manager, owner


def create_incident_for_service(team, service, route):
    return AlertGroup.create(
        team=team,
        route=route,
        service=service,
        source=route.source,
        group_key_hash=unique("group-hash"),
        group_key=unique("group-key"),
        title="DiskFull",
        message="/var is 95% full",
        severity="critical",
        status="firing",
        alert_count=0,
        firing_count=0,
        priority_slug="p1",
        priority_order=1,
        common_labels={
            "alertname": "DiskFull",
            "severity": "critical",
        },
        label_values={},
        payload_summary={},
    )


def test_service_owner_api_creates_default_stakeholder_with_notification_flags(
    client,
    db,
):
    group, team, service, route, manager, owner = create_service_owner_fixture()

    response = client.post(
        f"/api/services/{service.id}/owners",
        json={
            "user_id": owner.id,
            "role": "business_owner",
            "active": True,
            "notify_on_created": True,
            "notify_on_priority_change": False,
            "notify_on_status_change": False,
            "notify_on_resolved": True,
        },
        headers=auth_headers(manager),
    )

    assert response.status_code == 201, response.get_json()

    payload = response.get_json()

    assert payload["service_id"] == service.id
    assert payload["user_id"] == owner.id
    assert payload["role"] == "business_owner"
    assert payload["active"] is True
    assert payload["notify_on_created"] is True
    assert payload["notify_on_priority_change"] is False
    assert payload["notify_on_status_change"] is False
    assert payload["notify_on_resolved"] is True

    db_owner = ServiceOwner.get_by_id(payload["id"])

    assert db_owner.service.id == service.id
    assert db_owner.user.id == owner.id
    assert db_owner.role == "business_owner"
    assert db_owner.notify_on_priority_change is False
    assert db_owner.notify_on_status_change is False


def test_service_owner_api_lists_default_stakeholders(client, db):
    group, team, service, route, manager, owner = create_service_owner_fixture()

    ServiceOwner.create(
        service=service,
        user=owner,
        role="owner",
        active=True,
        notify_on_created=True,
        notify_on_priority_change=True,
        notify_on_status_change=False,
        notify_on_resolved=True,
    )

    response = client.get(
        f"/api/services/{service.id}/owners",
        headers=auth_headers(manager),
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()

    assert len(payload) == 1
    assert payload[0]["service_id"] == service.id
    assert payload[0]["user_id"] == owner.id
    assert payload[0]["role"] == "owner"
    assert payload[0]["notify_on_status_change"] is False


def test_service_owner_api_updates_default_stakeholder(client, db):
    group, team, service, route, manager, owner = create_service_owner_fixture()

    service_owner = ServiceOwner.create(
        service=service,
        user=owner,
        role="owner",
        active=True,
        notify_on_created=True,
        notify_on_priority_change=True,
        notify_on_status_change=True,
        notify_on_resolved=True,
    )

    response = client.put(
        f"/api/services/{service.id}/owners/{service_owner.id}",
        json={
            "user_id": owner.id,
            "role": "support",
            "active": True,
            "notify_on_created": False,
            "notify_on_priority_change": True,
            "notify_on_status_change": False,
            "notify_on_resolved": False,
        },
        headers=auth_headers(manager),
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()

    assert payload["role"] == "support"
    assert payload["notify_on_created"] is False
    assert payload["notify_on_priority_change"] is True
    assert payload["notify_on_status_change"] is False
    assert payload["notify_on_resolved"] is False

    service_owner = ServiceOwner.get_by_id(service_owner.id)

    assert service_owner.role == "support"
    assert service_owner.notify_on_created is False
    assert service_owner.notify_on_resolved is False


def test_service_owner_api_deletes_default_stakeholder(client, db):
    group, team, service, route, manager, owner = create_service_owner_fixture()

    service_owner = ServiceOwner.create(
        service=service,
        user=owner,
        role="owner",
        active=True,
        notify_on_created=True,
        notify_on_priority_change=True,
        notify_on_status_change=True,
        notify_on_resolved=True,
    )

    response = client.delete(
        f"/api/services/{service.id}/owners/{service_owner.id}",
        headers=auth_headers(manager),
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json() == {
        "deleted": True,
        "id": service_owner.id,
    }

    service_owner = ServiceOwner.get_by_id(service_owner.id)

    assert service_owner.active is False


def test_service_owner_notification_flags_are_copied_to_incident_stakeholder(db):
    group, team, service, route, manager, owner = create_service_owner_fixture()
    incident = create_incident_for_service(team, service, route)

    ServiceOwner.create(
        service=service,
        user=owner,
        role="business_owner",
        active=True,
        notify_on_created=True,
        notify_on_priority_change=False,
        notify_on_status_change=False,
        notify_on_resolved=True,
    )

    rows = incidents_repo.add_service_stakeholders_to_incident(incident)

    assert len(rows) == 1

    stakeholder = rows[0]

    assert stakeholder.group.id == incident.id
    assert stakeholder.user.id == owner.id
    assert stakeholder.role == "business_owner"
    assert stakeholder.source == "service_owner"
    assert stakeholder.notify_on_created is True
    assert stakeholder.notify_on_priority_change is False
    assert stakeholder.notify_on_status_change is False
    assert stakeholder.notify_on_resolved is True


def test_service_owner_support_role_is_copied_to_incident_stakeholder(db):
    group, team, service, route, manager, owner = create_service_owner_fixture()
    incident = create_incident_for_service(team, service, route)

    ServiceOwner.create(
        service=service,
        user=owner,
        role="support",
        active=True,
        notify_on_created=True,
        notify_on_priority_change=True,
        notify_on_status_change=True,
        notify_on_resolved=True,
    )

    rows = incidents_repo.add_service_stakeholders_to_incident(incident)

    assert len(rows) == 1
    assert rows[0].role == "support"
    assert rows[0].user.id == owner.id


def test_inactive_service_owner_is_not_copied_to_incident_stakeholders(db):
    group, team, service, route, manager, owner = create_service_owner_fixture()
    incident = create_incident_for_service(team, service, route)

    ServiceOwner.create(
        service=service,
        user=owner,
        role="business_owner",
        active=False,
        notify_on_created=True,
        notify_on_priority_change=True,
        notify_on_status_change=True,
        notify_on_resolved=True,
    )

    rows = incidents_repo.add_service_stakeholders_to_incident(incident)

    assert rows == []
    assert incidents_repo.list_incident_stakeholders(incident.id) == []


def test_service_owner_is_not_copied_twice_to_incident_stakeholders(db):
    group, team, service, route, manager, owner = create_service_owner_fixture()
    incident = create_incident_for_service(team, service, route)

    ServiceOwner.create(
        service=service,
        user=owner,
        role="business_owner",
        active=True,
        notify_on_created=True,
        notify_on_priority_change=True,
        notify_on_status_change=True,
        notify_on_resolved=True,
    )

    first_rows = incidents_repo.add_service_stakeholders_to_incident(incident)
    second_rows = incidents_repo.add_service_stakeholders_to_incident(incident)
    stakeholders = incidents_repo.list_incident_stakeholders(incident.id)

    assert len(first_rows) == 1
    assert second_rows == []
    assert len(stakeholders) == 1
    assert stakeholders[0].user.id == owner.id


def test_new_alert_notifies_service_owner_stakeholder_on_created(
    client,
    db,
    monkeypatch,
):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"), name="Platform Team")
    service = create_service(team, name="Cloud OPS", slug=unique("service"))
    route = create_route(team=team, service=service)

    stakeholder = create_user(
        unique("stakeholder"),
        group=group,
        email="stakeholder@example.com",
    )

    ServiceOwner.create(
        service=service,
        user=stakeholder,
        role="business_owner",
        active=True,
        notify_on_created=True,
        notify_on_priority_change=True,
        notify_on_status_change=True,
        notify_on_resolved=True,
    )

    emails = []

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

    alert_data = create_upsert_alert_data(route)

    incident, created = upsert_alert(alert_data)

    assert created is True
    assert incident is not None

    incident_stakeholders = incidents_repo.list_incident_stakeholders(
        incident.id,
    )

    assert len(incident_stakeholders) == 1
    assert incident_stakeholders[0].user.id == stakeholder.id
    assert incident_stakeholders[0].source == "service_owner"

    assert len(emails) == 1
    assert emails[0]["recipient"] == "stakeholder@example.com"
    assert "[P1] DiskFull created" in emails[0]["subject"]
    assert "New incident created: [P1] DiskFull" in emails[0]["body"]
    assert "Priority: P1 Critical" in emails[0]["body"]


def test_new_alert_does_not_notify_service_owner_when_created_notifications_disabled(
    client,
    db,
    monkeypatch,
):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"), name="Platform Team")
    service = create_service(team, name="Cloud OPS", slug=unique("service"))
    route = create_route(team=team, service=service)

    stakeholder = create_user(
        unique("stakeholder"),
        group=group,
        email="stakeholder@example.com",
    )

    ServiceOwner.create(
        service=service,
        user=stakeholder,
        role="business_owner",
        active=True,
        notify_on_created=False,
        notify_on_priority_change=True,
        notify_on_status_change=True,
        notify_on_resolved=True,
    )

    emails = []

    monkeypatch.setattr(
        "app.services.incidents.stakeholders.send_stakeholder_email",
        lambda recipient, subject, body: emails.append(recipient),
    )

    alert_data = create_upsert_alert_data(route)

    incident, created = upsert_alert(alert_data)

    assert created is True
    assert incident is not None
    assert incidents_repo.list_incident_stakeholders(incident.id)
    assert emails == []


def test_new_alert_sends_browser_push_to_service_owner_stakeholder(
    client,
    db,
    monkeypatch,
):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"), name="Platform Team")
    service = create_service(team, name="Cloud OPS", slug=unique("service"))
    route = create_route(team=team, service=service)

    stakeholder = create_user(
        unique("stakeholder"),
        group=group,
        email="stakeholder@example.com",
    )

    ServiceOwner.create(
        service=service,
        user=stakeholder,
        role="business_owner",
        active=True,
        notify_on_created=True,
        notify_on_priority_change=True,
        notify_on_status_change=True,
        notify_on_resolved=True,
    )

    emails = []
    pushes = []

    monkeypatch.setattr(
        "app.services.incidents.stakeholders.send_stakeholder_email",
        lambda recipient, subject, body: emails.append(recipient),
    )

    monkeypatch.setattr(
        "app.services.incidents.stakeholders.browser_push.send_stakeholder_push_to_user",
        lambda user, group, event_type="incident_created": pushes.append(
            {
                "user_id": user.id,
                "group_id": group.id,
                "event_type": event_type,
            }
        ) or 1,
    )

    alert_data = create_upsert_alert_data(route)

    incident, created = upsert_alert(alert_data)

    assert created is True
    assert incident is not None
    assert emails == ["stakeholder@example.com"]
    assert pushes == [
        {
            "user_id": stakeholder.id,
            "group_id": incident.id,
            "event_type": "incident_created",
        }
    ]


def test_new_alert_does_not_push_stakeholder_when_created_notifications_disabled(
    client,
    db,
    monkeypatch,
):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"), name="Platform Team")
    service = create_service(team, name="Cloud OPS", slug=unique("service"))
    route = create_route(team=team, service=service)

    stakeholder = create_user(
        unique("stakeholder"),
        group=group,
        email="stakeholder@example.com",
    )

    ServiceOwner.create(
        service=service,
        user=stakeholder,
        role="business_owner",
        active=True,
        notify_on_created=False,
        notify_on_priority_change=True,
        notify_on_status_change=True,
        notify_on_resolved=True,
    )

    pushes = []

    monkeypatch.setattr(
        "app.services.incidents.stakeholders.send_stakeholder_email",
        lambda recipient, subject, body: None,
    )

    monkeypatch.setattr(
        "app.services.incidents.stakeholders.browser_push.send_stakeholder_push_to_user",
        lambda user, group, event_type="incident_created": pushes.append(user.id) or 1,
    )

    alert_data = create_upsert_alert_data(route)

    incident, created = upsert_alert(alert_data)

    assert created is True
    assert incident is not None
    assert pushes == []


def create_push_alert_group(
    *,
    status="firing",
    title="DiskFull",
    severity="critical",
    priority_slug="p1",
    priority_order=1,
):
    group = create_group(slug=unique("group"))
    team = create_team(group, slug=unique("team"), name="Platform Team")
    service = create_service(team, name="Cloud OPS", slug=unique("service"))
    route = create_route(team=team, service=service)

    return AlertGroup.create(
        team=team,
        route=route,
        service=service,
        source=route.source,
        group_key_hash=unique("group-hash"),
        group_key=unique("group-key"),
        title=title,
        message="/var is 95% full",
        severity=severity,
        status=status,
        alert_count=0,
        firing_count=0,
        priority_slug=priority_slug,
        priority_order=priority_order,
        common_labels={
            "alertname": title,
            "severity": severity,
        },
        label_values={},
        payload_summary={},
    )


def test_build_stakeholder_push_payload_has_no_action_tokens(db):
    group = create_push_alert_group(
        status="firing",
        title="DiskFull",
        severity="critical",
        priority_slug="p1",
        priority_order=1,
    )

    payload = browser_push.build_stakeholder_alert_push_payload(
        group,
        event_type="incident_created",
    )

    assert payload["title"] == "INCIDENT CREATED: [P1] DiskFull"
    assert payload["priority"] == "p1"
    assert payload["priority_label"] == "P1 Critical"
    assert payload["action_tokens"] == {}


def test_acknowledge_alert_notifies_stakeholder_status_change(db, monkeypatch):
    group, team, service, route, manager, owner = create_service_owner_fixture()
    incident = create_incident_for_service(team, service, route)

    incidents_repo.create_incident_stakeholder(
        incident.id,
        {
            "user_id": owner.id,
            "role": "business_owner",
            "source": "manual",
            "notify_on_created": True,
            "notify_on_priority_change": True,
            "notify_on_status_change": True,
            "notify_on_resolved": True,
        },
    )

    emails = []
    pushes = []

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

    monkeypatch.setattr(
        "app.services.incidents.stakeholders.browser_push.send_stakeholder_push_to_user",
        lambda user, group, event_type="status_changed": pushes.append(
            {
                "user_id": user.id,
                "group_id": group.id,
                "event_type": event_type,
            }
        ) or 1,
    )

    acknowledge_alert(incident.id)

    assert len(emails) == 1
    assert emails[0]["recipient"] == owner.email
    assert "[P1] DiskFull status changed" in emails[0]["subject"]
    assert "Incident status changed: firing -> acknowledged" in emails[0]["body"]

    assert pushes == [
        {
            "user_id": owner.id,
            "group_id": incident.id,
            "event_type": "status_changed",
        }
    ]


def test_acknowledge_alert_respects_stakeholder_status_flag(db, monkeypatch):
    group, team, service, route, manager, owner = create_service_owner_fixture()
    incident = create_incident_for_service(team, service, route)

    incidents_repo.create_incident_stakeholder(
        incident.id,
        {
            "user_id": owner.id,
            "role": "business_owner",
            "source": "manual",
            "notify_on_created": True,
            "notify_on_priority_change": True,
            "notify_on_status_change": False,
            "notify_on_resolved": True,
        },
    )

    emails = []
    pushes = []

    monkeypatch.setattr(
        "app.services.incidents.stakeholders.send_stakeholder_email",
        lambda recipient, subject, body: emails.append(recipient),
    )

    monkeypatch.setattr(
        "app.services.incidents.stakeholders.browser_push.send_stakeholder_push_to_user",
        lambda user, group, event_type="status_changed": pushes.append(user.id) or 1,
    )

    acknowledge_alert(incident.id)

    assert emails == []
    assert pushes == []


def test_resolve_alert_notifies_stakeholder_resolved(db, monkeypatch):
    group, team, service, route, manager, owner = create_service_owner_fixture()
    incident = create_incident_for_service(team, service, route)

    incidents_repo.create_incident_stakeholder(
        incident.id,
        {
            "user_id": owner.id,
            "role": "business_owner",
            "source": "manual",
            "notify_on_created": True,
            "notify_on_priority_change": True,
            "notify_on_status_change": True,
            "notify_on_resolved": True,
        },
    )

    emails = []
    pushes = []

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

    monkeypatch.setattr(
        "app.services.incidents.stakeholders.browser_push.send_stakeholder_push_to_user",
        lambda user, group, event_type="incident_resolved": pushes.append(
            {
                "user_id": user.id,
                "group_id": group.id,
                "event_type": event_type,
            }
        ) or 1,
    )

    resolve_alert(incident.id)

    assert len(emails) == 1
    assert emails[0]["recipient"] == owner.email
    assert "[P1] DiskFull resolved" in emails[0]["subject"]
    assert "Incident resolved: [P1] DiskFull" in emails[0]["body"]

    assert pushes == [
        {
            "user_id": owner.id,
            "group_id": incident.id,
            "event_type": "incident_resolved",
        }
    ]


def test_resolve_alert_respects_stakeholder_resolved_flag(db, monkeypatch):
    group, team, service, route, manager, owner = create_service_owner_fixture()
    incident = create_incident_for_service(team, service, route)

    incidents_repo.create_incident_stakeholder(
        incident.id,
        {
            "user_id": owner.id,
            "role": "business_owner",
            "source": "manual",
            "notify_on_created": True,
            "notify_on_priority_change": True,
            "notify_on_status_change": True,
            "notify_on_resolved": False,
        },
    )

    emails = []
    pushes = []

    monkeypatch.setattr(
        "app.services.incidents.stakeholders.send_stakeholder_email",
        lambda recipient, subject, body: emails.append(recipient),
    )

    monkeypatch.setattr(
        "app.services.incidents.stakeholders.browser_push.send_stakeholder_push_to_user",
        lambda user, group, event_type="incident_resolved": pushes.append(user.id) or 1,
    )

    resolve_alert(incident.id)

    assert emails == []
    assert pushes == []


def test_incoming_resolved_payload_notifies_stakeholder_resolved(
    db,
    monkeypatch,
):
    group, team, service, route, manager, owner = create_service_owner_fixture()

    ServiceOwner.create(
        service=service,
        user=owner,
        role="business_owner",
        active=True,
        notify_on_created=True,
        notify_on_priority_change=True,
        notify_on_status_change=True,
        notify_on_resolved=True,
    )

    emails = []
    pushes = []

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

    monkeypatch.setattr(
        "app.services.incidents.stakeholders.browser_push.send_stakeholder_push_to_user",
        lambda user, group, event_type="incident_created": pushes.append(
            {
                "user_id": user.id,
                "group_id": group.id,
                "event_type": event_type,
            }
        ) or 1,
    )

    dedup_key = unique("disk-full")

    incident, created = upsert_alert(
        create_upsert_alert_data(
            route,
            status="firing",
            dedup_key=dedup_key,
        )
    )

    assert created is True
    assert incident is not None

    emails.clear()
    pushes.clear()

    incident, created = upsert_alert(
        create_upsert_alert_data(
            route,
            status="resolved",
            dedup_key=dedup_key,
        )
    )

    assert created is False
    assert incident is not None
    assert incident.status == "resolved"

    assert len(emails) == 1
    assert emails[0]["recipient"] == owner.email
    assert "[P1] DiskFull resolved" in emails[0]["subject"]
    assert "Incident resolved: [P1] DiskFull" in emails[0]["body"]

    assert pushes == [
        {
            "user_id": owner.id,
            "group_id": incident.id,
            "event_type": "incident_resolved",
        }
    ]


def test_incoming_resolved_payload_respects_stakeholder_resolved_flag(
    db,
    monkeypatch,
):
    group, team, service, route, manager, owner = create_service_owner_fixture()

    ServiceOwner.create(
        service=service,
        user=owner,
        role="business_owner",
        active=True,
        notify_on_created=True,
        notify_on_priority_change=True,
        notify_on_status_change=True,
        notify_on_resolved=False,
    )

    emails = []
    pushes = []

    monkeypatch.setattr(
        "app.services.incidents.stakeholders.send_stakeholder_email",
        lambda recipient, subject, body: emails.append(recipient),
    )

    monkeypatch.setattr(
        "app.services.incidents.stakeholders.browser_push.send_stakeholder_push_to_user",
        lambda user, group, event_type="incident_resolved": pushes.append(user.id) or 1,
    )

    dedup_key = unique("disk-full")

    incident, created = upsert_alert(
        create_upsert_alert_data(
            route,
            status="firing",
            dedup_key=dedup_key,
        )
    )

    assert created is True
    assert incident is not None

    emails.clear()
    pushes.clear()

    incident, created = upsert_alert(
        create_upsert_alert_data(
            route,
            status="resolved",
            dedup_key=dedup_key,
        )
    )

    assert created is False
    assert incident is not None
    assert incident.status == "resolved"
    assert emails == []
    assert pushes == []


def test_group_comment_notifies_stakeholder(db, monkeypatch):
    group, team, service, route, manager, owner = create_service_owner_fixture()
    incident = create_incident_for_service(team, service, route)

    incidents_repo.create_incident_stakeholder(
        incident.id,
        {
            "user_id": owner.id,
            "role": "business_owner",
            "source": "manual",
            "notify_on_created": True,
            "notify_on_priority_change": True,
            "notify_on_status_change": True,
            "notify_on_resolved": True,
            "notify_on_comment": True,
        },
    )

    emails = []
    pushes = []

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

    monkeypatch.setattr(
        "app.services.incidents.stakeholders.browser_push.send_stakeholder_push_to_user",
        lambda user, group, event_type="incident_comment_added", context=None: pushes.append(
            {
                "user_id": user.id,
                "group_id": group.id,
                "event_type": event_type,
                "context": context,
            }
        ) or 1,
    )

    create_group_comment(
        group_id=incident.id,
        body="Checked logs, looks like disk cleanup is safe.",
        user_id=manager.id,
    )

    assert len(emails) == 1
    assert emails[0]["recipient"] == owner.email
    assert "[P1] DiskFull new comment" in emails[0]["subject"]
    assert "New comment from" in emails[0]["body"]
    assert "Checked logs, looks like disk cleanup is safe." in emails[0]["body"]

    assert len(pushes) == 1
    assert pushes[0]["user_id"] == owner.id
    assert pushes[0]["group_id"] == incident.id
    assert pushes[0]["event_type"] == "incident_comment_added"
    assert pushes[0]["context"]["comment_body"] == (
        "Checked logs, looks like disk cleanup is safe."
    )


def test_group_comment_respects_stakeholder_comment_flag(db, monkeypatch):
    group, team, service, route, manager, owner = create_service_owner_fixture()
    incident = create_incident_for_service(team, service, route)

    incidents_repo.create_incident_stakeholder(
        incident.id,
        {
            "user_id": owner.id,
            "role": "business_owner",
            "source": "manual",
            "notify_on_created": True,
            "notify_on_priority_change": True,
            "notify_on_status_change": True,
            "notify_on_resolved": True,
            "notify_on_comment": False,
        },
    )

    emails = []
    pushes = []

    monkeypatch.setattr(
        "app.services.incidents.stakeholders.send_stakeholder_email",
        lambda recipient, subject, body: emails.append(recipient),
    )

    monkeypatch.setattr(
        "app.services.incidents.stakeholders.browser_push.send_stakeholder_push_to_user",
        lambda user, group, event_type="incident_comment_added", context=None: pushes.append(user.id) or 1,
    )

    create_group_comment(
        group_id=incident.id,
        body="Added investigation details.",
        user_id=manager.id,
    )

    assert emails == []
    assert pushes == []
