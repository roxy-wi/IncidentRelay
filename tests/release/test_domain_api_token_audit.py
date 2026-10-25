"""API-token attribution must survive service-owned and nested audit writes."""

from app.modules.db import tokens_repo
from app.modules.db.models import AlertGroup, AuditLog
from app.services.integrations.auth import hash_token
from tests.factories import create_group, create_route, create_team, unique


def _token_headers(user):
    raw = unique("domain-audit-token")
    token = tokens_repo.create_token(
        name=unique("domain-audit"),
        token_prefix=raw[:12],
        token_hash=hash_token(raw),
        scopes=["incidents:write", "alerts:write"],
        user=user.id,
    )
    return {"Authorization": f"Bearer {raw}"}, token


def _alert_group(team):
    route = create_route(team)
    key = unique("audit-group")
    return AlertGroup.create(
        team=team,
        route=route,
        source=route.source,
        group_key_hash=key,
        group_key=key,
        title="Audit attribution",
        message="test",
        severity="warning",
        status="firing",
        alert_count=1,
        firing_count=1,
        common_labels={},
        label_values={},
        payload_summary={},
    )


def _audit(group_or_incident_id, action):
    return AuditLog.get(
        AuditLog.action == action,
        AuditLog.object_id == group_or_incident_id,
    )


def test_incident_create_and_status_keep_personal_api_token(client, db, admin_user):
    team = create_team(create_group())
    headers, token = _token_headers(admin_user)

    created = client.post(
        "/api/incidents",
        headers=headers,
        json={"team_id": team.id, "title": "Token-sourced incident"},
    )
    assert created.status_code == 201, created.get_json()
    incident_id = created.get_json()["id"]

    declared_audit = _audit(incident_id, "incident.declare")
    assert declared_audit.api_token_id == token.id
    assert declared_audit.user_id == admin_user.id
    assert declared_audit.data["source"] == "api"

    updated = client.post(
        f"/api/incidents/{incident_id}/status",
        headers=headers,
        json={"row_version": created.get_json()["row_version"], "status": "investigating"},
    )
    assert updated.status_code == 200, updated.get_json()
    transition_audit = _audit(incident_id, "incident.status_change")
    assert transition_audit.api_token_id == token.id
    assert transition_audit.user_id == admin_user.id
    assert transition_audit.data["source"] == "api"


def test_create_incident_from_alert_group_keeps_token_on_nested_audits(
    client, db, admin_user,
):
    team = create_team(create_group())
    group = _alert_group(team)
    headers, token = _token_headers(admin_user)

    response = client.post(
        f"/api/alert-groups/{group.id}/create-incident",
        json={},
        headers=headers,
    )
    assert response.status_code == 201, response.get_json()
    incident_id = response.get_json()["id"]
    for action in ("incident.declare", "incident.group_link"):
        record = _audit(incident_id, action)
        assert record.api_token_id == token.id
        assert record.user_id == admin_user.id
        assert record.data["source"] == "api"


def test_shelve_then_resolve_keeps_token_on_nested_unshelve_audit(
    client, db, admin_user, monkeypatch,
):
    team = create_team(create_group())
    group = _alert_group(team)
    headers, token = _token_headers(admin_user)

    # This test checks local persistence, not outbound delivery.
    monkeypatch.setattr(
        "app.services.alerts.actions.update_alert_messages",
        lambda *args, **kwargs: None,
    )

    shelved = client.post(
        f"/api/alert-groups/{group.id}/shelve",
        headers=headers,
        json={"duration_seconds": 3600},
    )
    assert shelved.status_code == 200, shelved.get_json()

    resolved = client.post(
        f"/api/alert-groups/{group.id}/resolve",
        headers=headers,
        json={},
    )
    assert resolved.status_code == 200, resolved.get_json()

    for action in ("alert_group.shelve", "alert_group.unshelve", "alert_group.resolve"):
        record = _audit(group.id, action)
        assert record.api_token_id == token.id
        assert record.user_id == admin_user.id
    assert _audit(group.id, "alert_group.unshelve").data["source"] == "resolve"
