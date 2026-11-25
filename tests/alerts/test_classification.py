from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Barrier
from unittest.mock import patch

import pytest

from app.login import create_access_token
from app.api.openapi.spec import build_openapi_spec
from app.modules.db import tokens_repo
from app.modules.db.models import AlertEvent, AlertGroup, AlertGroupReview, AuditLog, Incident, IncidentAlertGroupLink
from app.modules.token_hashing import hash_token
from tests.factories import add_user_to_team, create_group, create_team, create_user, unique


def signal(team):
    key = unique("classification")
    return AlertGroup.create(team=team, source="manual", group_key=key, group_key_hash=key, title=key)


def path(group):
    return f"/api/alert-groups/{group.id}/classification"


def headers(user):
    return {"Authorization": f"Bearer {create_access_token(user)[0]}"}


@pytest.mark.parametrize("outcome", ["false_positive", "known_issue", "no_action_required",
                                    "planned_activity", "test_alert", "other"])
def test_optional_review_records_author_time_and_history(client, admin_user, admin_headers, outcome):
    admin_user.color = "#274b7a"
    admin_user.save()
    group = signal(create_team(create_group()))
    url = path(group)
    assert client.get(url, headers=admin_headers).get_json()["version"] == 0
    data = {"classification": outcome, "version": 0, "note": "Initial review"}
    saved = client.put(url, headers=admin_headers, json=data)
    assert saved.status_code == 200, saved.get_json()
    review = saved.get_json()
    assert review["classified_by_id"] == admin_user.id
    assert review["classified_by_color"] == admin_user.color
    assert review["classified_at"].endswith("Z")
    assert review["version"] == 1
    assert client.put(url, headers=admin_headers, json={**data, "version": 1}).get_json() == review
    assert client.put(url, headers=admin_headers, json=data).status_code == 409
    changed = client.put(url, headers=admin_headers, json={**data, "version": 1, "note": "Updated"}).get_json()
    detail = client.get(f"/api/alert-groups/{group.id}", headers=admin_headers).get_json()
    assert detail["review"] == changed
    assert detail["status"] == group.status
    assert client.delete(url + "?version=1", headers=admin_headers).status_code == 409
    cleared = client.delete(url + "?version=2", headers=admin_headers).get_json()
    assert cleared["classification"] is cleared["classified_at"] is cleared["classified_by_id"] is None
    assert cleared["classified_by_color"] is None
    assert cleared["version"] == 3
    assert client.delete(url + "?version=3", headers=admin_headers).get_json() == cleared
    assert [e.event_type for e in AlertEvent.select().order_by(AlertEvent.id)] == [
        "alert_classification_set", "alert_classification_changed", "alert_classification_cleared",
    ]
    assert [a.action for a in AuditLog.select().order_by(AuditLog.id)] == [
        "alert_group.classification.set", "alert_group.classification.changed", "alert_group.classification.cleared",
    ]


def test_duplicate_requires_a_readable_canonical_target(client, admin_headers):
    own, other = create_team(create_group()), create_team(create_group())
    a, b = signal(own), signal(other)
    responder = create_user(group=own.group, group_role="viewer")
    add_user_to_team(own, responder, "responder")
    data = {"version": 0, "classification": "duplicate"}
    for invalid in ({}, {"canonical_group_id": a.id}, {"incident_id": 12, "canonical_group_id": b.id}):
        assert client.put(path(a), headers=admin_headers, json={**data, **invalid}).status_code == 400
    choice = {**data, "canonical_group_id": b.id}
    assert client.put(path(a), headers=headers(responder), json=choice).status_code == 404
    assert client.put(path(a), headers=admin_headers, json=choice).get_json()["canonical_group_id"] == b.id
    assert client.get(path(a), headers=headers(responder)).get_json()["canonical_group_id"] is None
    assert client.put(path(b), headers=admin_headers, json={**data, "canonical_group_id": a.id}).status_code == 400
    incident = Incident.create(team=other, title="Canonical")
    changed = client.put(path(a), headers=admin_headers, json={**data, "version": 1, "incident_id": incident.id})
    assert changed.get_json()["incident_id"] == incident.id
    assert not IncidentAlertGroupLink.select().exists()
    assert client.get(path(a), headers=headers(responder)).get_json()["incident_id"] is None


def test_permissions_and_incident_token_scope(client, db):
    team = create_team(create_group())
    group = signal(team)
    user = create_user(group=team.group, group_role="viewer")
    add_user_to_team(team, user, "viewer")
    data = {"version": 0, "classification": "known_issue"}
    assert not client.get(path(group), headers=headers(user)).get_json()["can_classify"]
    assert client.put(path(group), headers=headers(user), json=data).status_code == 403
    editor = create_user(group=team.group, group_role="editor")
    assert client.put(path(group), headers=headers(editor), json=data).status_code == 200
    add_user_to_team(team, editor, "responder")
    raw = unique("classification-token")
    tokens_repo.create_api_token("review", raw[:8], hash_token(raw), ["alerts:write", "incidents:read"],
                                 user_id=editor.id, team_id=team.id)
    incident = Incident.create(team=team, title="Existing")
    response = client.put(path(group), headers={"Authorization": f"Bearer {raw}"}, json={
        "version": 1, "classification": "incident", "incident_id": incident.id,
    })
    assert response.status_code == 403
    assert not IncidentAlertGroupLink.select().exists()
    scoped = {"Authorization": f"Bearer {raw}"}
    assert client.put(path(group), headers=scoped, json={**data, "version": 1, "note": "Token review"}).status_code == 200
    audit = AuditLog.get(AuditLog.action == "alert_group.classification.changed")
    assert audit.user_id == editor.id and audit.api_token_id is not None
    assert audit.data["source"] == "api"
    outside = signal(create_team(team.group))
    assert client.put(path(outside), headers=scoped, json=data).status_code == 403


def test_incident_selection_creation_and_rollback(client, admin_headers):
    team = create_team(create_group())
    group = signal(team)
    missing_target = client.put(path(group), headers=admin_headers, json={"version": 0, "classification": "incident"})
    assert missing_target.status_code == 400
    data = {"version": 0, "classification": "incident", "create_incident": True}
    with (
        patch("app.services.alerts.classification.record_audit", side_effect=RuntimeError("audit failed")) as audit,
        patch("app.services.alerts.classification.notify_stakeholders") as notify,
    ):
        response = client.put(path(group), headers=admin_headers, json=data)
        assert response.status_code == 500, response.get_json()
        audit.assert_called_once()
        notify.assert_not_called()
    assert not Incident.select().exists()
    assert not AlertGroupReview.select().exists()
    assert not AlertEvent.select().exists()
    created = client.put(path(group), headers=admin_headers, json=data)
    assert created.status_code == 200, created.get_json()
    incident_id = created.get_json()["incident_id"]
    assert IncidentAlertGroupLink.get().relation_type == "primary"
    assert client.put(path(group), headers=admin_headers, json=data).status_code == 409
    assert Incident.select().count() == 1
    second = signal(team)
    attached = client.put(path(second), headers=admin_headers, json={
        "version": 0, "classification": "incident", "incident_id": incident_id,
    })
    assert attached.status_code == 200
    assert client.delete(path(second) + "?version=1", headers=admin_headers).status_code == 200
    assert IncidentAlertGroupLink.select().where(IncidentAlertGroupLink.removed_at.is_null()).count() == 2


def test_two_reviewers_writing_the_same_version(app, admin_headers):
    group = signal(create_team(create_group()))
    barrier = Barrier(2)

    def submit(outcome):
        with app.test_client() as client:
            barrier.wait(timeout=10)
            return client.put(path(group), headers=admin_headers, json={
                "classification": outcome, "version": 0,
            }).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, ["test_alert", "false_positive"])) == [200, 409]
    assert AlertGroupReview.get().version == 1
    assert AlertEvent.select().count() == 1


def test_review_migration_preserves_existing_groups_and_assessments(client, admin_headers):
    migration = import_module("app.migrations.20261125010000_alert_group_review")
    group = signal(create_team(create_group()))
    migration.downgrade()
    migration.upgrade()
    migration.upgrade()
    assert AlertGroup.get_by_id(group.id).status == group.status
    assert not AlertGroupReview.select().exists()
    client.put(path(group), headers=admin_headers, json={"classification": "other", "version": 0})
    with pytest.raises(RuntimeError, match="stored AlertGroup reviews"):
        migration.downgrade()
    assert AlertGroupReview.get().classification == "other"


def test_concurrent_duplicate_targets_cannot_form_a_cycle(app, admin_headers):
    team = create_team(create_group())
    a, b = signal(team), signal(team)
    barrier = Barrier(2)

    def classify(pair):
        group, target = pair
        with app.test_client() as client:
            barrier.wait(timeout=10)
            return client.put(path(group), headers=admin_headers, json={
                "version": 0, "classification": "duplicate", "canonical_group_id": target.id,
            }).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(classify, [(a, b), (b, a)])) == [200, 400]
    assert AlertGroupReview.select().count() == AlertEvent.select().count() == 1


def test_classification_openapi_matches_detail_contract():
    paths = build_openapi_spec()["paths"]
    resource = paths["/api/alert-groups/{alert_id}/classification"]
    read_schema = resource["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    detail = paths["/api/alert-groups/{alert_id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert detail["properties"]["review"] == read_schema
    update = resource["put"]["requestBody"]["content"]["application/json"]["schema"]
    assert update["required"] == ["version", "classification"]
    assert len(update["properties"]["classification"]["enum"]) == 8
    assert "409" in resource["delete"]["responses"]
