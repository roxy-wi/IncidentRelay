import pytest

from app.login import create_access_token
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
from app.modules.db.orchestrations_repo import (
    create_orchestration,
    get_or_create_draft,
    publish_draft,
    replace_draft_rules,
)
from tests.factories import create_alert, create_group, create_route, create_team, create_user


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

    assert response.status_code == 403
    assert response.get_json()["error"] == "forbidden"
