"""Unified audit semantics for retroactive effects, draft operations and no-ops."""

from datetime import timedelta

import pytest

from app.modules.common import utc_now
from app.modules.db import silences_repo, tokens_repo
from app.modules.db.models import AlertEvent, AuditLog, HeartbeatPing
from app.services.alerts.lifecycle import upsert_alert
from app.services.alerts.maintenance_state import reconcile_maintenance_window
from app.services.integrations.auth import hash_token
from app.services.silences import reconcile_silence
from tests.factories import (
    create_group,
    create_heartbeat,
    create_route,
    create_silence,
    create_team,
    unique,
)
from tests.services.test_maintenance_retroactive import _window
from tests.services.test_maintenance_windows import (
    create_manager_context,
    create_test_alert_group,
)


def _event_audits(action):
    return list(AuditLog.select().where(AuditLog.action == action))


def _api_token(admin_user):
    secret = unique("audit-token")
    token = tokens_repo.create_token(
        name=unique("audit"),
        token_prefix=secret[:12],
        token_hash=hash_token(secret),
        scopes=["*"],
        user=admin_user.id,
    )
    return token, {"Authorization": f"Bearer {secret}"}


def test_retroactive_silence_audit_keeps_manual_actor_and_token(db, admin_user):
    group = create_group()
    team = create_team(group)
    create_route(team)
    actor = admin_user
    alert_result = upsert_alert({
        "source": "alertmanager",
        "team_slug": team.slug,
        "external_id": unique("source"),
        "dedup_key": unique("group"),
        "title": "DiskFull",
        "message": "disk is full",
        "severity": "critical",
        "labels": {"alertname": "DiskFull"},
        "payload": {},
        "status": "firing",
    })
    token, _headers = _api_token(admin_user)
    silence = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
        apply_to_existing=True,
    )

    applied = reconcile_silence(
        silence,
        trigger_source="api",
        actor_user_id=actor.id,
        api_token_id=token.id,
    )
    assert applied["silenced"] == 1
    record = AuditLog.get(
        AuditLog.action == "silence.alert_applied",
        AuditLog.object_type == "alert",
        AuditLog.object_id == alert_result.alert.id,
    )
    assert record.user_id == actor.id
    assert record.api_token_id == token.id
    assert record.data["trigger_source"] == "api"
    assert record.data["transport"] == "api"
    event = AlertEvent.get(
        AlertEvent.group == alert_result.group.id,
        AlertEvent.event_type == "silenced",
        AlertEvent.user == admin_user.id,
    )
    assert event.user_id == admin_user.id

    silence = silences_repo.disable_silence(silence.id)
    reconciled = reconcile_silence(silence, trigger_source="scheduler")
    assert reconciled["reactivated"] == 1
    restored = AuditLog.get(
        AuditLog.action == "silence.alert_reactivated",
        AuditLog.object_type == "alert",
        AuditLog.object_id == alert_result.alert.id,
    )
    assert restored.user_id is None
    assert restored.api_token_id is None
    assert restored.data["transport"] == "system"


def test_silence_api_token_flows_into_retroactive_alert_audit(
    client, db, admin_user,
):
    group = create_group()
    team = create_team(group)
    create_route(team)
    alert_result = upsert_alert({
        "source": "alertmanager",
        "team_slug": team.slug,
        "external_id": unique("external"),
        "dedup_key": unique("dedup"),
        "title": "DiskFull",
        "message": "out of disk space",
        "severity": "critical",
        "labels": {"alertname": "DiskFull"},
        "payload": {},
        "status": "firing",
    })
    token, headers = _api_token(admin_user)
    now = utc_now()
    response = client.post(
        "/api/silences",
        headers=headers,
        json={
            "team_id": team.id,
            "name": "Disk silence",
            "starts_at": (now - timedelta(minutes=5)).isoformat(),
            "ends_at": (now + timedelta(minutes=5)).isoformat(),
            "matchers": {"labels": {"alertname": "DiskFull"}},
            "apply_to_existing": True,
        },
    )
    assert response.status_code == 201, response.get_json()
    row = AuditLog.get(
        AuditLog.action == "silence.alert_applied",
        AuditLog.object_type == "alert",
        AuditLog.object_id == alert_result.alert.id,
    )
    assert row.user_id == admin_user.id
    assert row.api_token_id == token.id
    assert row.data["trigger_source"] == "api"


def test_silence_enable_disable_retries_have_no_extra_command_audit(
    client, admin_headers, db,
):
    team = create_team(create_group())
    silence = create_silence(team)

    url = f"/api/silences/{silence.id}"
    assert client.post(f"{url}/enable", headers=admin_headers).status_code == 200
    assert not _event_audits("silence.enable")

    assert client.delete(url, headers=admin_headers).status_code == 200
    assert client.delete(url, headers=admin_headers).status_code == 200
    assert len(_event_audits("silence.disable")) == 1

    assert client.post(f"{url}/enable", headers=admin_headers).status_code == 200
    assert client.post(f"{url}/enable", headers=admin_headers).status_code == 200
    assert len(_event_audits("silence.enable")) == 1


def test_maintenance_api_reconciliation_records_actor_and_token(db, admin_user):
    _group, team, route, service, _actor, _headers = create_manager_context()
    actor = admin_user
    alert = create_test_alert_group(
        route=route, service=service, suffix="operator-attribution"
    )
    window = _window(team, service, apply=True)
    token, _headers = _api_token(admin_user)

    first = reconcile_maintenance_window(
        window,
        trigger_source="api",
        actor_user_id=actor.id,
        api_token_id=token.id,
    )
    assert first["applied"] == 1
    record = AuditLog.get(
        AuditLog.action == "maintenance_window.alert_group_applied",
        AuditLog.object_id == alert.id,
    )
    assert record.user_id == actor.id
    assert record.api_token_id == token.id
    assert record.data["trigger_source"] == "api"

    # A subsequent scheduler release must NOT impersonate the user who
    # originally created/edited the maintenance window.
    reconcile_maintenance_window(
        window,
        now=window.ends_at + timedelta(seconds=1),
        trigger_source="scheduler",
    )
    released = AuditLog.get(
        AuditLog.action == "maintenance_window.alert_group_released",
        AuditLog.object_id == alert.id,
    )
    assert released.user_id is None
    assert released.api_token_id is None
    assert released.data["transport"] == "system"
    event = AlertEvent.get(
        AlertEvent.group == alert.id,
        AlertEvent.event_type == "maintenance_applied",
    )
    assert event.user_id == actor.id


def test_retained_silence_reconciliation_does_not_repeat_audit(db):
    team = create_team(create_group())
    create_route(team)
    silence = create_silence(
        team,
        matchers={"labels": {"alertname": "DiskFull"}},
        reactivate_on_end=False,
    )
    upsert_alert({
        "source": "alertmanager",
        "team_slug": team.slug,
        "external_id": unique("retained-source"),
        "dedup_key": unique("retained-dedup"),
        "title": "DiskFull",
        "message": "out of disk space",
        "severity": "critical",
        "labels": {"alertname": "DiskFull"},
        "payload": {},
        "status": "firing",
    })
    silence = silences_repo.disable_silence(silence.id)
    reconcile_silence(silence, trigger_source="api")
    reconcile_silence(silence, trigger_source="api")
    assert len(_event_audits("silence.alerts_retained")) == 1


def test_maintenance_http_api_token_flows_to_application_audit(
    client, db, admin_user,
):
    _group, team, route, service, _manager, _headers = create_manager_context()
    affected = create_test_alert_group(
        route=route, service=service, suffix="api-token-maintenance"
    )
    token, headers = _api_token(admin_user)
    now = utc_now()
    result = client.post(
        "/api/maintenance-windows",
        headers=headers,
        json={
            "name": "Operator maintenance",
            "behavior": "suppress_notifications",
            "timezone": "UTC",
            "starts_at": (now - timedelta(minutes=5)).isoformat(),
            "ends_at": (now + timedelta(minutes=30)).isoformat(),
            "apply_to_existing": True,
            "scopes": [{"scope_type": "service", "service_id": service.id}],
        },
    )
    assert result.status_code == 201, result.get_json()
    row = AuditLog.get(
        AuditLog.action == "maintenance_window.alert_group_applied",
        AuditLog.object_id == affected.id,
    )
    assert row.user_id == admin_user.id
    assert row.api_token_id == token.id
    assert row.data["trigger_source"] == "api"


def test_orchestration_draft_creation_and_validation_audited_once(
    client, admin_headers, db,
):
    group = create_group()
    created = client.post(
        "/api/event-orchestrations",
        headers=admin_headers,
        json={"group_id": group.id, "name": unique("draft-audit"), "scope": "global"},
    )
    assert created.status_code == 201, created.get_json()
    orchestration_id = created.get_json()["id"]

    validation = client.post(
        f"/api/event-orchestrations/{orchestration_id}/validate",
        headers=admin_headers,
        json={},
    )
    assert validation.status_code == 200, validation.get_json()
    record = _event_audits("event_orchestration.draft.validate")[0]
    assert record.data["orchestration_id"] == orchestration_id
    assert record.data["valid"] == validation.get_json()["valid"]
    assert "definition" not in record.data
    assert "rules" not in record.data

    # The initial draft is already created by POST /event-orchestrations.
    duplicate = client.post(
        f"/api/event-orchestrations/{orchestration_id}/draft",
        headers=admin_headers,
        json={},
    )
    assert duplicate.status_code == 200, duplicate.get_json()
    assert _event_audits("event_orchestration.draft.create") == []

    rule = {
        "name": "critical",
        "description": "",
        "enabled": True,
        "condition_tree": {
            "all": [{"field": "labels.environment", "operator": "equals", "value": "production"}]
        },
        "actions": [{"type": "set_severity", "value": "critical"}],
        "processing_mode": "continue",
        "children": [],
    }
    saved = client.put(
        f"/api/event-orchestrations/{orchestration_id}/draft",
        headers=admin_headers,
        json={"rules": [rule]},
    )
    assert saved.status_code == 200, saved.get_json()
    published = client.post(
        f"/api/event-orchestrations/{orchestration_id}/publish",
        headers=admin_headers,
        json={},
    )
    assert published.status_code == 200, published.get_json()

    new_draft = client.post(
        f"/api/event-orchestrations/{orchestration_id}/draft",
        headers=admin_headers,
        json={},
    )
    assert new_draft.status_code == 200, new_draft.get_json()
    assert len(_event_audits("event_orchestration.draft.create")) == 1

    repeated = client.post(
        f"/api/event-orchestrations/{orchestration_id}/draft",
        headers=admin_headers,
        json={},
    )
    assert repeated.status_code == 200, repeated.get_json()
    assert len(_event_audits("event_orchestration.draft.create")) == 1


def test_silence_command_and_audit_fail_as_one_transaction(
    client, admin_headers, db, monkeypatch,
):
    from app.views import silences_view
    from app.modules.db.models import Silence

    audit_calls = []

    def fail_audit(action, **_kwargs):
        audit_calls.append(action)
        raise RuntimeError("simulated audit database failure")

    team = create_team(create_group())
    monkeypatch.setattr(silences_view, "write_audit", fail_audit)
    now = utc_now()
    response = client.post(
        "/api/silences",
        headers=admin_headers,
        json={
            "team_id": team.id,
            "name": "Audit rollback",
            "starts_at": now.isoformat(),
            "ends_at": (now + timedelta(minutes=5)).isoformat(),
        },
    )

    # The app's global Exception handler deliberately translates the injected
    # audit failure into a sanitized HTTP 500, even when TESTING=True.
    assert audit_calls == ["silence.create"], response.get_json()
    assert response.status_code == 500, response.get_json()
    assert response.get_json()["error"] == "Internal Server Error"
    assert Silence.select().count() == 0


def test_heartbeat_pause_resume_retry_is_noop_for_audit_and_ping_history(
    client, admin_headers, db,
):
    team = create_team(create_group())
    route = create_route(team, source="heartbeat")
    heartbeat = create_heartbeat(team, route)
    url = f"/api/heartbeats/{heartbeat.id}"

    first_pause = client.post(f"{url}/pause", headers=admin_headers)
    assert first_pause.status_code == 200, first_pause.get_json()
    assert client.post(f"{url}/pause", headers=admin_headers).status_code == 200
    assert len(_event_audits("heartbeat.pause")) == 1
    assert HeartbeatPing.select().where(
        HeartbeatPing.heartbeat == heartbeat.id,
        HeartbeatPing.event_type == "paused",
    ).count() == 1

    assert client.post(f"{url}/resume", headers=admin_headers).status_code == 200
    assert client.post(f"{url}/resume", headers=admin_headers).status_code == 200
    assert len(_event_audits("heartbeat.resume")) == 1
    assert HeartbeatPing.select().where(
        HeartbeatPing.heartbeat == heartbeat.id,
        HeartbeatPing.event_type == "resumed",
    ).count() == 1
