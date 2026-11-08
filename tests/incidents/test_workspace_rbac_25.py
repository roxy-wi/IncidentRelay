"""Incident 2.5 cross-team authorization regression gates.

No Incident ownership information may grant permission to read or mutate a
linked technical AlertGroup or another team's service.
"""
from app.login import create_access_token
from app.modules.db.models import Incident, IncidentService
from tests.factories import (
    add_user_to_team, create_group, create_service, create_team, create_user,
)


def _headers(user):
    token, _ = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def _fixture():
    group = create_group()
    owner_team = create_team(group)
    foreign_team = create_team(group)
    owner = create_user(group=group, group_role="viewer")
    add_user_to_team(owner_team, owner, role="responder")
    incident = Incident.create(team=owner_team, title="Restricted service impact")
    foreign_service = create_service(foreign_team, name="Private database")
    return incident, foreign_service, _headers(owner)


def test_affected_services_does_not_expose_other_team_service(client, db):
    incident, service, headers = _fixture()
    IncidentService.create(incident=incident, service=service)

    response = client.get(f"/api/incidents/{incident.id}/affected-services", headers=headers)
    assert response.status_code == 200, response.get_json()
    assert response.get_json() == []


def test_other_team_service_cannot_be_added_or_removed(client, db):
    incident, service, headers = _fixture()
    url = f"/api/incidents/{incident.id}/affected-services"
    response = client.post(url, headers=headers, json={"service_id": service.id})
    assert response.status_code in (403, 404), response.get_json()
    assert not IncidentService.select().where(
        IncidentService.incident == incident.id,
        IncidentService.service == service.id,
    ).exists()

    IncidentService.create(incident=incident, service=service)
    response = client.delete(f"{url}/{service.id}", headers=headers)
    assert response.status_code in (403, 404), response.get_json()
    assert IncidentService.select().where(
        IncidentService.incident == incident.id,
        IncidentService.service == service.id,
    ).exists()
