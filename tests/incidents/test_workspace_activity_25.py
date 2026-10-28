"""Runtime contracts for Incident activity, UTC timestamps and service context."""

from datetime import datetime, timedelta

import pytest

from app.login import create_access_token
from app.modules.db.models import (
    AlertComment, AlertEvent, Incident, IncidentAlertGroupLink, IncidentComment,
    IncidentEvent, IncidentResponder, IncidentService, IncidentStakeholder,
    ServiceLink, ServiceRunbook,
)
from tests.factories import (
    add_user_to_team, create_group, create_impact_alert_group, create_service,
    create_service_dependency, create_team, create_user,
)


@pytest.fixture
def workspace(db):
    group = create_group()
    team = create_team(group)
    user = create_user(group=group, group_role="viewer")
    add_user_to_team(team, user, role="responder")
    service = create_service(team)
    incident = Incident.create(team=team, title="Activity regression")
    alert_group = create_impact_alert_group(team=team, service=service)
    IncidentAlertGroupLink.create(incident=incident, alert_group=alert_group)
    token, _ = create_access_token(user)
    return incident, alert_group, service, user, {"Authorization": f"Bearer {token}"}


def activity(client, workspace, query=""):
    incident, _, _, _, headers = workspace
    response = client.get(f"/api/incidents/{incident.id}/activity{query}", headers=headers)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def test_reopen_activity_keeps_transition_source_author_and_utc(client, workspace):
    incident, group, _, user, _ = workspace
    at = datetime(2026, 10, 25, 1, 30)
    event = IncidentEvent.create(
        incident=incident, user=user, created_at=at,
        event_type="incident_reopened_by_alert_group",
        data={"from": "resolved", "to": "investigating", "alert_group_id": group.id,
              "payload": {"password": "never-expose"}, "new_alert_id": 12345},
    )
    row = activity(client, workspace)[0]
    assert row["record_id"] == event.id
    assert row["source_type"] == "Incident"
    assert row["data"] == {"from": "resolved", "to": "investigating", "alert_group_id": group.id}
    assert row["actor"] == {"id": user.id, "username": user.username, "display_name": user.display_name}
    assert row["created_at"] == "2026-10-25T01:30:00Z"


@pytest.mark.parametrize("visibility", ["foreign_team", "unlinked", "no_team"])
def test_hidden_technical_records_and_references_are_omitted(client, workspace, visibility):
    incident, group, _, user, _ = workspace
    if visibility == "foreign_team":
        group.team = create_team(group.team.group)
        group.save()
    elif visibility == "no_team":
        group.team = None
        group.save()
    else:
        IncidentAlertGroupLink.update(removed_at=datetime(2026, 1, 1)).where(
            IncidentAlertGroupLink.incident == incident.id,
        ).execute()
    AlertComment.create(group=group, user=user, body="private technical comment")
    AlertEvent.create(group=group, user=user, event_type="reopened", message="private signal")
    IncidentEvent.create(
        incident=incident, event_type="incident_reopened_by_alert_group",
        message=f"private name #{group.id}",
        data={"alert_group_id": group.id, "from": "resolved", "to": "investigating"},
    )
    rows = activity(client, workspace)
    assert len(rows) == 1
    assert rows[0]["data"] == {"from": "resolved", "to": "investigating"}
    assert rows[0]["message"] is None
    assert rows[0]["actor"] is None


def test_comments_keep_authorship_and_origin_without_duplicate_markers(client, workspace):
    incident, group, _, user, _ = workspace
    at = datetime(2026, 10, 25, 12)
    own = IncidentComment.create(incident=incident, author=user, body="operational", created_at=at)
    IncidentEvent.create(incident=incident, event_type="incident_comment_added",
                         data={"comment_id": own.id}, created_at=at + timedelta(seconds=1))
    technical = AlertComment.create(group=group, user=user, body="technical", created_at=at)
    AlertComment.create(group=group, user=user, body="deleted", deleted=True)
    rows = activity(client, workspace, "?limit=2")
    assert {(r["source_type"], r["record_id"]) for r in rows} == {
        ("Incident", own.id), ("AlertGroup", technical.id),
    }
    assert all(row["actor_id"] == user.id and row["actor"]["id"] == user.id for row in rows)
    assert {r["message"] for r in rows} == {"operational", "technical"}
    assert activity(client, workspace, "?limit=2") == rows
    assert AlertComment.get_by_id(technical.id).group_id == group.id


def test_global_limit_merges_newest_rows_across_streams(client, workspace):
    incident, group, _, user, _ = workspace
    at = datetime(2026, 10, 25, 12)
    for second in range(6):
        AlertEvent.create(group=group, event_type="reopened", created_at=at + timedelta(seconds=second))
    IncidentComment.create(incident=incident, author=user, body="newest", created_at=at + timedelta(seconds=7))
    rows = activity(client, workspace, "?limit=3")
    assert len(rows) == 3
    assert [row["created_at"] for row in rows] == [
        "2026-10-25T12:00:07Z", "2026-10-25T12:00:05Z", "2026-10-25T12:00:04Z",
    ]


@pytest.mark.parametrize("data", [{}, [], "invalid", {"fields": [None, {}, [], "root_cause", "secret"]}])
def test_malformed_event_metadata_does_not_break_activity(client, workspace, data):
    incident, _, _, _, _ = workspace
    IncidentEvent.create(incident=incident, event_type="incident_updated", data=data)
    row = activity(client, workspace)[0]
    assert row["data"] == ({"fields": ["root_cause"]} if isinstance(data, dict) and data else {})


@pytest.mark.parametrize("limit", ["0", "501", "bad", "1.5", "-2"])
def test_invalid_activity_limit(client, workspace, limit):
    incident, _, _, _, headers = workspace
    assert client.get(f"/api/incidents/{incident.id}/activity?limit={limit}", headers=headers).status_code == 400


def test_collaboration_dates_use_explicit_utc(client, workspace):
    incident, _, service, user, headers = workspace
    at = datetime(2026, 10, 25, 1, 30)
    IncidentComment.create(incident=incident, author=user, body="UTC", created_at=at, updated_at=at)
    IncidentResponder.create(incident=incident, target_type="user", target_user=user,
                             role="responder", status="accepted", created_at=at)
    IncidentStakeholder.create(incident=incident, user=user, created_at=at)
    IncidentService.create(incident=incident, service=service, added_at=at)
    for endpoint, fields in (("comments", ["created_at", "updated_at"]),
                             ("participants", ["created_at"]), ("stakeholders", ["created_at"]),
                             ("affected-services", ["added_at"])):
        response = client.get(f"/api/incidents/{incident.id}/{endpoint}", headers=headers)
        assert response.status_code == 200, response.get_json()
        for field in fields:
            assert response.get_json()[0][field] == "2026-10-25T01:30:00Z"


def test_service_context_uses_shared_impact_without_private_dependencies(client, workspace):
    incident, _, service, user, headers = workspace
    private_team = create_team(service.group)
    private_service = create_service(private_team, name="Private root cause", status="major_outage")
    create_service_dependency(service=service, depends_on_service=private_service)
    IncidentService.create(incident=incident, service=service)
    IncidentService.create(incident=incident, service=private_service)
    ServiceRunbook.create(service=service, title="Runbook", url="https://example.org/runbook")
    ServiceLink.create(service=service, label="Dashboard", url="https://example.org/dashboard")
    IncidentEvent.create(incident=incident, event_type="incident_service_added",
                         message="Private root cause", data={"service_id": private_service.id})
    response = client.get(f"/api/incidents/{incident.id}/affected-services", headers=headers)
    assert response.status_code == 200, response.get_json()
    rows = response.get_json()
    assert len(rows) == 1
    assert rows[0]["service_id"] == service.id
    assert rows[0]["impact"]["effective_status"] == "major_outage"
    assert rows[0]["impact"]["effective_impact_score"] > 0
    assert rows[0]["dependencies"] == []
    assert rows[0]["permissions"]["can_remove"] is True
    assert rows[0]["runbooks"][0]["title"] == "Runbook"
    assert rows[0]["links"][0]["label"] == "Dashboard"
    assert "Private root cause" not in response.get_data(as_text=True)
    event = activity(client, workspace)[0]
    assert event["data"] == {} and event["message"] is None


def test_readable_objects_expose_their_own_mutation_permissions(client, workspace):
    incident, group, service, user, headers = workspace
    read_team = create_team(service.group)
    add_user_to_team(read_team, user, role="viewer")
    service.team = read_team
    service.save()
    group.team = read_team
    group.save()
    IncidentService.create(incident=incident, service=service)
    response = client.get(f"/api/incidents/{incident.id}/affected-services", headers=headers)
    assert response.get_json()[0]["permissions"]["can_remove"] is False
    response = client.get(f"/api/incidents/{incident.id}/alert-groups", headers=headers)
    assert response.get_json()[0]["permissions"]["can_unlink"] is False
    assert client.delete(f"/api/incidents/{incident.id}/affected-services/{service.id}", headers=headers).status_code == 403


def test_resolution_conflict_preserves_saved_version(client, workspace):
    incident, _, _, _, headers = workspace
    url = f"/api/incidents/{incident.id}"
    payload = {"row_version": incident.row_version, "root_cause": "cause", "resolution_summary": "fix"}
    response = client.patch(url, json=payload, headers=headers)
    assert response.status_code == 200, response.get_json()
    payload["root_cause"] = "stale edit"
    assert client.patch(url, json=payload, headers=headers).status_code == 409
    saved = client.get(url, headers=headers).get_json()
    assert saved["root_cause"] == "cause"
    assert saved["resolution_summary"] == "fix"
