"""2.5 Incident-owned collaboration acceptance and legacy boundaries."""
from app.modules.db.models import Incident, IncidentResponder, IncidentStakeholder
from tests.factories import create_group, create_team, create_user, unique


def _incident():
    group = create_group()
    team = create_team(group)
    user = create_user(unique("participant"), group=group)
    return Incident.create(team=team, title="Operational response"), user


def test_legacy_alert_group_collaboration_api_is_removed(client, admin_headers, db):
    incident, user = _incident()
    for suffix in ("responders", "stakeholders"):
        response = client.get(f"/api/alert-groups/{incident.id}/{suffix}", headers=admin_headers)
        assert response.status_code == 404


def test_incident_responder_request_flow(client, admin_headers, db, monkeypatch):
    incident, user = _incident()
    monkeypatch.setattr("app.services.incidents.responders.notify_incident_responder_requested",
                        lambda responder: {"status": "sent", "sent": 1})
    response = client.post(f"/api/incidents/{incident.id}/responders",
        json={"target_type": "user", "target_user_id": user.id}, headers=admin_headers)
    assert response.status_code == 201, response.get_json()
    responder_id = response.get_json()["id"]
    row = IncidentResponder.get_by_id(responder_id)
    assert row.incident_id == incident.id
    assert row.status == "requested"
    response = client.put(f"/api/incidents/{incident.id}/responders/{responder_id}",
        json={"status": "accepted"}, headers=admin_headers)
    assert response.status_code == 200, response.get_json()
    assert IncidentResponder.get_by_id(responder_id).status == "accepted"


def test_concrete_incident_commander_uses_canonical_responder_model(client, admin_headers, db):
    incident, user = _incident()
    response = client.post(f"/api/incidents/{incident.id}/participants",
        json={"user_id": user.id, "role": "commander"}, headers=admin_headers)
    assert response.status_code == 201, response.get_json()
    row = IncidentResponder.get_by_id(response.get_json()["id"])
    assert row.incident_id == incident.id
    assert row.role == "commander"
    assert row.status == "accepted"


def test_incident_stakeholder_is_not_alert_group_owned(client, admin_headers, db):
    incident, user = _incident()
    response = client.post(f"/api/incidents/{incident.id}/stakeholders",
        json={"user_id": user.id, "role": "stakeholder"}, headers=admin_headers)
    assert response.status_code == 201, response.get_json()
    row = IncidentStakeholder.get_by_id(response.get_json()["id"])
    assert row.incident_id == incident.id
    response = client.delete(f"/api/incidents/{incident.id}/stakeholders/{row.id}",
                             headers=admin_headers)
    assert response.status_code == 204
    assert IncidentStakeholder.get_by_id(row.id).active is False
