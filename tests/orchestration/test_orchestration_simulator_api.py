import copy

import pytest

from app.login import create_access_token
from app.modules.db.models import (
    Alert,
    AlertGroup,
    AutomationExecution,
    EventOrchestration,
    EventOrchestrationRule,
    EventOrchestrationVersion,
    OrchestrationExecution,
    OrchestrationIntakeToken,
    OrchestrationWebhookAction,
    PendingOrchestratedEvent,
)
from app.modules.db.orchestrations_repo import create_orchestration, get_or_create_draft, replace_draft_rules
from app.services.integrations.normalizers.alertmanager import normalize_alertmanager
from app.services.serializers.alerts import serialize_alert
from tests.factories import create_alert, create_group, create_route, create_team, create_user
from app.services.alerts import group_state
from app.services.orchestration.publication import publish_draft


@pytest.fixture(autouse=True)
def orchestration_api_tables(db):
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


def _fixture(group):
    user = create_user(group=group)
    orchestration = create_orchestration(
        group_id=group.id,
        name="api simulator",
        created_by_id=user.id,
    )
    draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(
        draft.id,
        [
            {
                "name": "critical",
                "condition_tree": {},
                "actions": [{"type": "set_severity", "value": "critical"}],
                "processing_mode": "continue",
            }
        ],
    )
    published = publish_draft(orchestration.id, actor_id=user.id)
    return orchestration, published


def _headers(user):
    token, _ = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def test_simulate_api_accepts_normalized_event(client, db):
    group = create_group()
    user = create_user(group=group, group_role="editor")
    orchestration, published = _fixture(group)

    response = client.post(
        f"/api/event-orchestrations/{orchestration.id}/simulate",
        headers=_headers(user),
        json={
            "version_id": published.id,
            "normalized_event": {
                "source": "webhook",
                "dedup_key": "api-1",
                "title": "API event",
                "labels": {},
                "payload": {},
            },
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["selected_normalizer"] == "normalized"
    assert body["final_context"]["event"]["severity"] == "critical"
    assert body["input_output_diff"]["changed"] is True
    assert any(
        change["path"] == "event.severity"
        and change["before"] is None
        and change["after"] == "critical"
        for change in body["input_output_diff"]["changes"]
    )
    assert OrchestrationExecution.select().count() == 0


def test_simulate_api_denies_group_viewer(client, db):
    group = create_group()
    viewer = create_user(group=group, group_role="viewer")
    orchestration, _ = _fixture(group)

    response = client.post(
        f"/api/event-orchestrations/{orchestration.id}/simulate",
        headers=_headers(viewer),
        json={
            "normalized_event": {
                "source": "webhook",
                "dedup_key": "api-2",
                "title": "API event",
                "labels": {},
            }
        },
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "forbidden"


@pytest.mark.parametrize(
    "input_format", ["single_alert", "webhook", "normalized", "alert_details"],
)
def test_simulate_api_accepts_data_copied_from_stored_alert(
    client, db, admin_headers, input_format,
):
    group = create_group()
    editor = create_user(group=group, group_role="editor")
    route = create_route(create_team(group), source="alertmanager")
    alert = create_alert(route)
    raw = {
        "status": "firing",
        "fingerprint": "stored-alert-1",
        "labels": {"alertname": "DiskFull", "severity": "warning"},
        "annotations": {"summary": "Disk full", "description": "Disk usage is high"},
        "startsAt": "2026-11-18T10:00:00Z",
    }
    for key, value in normalize_alertmanager({"alerts": [raw]})[0].items():
        if key != "team_slug":
            setattr(alert, key, value)
    alert.save()
    copied = serialize_alert(alert, include_payload=True)
    orchestration, _ = _fixture(group)
    if input_format == "normalized":
        request_body = {"normalized_event": copied}
    elif input_format == "alert_details":
        alert_group = AlertGroup.create(
            team=route.team,
            route=route,
            source=alert.source,
            group_key=alert.group_key,
            group_key_hash="simulation-test-group",
            title=alert.title,
        )
        alert.group = alert_group
        alert.save()
        group_state.recalculate_alert_group(alert_group)
        details = client.get(
            f"/api/alert-groups/{alert_group.id}", headers=admin_headers,
        )
        assert details.status_code == 200
        request_body = {
            "source": "alertmanager",
            "payload": details.get_json()["payload_summary"],
        }
    else:
        request_body = {
            "source": "alertmanager",
            "payload": (
                copied["payload"]
                if input_format == "single_alert"
                else {"alerts": [raw]}
            ),
        }
    original = copy.deepcopy(request_body)
    alert_count = Alert.select().count()

    response = client.post(
        f"/api/event-orchestrations/{orchestration.id}/simulate",
        headers=_headers(editor),
        json=request_body,
    )

    assert response.status_code == 200, response.get_json()
    result = response.get_json()
    assert result["executed"] is True
    assert result["normalized_event_count"] == 1
    event = result["initial_normalized_event"]
    assert event["source"] == "alertmanager"
    assert event["dedup_key"] == raw["fingerprint"]
    assert event["title"] == "Disk full"
    assert event["payload"] == raw
    assert result["final_context"]["event"]["severity"] == "critical"
    assert request_body == original
    assert Alert.select().count() == alert_count
    assert Alert.get_by_id(alert.id).severity == "warning"
    assert OrchestrationExecution.select().count() == 0
    assert PendingOrchestratedEvent.select().count() == 0
    assert AutomationExecution.select().count() == 0


@pytest.mark.parametrize(
    "request_body, expected_message",
    [
        ({"normalized_event": {"alertname": "DiskFull"}}, "source, dedup_key, title"),
        ({"normalized_event": {"labels": {}, "fingerprint": "raw-1"}}, "Alertmanager"),
        ({"source": "alertmanager", "payload": {"alerts": []}}, "non-empty array"),
        ({"source": "alertmanager", "payload": {"alerts": {}}}, "non-empty array"),
        (
            {
                "source": "alertmanager",
                "payload": {"latest_alert_id": 1, "latest_payload": "secret-input"},
            },
            "latest_payload must be an object",
        ),
        (
            {"source": "alertmanager", "payload": {"alerts": ["secret-input"]}},
            "alerts[0] must be an object",
        ),
        (
            {
                "source": "alertmanager",
                "payload": {"alerts": [{"labels": "secret-input"}]},
            },
            "alerts[0].labels",
        ),
        (
            {
                "source": "alertmanager",
                "payload": {"labels": {}, "annotations": "secret-input"},
            },
            "alerts[0].annotations",
        ),
        (
            {"source": "alertmanager", "payload": {"title": "secret-input"}},
            "single alert",
        ),
        (
            {
                "source": "alertmanager",
                "payload": {
                    "source": "alertmanager",
                    "dedup_key": "secret-input",
                    "title": "Disk full",
                },
            },
            "Select the Normalized event",
        ),
        (
            {
                "source": "alertmanager",
                "payload": {"labels": {}, "fingerprint": "raw-1"},
                "event_index": 1,
            },
            "event_index must be between 0 and 0",
        ),
    ],
)
def test_simulation_reports_actionable_input_errors(
    client, db, request_body, expected_message,
):
    group = create_group()
    editor = create_user(group=group, group_role="editor")
    orchestration, _ = _fixture(group)

    response = client.post(
        f"/api/event-orchestrations/{orchestration.id}/simulate",
        headers=_headers(editor),
        json=request_body,
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "orchestration_simulation_invalid"
    assert expected_message in body["message"]
    assert "secret-input" not in response.get_data(as_text=True)


def test_simulation_does_not_expose_normalizer_exception(client, db, monkeypatch):
    from app.services.orchestration import simulator

    def fail_normalization(*args, **kwargs):
        raise ValueError("secret-input from external payload")

    monkeypatch.setattr(simulator, "normalize_for_source", fail_normalization)
    group = create_group()
    editor = create_user(group=group, group_role="editor")
    orchestration, _ = _fixture(group)
    response = client.post(
        f"/api/event-orchestrations/{orchestration.id}/simulate",
        headers=_headers(editor),
        json={"source": "webhook", "payload": {"title": "Disk full"}},
    )

    assert response.status_code == 400
    assert "Check the selected input format" in response.get_json()["message"]
    assert "secret-input" not in response.get_data(as_text=True)


def test_replay_api_uses_stored_alert_without_creating_new_alert(client, db):
    group = create_group()
    editor = create_user(group=group, group_role="editor")
    team = create_team(group)
    route = create_route(team)
    alert = create_alert(route)
    orchestration, published = _fixture(group)

    response = client.post(
        f"/api/event-orchestrations/{orchestration.id}/replay",
        headers=_headers(editor),
        json={
            "alert_ids": [alert.id],
            "version_id": published.id,
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["count"] == 1
    assert body["successful"] == 1
    assert body["production_state_modified"] is False


def test_execution_and_shadow_metrics_api_are_visible_to_viewer(client, db):
    group = create_group()
    viewer = create_user(group=group, group_role="viewer")
    orchestration, published = _fixture(group)
    OrchestrationExecution.create(
        group=group,
        orchestration=orchestration,
        version=published,
        source="webhook",
        trace_json={"mode": "shadow", "result": {"context": {}}},
    )

    executions = client.get(
        f"/api/event-orchestrations/{orchestration.id}/executions?include_trace=1",
        headers=_headers(viewer),
    )
    metrics = client.get(
        f"/api/event-orchestrations/{orchestration.id}/shadow-metrics",
        headers=_headers(viewer),
    )

    assert executions.status_code == 200
    assert len(executions.get_json()) == 1
    assert metrics.status_code == 200
    assert metrics.get_json()["metrics"]["executions"] == 1


def test_replay_api_rejects_alert_from_another_group(client, db):
    owner_group = create_group(slug="sim-owner")
    foreign_group = create_group(slug="sim-foreign")
    editor = create_user(group=owner_group, group_role="editor")
    foreign_team = create_team(foreign_group)
    foreign_route = create_route(foreign_team)
    foreign_alert = create_alert(foreign_route)
    orchestration, published = _fixture(owner_group)

    response = client.post(
        f"/api/event-orchestrations/{orchestration.id}/replay",
        headers=_headers(editor),
        json={
            "alert_ids": [foreign_alert.id],
            "version_id": published.id,
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "orchestration_simulation_invalid"
    assert response.get_json()["message"] == "Orchestration simulation failed."


def test_simulate_api_rejects_ambiguous_input(client, db):
    group = create_group()
    editor = create_user(group=group, group_role="editor")
    orchestration, _ = _fixture(group)

    response = client.post(
        f"/api/event-orchestrations/{orchestration.id}/simulate",
        headers=_headers(editor),
        json={
            "source": "webhook",
            "payload": {"title": "raw"},
            "normalized_event": {
                "source": "webhook",
                "dedup_key": "ambiguous",
                "title": "normalized",
            },
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


def test_simulate_api_rejects_unauthenticated_request(client, db):
    group = create_group()
    orchestration, _ = _fixture(group)

    response = client.post(
        f"/api/event-orchestrations/{orchestration.id}/simulate",
        json={
            "normalized_event": {
                "source": "webhook",
                "dedup_key": "anonymous",
                "title": "Anonymous event",
                "labels": {},
            }
        },
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "JWT or API token authentication is required"
