"""2.5 Incident-owned collaboration acceptance and legacy boundaries."""
import pytest

from app.login import create_access_token
from app.modules.db.models import Incident, IncidentResponder, IncidentStakeholder
from tests.factories import add_user_to_team, create_group, create_team, create_user, unique


def _incident():
    group = create_group()
    team = create_team(group)
    user = create_user(unique("participant"), group=group)
    return Incident.create(team=team, title="Operational response"), user


def _headers(user):
    token, _ = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("decision", ["accepted", "declined"])
def test_team_invitation_without_source_team_membership(client, db, monkeypatch, decision):
    monkeypatch.setattr("app.services.incidents.responders.notify_incident_responder_requested", lambda row: None)
    incident, operator = _incident()
    group = incident.team.group
    add_user_to_team(incident.team, operator, "responder")
    target = create_team(group)
    inactive = create_team(group)
    inactive.active = False
    inactive.save()
    create_team(create_group())
    recipient = create_user(group=group, group_role="viewer")
    add_user_to_team(target, recipient, "responder")
    viewer = create_user(group=group, group_role="viewer")
    add_user_to_team(target, viewer, "viewer")
    sender_headers, recipient_headers, viewer_headers = map(_headers, (operator, recipient, viewer))
    base = f"/api/incidents/{incident.id}"
    requests = base + "/responders"
    assert client.get(requests + "?include_team_options=1", headers=sender_headers).json == {
        "teams": [{"id": target.id, "name": target.name}], "items": [],
    }
    payload = {"target_type": "team", "target_team_id": target.id, "message": "Please investigate"}
    result = client.post(requests, json=payload, headers=sender_headers)
    assert result.status_code == 201, result.json
    assert client.post(requests, json=payload, headers=sender_headers).status_code == 409
    request_id = result.json["id"]
    center = f"/api/notification-center?responder_id={request_id}"
    [item] = client.get(center, headers=recipient_headers).json["items"]
    assert item["url"] is None and item["responder"]["message"] == payload["message"]
    assert not client.get(center, headers=viewer_headers).json["items"]
    action = item["actions"][0]["url"]
    assert client.put(action, json={"status": decision}, headers=viewer_headers).status_code == 403
    assert client.put(action, json={"status": "expired"}, headers=recipient_headers).status_code == 403
    other = Incident.create(team=incident.team, title="Separate incident")
    wrong_url = f"/api/incidents/{other.id}/responders/{request_id}"
    assert client.put(wrong_url, json={"status": decision}, headers=recipient_headers).status_code == 403
    assert client.put(action, json={"status": decision}, headers=recipient_headers).status_code == 200
    assert not client.get(center, headers=recipient_headers).json["items"]
    assert client.get(base, headers=recipient_headers).status_code == 403
    participants = client.get(base + "/participants", headers=sender_headers).json
    assert [row["user_id"] for row in participants] == ([recipient.id] if decision == "accepted" else [])


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
