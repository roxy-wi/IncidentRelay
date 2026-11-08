from app.login import create_access_token
from app.modules.db.models import AlertGroup, ServiceOwner
from tests.factories import (
    add_user_to_team,
    create_group,
    create_route,
    create_service,
    create_team,
    create_user,
    unique,
)


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



def test_incident_declaration_snapshots_service_owners(db, monkeypatch):
    from app.modules.db.models import IncidentStakeholder
    from app.services.incidents.core import create_incident
    monkeypatch.setattr("app.services.incidents.stakeholders.notify_stakeholders", lambda *a, **k: 0)
    group, team, service, route, manager, owner = create_service_owner_fixture()
    ServiceOwner.create(service=service, user=owner, role="business_owner", active=True,
                        notify_on_created=True, notify_on_priority_change=False,
                        notify_on_status_change=False, notify_on_resolved=True)
    incident = create_incident(team_id=team.id, title="Service outage", service_id=service.id,
                               user_id=manager.id)
    rows = list(IncidentStakeholder.select().where(IncidentStakeholder.incident == incident.id))
    assert len(rows) == 1
    assert rows[0].user_id == owner.id
    assert rows[0].role == "business_owner"
    assert rows[0].source == "service_owner"
    assert rows[0].notify_on_priority_change is False


def test_technical_alert_group_does_not_create_operational_stakeholders(db):
    from app.modules.db.models import IncidentStakeholder
    group, team, service, route, manager, owner = create_service_owner_fixture()
    ServiceOwner.create(service=service, user=owner, role="business_owner", active=True)
    alert_group = create_incident_for_service(team, service, route)
    assert alert_group.id is not None
    assert IncidentStakeholder.select().count() == 0
