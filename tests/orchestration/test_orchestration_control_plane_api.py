import pytest

from app.login import create_access_token
from app.modules.crypto import decrypt_json
from app.modules.db.models import (
    AutomationExecution,
    EventOrchestration,
    EventOrchestrationRule,
    EventOrchestrationVersion,
    OrchestrationExecution,
    OrchestrationIntakeToken,
    OrchestrationWebhookAction,
    PendingOrchestratedEvent,
)
from tests.factories import create_group, create_user


@pytest.fixture(autouse=True)
def orchestration_control_plane_tables(db):
    db.create_tables(
        [
            EventOrchestration,
            EventOrchestrationVersion,
            EventOrchestrationRule,
            OrchestrationIntakeToken,
            OrchestrationExecution,
            PendingOrchestratedEvent,
            OrchestrationWebhookAction,
            AutomationExecution,
        ],
        safe=True,
    )
    AutomationExecution.delete().execute()
    OrchestrationWebhookAction.delete().execute()
    PendingOrchestratedEvent.delete().execute()
    OrchestrationExecution.delete().execute()
    EventOrchestrationRule.delete().execute()
    EventOrchestrationVersion.delete().execute()
    OrchestrationIntakeToken.delete().execute()
    EventOrchestration.delete().execute()
    yield


def _headers(user):
    token, _ = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def _rule(name="critical"):
    return {
        "name": name,
        "description": "Set incident severity",
        "enabled": True,
        "condition_tree": {
            "all": [
                {
                    "field": "labels.environment",
                    "operator": "equals",
                    "value": "production",
                }
            ]
        },
        "actions": [{"type": "set_severity", "value": "critical"}],
        "processing_mode": "continue",
        "children": [],
    }


def test_admin_can_manage_full_orchestration_lifecycle(client, db, admin_headers):
    group = create_group(slug="control-plane")

    created = client.post(
        "/api/event-orchestrations",
        headers=admin_headers,
        json={
            "group_id": group.id,
            "name": "Production routing",
            "description": "Control-plane test",
            "scope": "global",
            "compatibility_mode": "legacy",
        },
    )

    assert created.status_code == 201
    orchestration = created.get_json()
    orchestration_id = orchestration["id"]
    assert orchestration["draft"]["definition"]["rules"] == []
    assert orchestration["permissions"]["publish"] is True

    saved = client.put(
        f"/api/event-orchestrations/{orchestration_id}/draft",
        headers=admin_headers,
        json={"rules": [_rule()], "comment": "Ready for validation"},
    )

    assert saved.status_code == 200
    saved_body = saved.get_json()
    assert saved_body["comment"] == "Ready for validation"
    assert saved_body["definition"]["rules"][0]["name"] == "critical"

    validation = client.post(
        f"/api/event-orchestrations/{orchestration_id}/validate",
        headers=admin_headers,
        json={},
    )
    assert validation.status_code == 200
    assert validation.get_json()["valid"] is True

    published = client.post(
        f"/api/event-orchestrations/{orchestration_id}/publish",
        headers=admin_headers,
        json={"comment": "Initial production version"},
    )
    assert published.status_code == 200
    published_body = published.get_json()
    assert published_body["status"] == "published"

    runtime = client.patch(
        f"/api/event-orchestrations/{orchestration_id}/runtime",
        headers=admin_headers,
        json={"mode": "shadow", "compatibility_mode": "hybrid"},
    )
    assert runtime.status_code == 200
    runtime_body = runtime.get_json()
    assert runtime_body["enabled"] is True
    assert runtime_body["mode"] == "shadow"
    assert runtime_body["compatibility_mode"] == "hybrid"

    versions = client.get(
        f"/api/event-orchestrations/{orchestration_id}/versions",
        headers=admin_headers,
    )
    assert versions.status_code == 200
    assert len(versions.get_json()["items"]) == 1

    rollback = client.post(
        f"/api/event-orchestrations/{orchestration_id}/rollback",
        headers=admin_headers,
        json={
            "version_id": published_body["id"],
            "comment": "Rollback copy",
        },
    )
    assert rollback.status_code == 200
    assert rollback.get_json()["version_number"] == 2
    assert rollback.get_json()["status"] == "published"

    deleted = client.delete(
        f"/api/event-orchestrations/{orchestration_id}",
        headers=admin_headers,
    )
    assert deleted.status_code == 200
    assert deleted.get_json()["deleted"] is True

    missing = client.get(
        f"/api/event-orchestrations/{orchestration_id}",
        headers=admin_headers,
    )
    assert missing.status_code == 404


def test_editor_can_edit_but_cannot_publish(client, db):
    group = create_group(slug="editor-group")
    editor = create_user(group=group, group_role="editor")
    headers = _headers(editor)

    created = client.post(
        "/api/event-orchestrations",
        headers=headers,
        json={"group_id": group.id, "name": "Editor draft"},
    )
    assert created.status_code == 201
    orchestration_id = created.get_json()["id"]

    saved = client.put(
        f"/api/event-orchestrations/{orchestration_id}/draft",
        headers=headers,
        json={"rules": [_rule()]},
    )
    assert saved.status_code == 200

    denied = client.post(
        f"/api/event-orchestrations/{orchestration_id}/publish",
        headers=headers,
        json={},
    )
    assert denied.status_code == 403
    assert denied.get_json()["error"] == "forbidden"


def test_list_and_get_do_not_cross_group_boundaries(client, db):
    owner_group = create_group(slug="owner-control")
    foreign_group = create_group(slug="foreign-control")
    owner = create_user(group=owner_group, group_role="editor")
    foreign = create_user(group=foreign_group, group_role="viewer")

    created = client.post(
        "/api/event-orchestrations",
        headers=_headers(owner),
        json={"group_id": owner_group.id, "name": "Owner only"},
    )
    orchestration_id = created.get_json()["id"]

    listed = client.get(
        f"/api/event-orchestrations?group_id={foreign_group.id}",
        headers=_headers(foreign),
    )
    assert listed.status_code == 200
    assert listed.get_json()["items"] == []

    denied = client.get(
        f"/api/event-orchestrations/{orchestration_id}",
        headers=_headers(foreign),
    )
    assert denied.status_code == 403


def test_webhook_action_api_never_returns_secret_headers(client, db, admin_headers):
    group = create_group(slug="webhook-control")

    created = client.post(
        "/api/orchestration-webhook-actions",
        headers=admin_headers,
        json={
            "group_id": group.id,
            "name": "Diagnostics",
            "url": "https://hooks.example.test/diagnostics",
            "method": "POST",
            "headers": {"Authorization": "Bearer super-secret"},
            "body_template": '{"title":"{{ event.title }}"}',
            "timeout_seconds": 10,
            "retry_count": 2,
            "private_network_policy": "deny",
        },
    )

    assert created.status_code == 201
    payload = created.get_json()
    action_id = payload["id"]
    serialized = str(payload)
    assert payload["has_headers"] is True
    assert "headers" not in payload
    assert "super-secret" not in serialized
    assert payload["created_at"]

    action = OrchestrationWebhookAction.get_by_id(action_id)
    assert decrypt_json(action.headers_encrypted)["Authorization"] == "Bearer super-secret"

    updated = client.patch(
        f"/api/orchestration-webhook-actions/{action_id}",
        headers=admin_headers,
        json={"name": "Diagnostics updated", "retry_count": 3},
    )
    assert updated.status_code == 200
    assert updated.get_json()["name"] == "Diagnostics updated"
    action = OrchestrationWebhookAction.get_by_id(action_id)
    assert decrypt_json(action.headers_encrypted)["Authorization"] == "Bearer super-secret"

    listed = client.get(
        f"/api/orchestration-webhook-actions?group_id={group.id}",
        headers=admin_headers,
    )
    assert listed.status_code == 200
    assert len(listed.get_json()["items"]) == 1
    assert "super-secret" not in str(listed.get_json())


def test_webhook_action_duplicate_name_returns_safe_conflict(client, db, admin_headers):
    group = create_group(slug="webhook-conflict")
    body = {
        "group_id": group.id,
        "name": "Duplicate",
        "url": "https://hooks.example.test/duplicate",
    }
    assert client.post(
        "/api/orchestration-webhook-actions",
        headers=admin_headers,
        json=body,
    ).status_code == 201

    duplicate = client.post(
        "/api/orchestration-webhook-actions",
        headers=admin_headers,
        json=body,
    )
    assert duplicate.status_code == 409
    payload = duplicate.get_json()
    assert payload["error"] == "webhook_action_conflict"
    assert "UNIQUE" not in str(payload).upper()
