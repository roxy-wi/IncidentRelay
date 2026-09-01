import copy

import pytest

from app.modules.db.models import (
    Alert,
    AlertExplainStep,
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
    set_runtime_state,
)
from app.services.alerts.lifecycle import upsert_alert
from app.services.orchestration.simulator import (
    OrchestrationSimulationError,
    list_executions,
    normalize_simulation_payload,
    replay_events,
    shadow_metrics,
    simulate_event,
)
from app.services.orchestration.webhooks import create_webhook_action
from app.settings import Config
from tests.factories import (
    create_alert,
    create_group,
    create_route,
    create_team,
    create_user,
)


@pytest.fixture(autouse=True)
def orchestration_simulator_tables(db):
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


def _rule(title, *, extra_actions=None):
    return [
        {
            "name": title,
            "condition_tree": {},
            "actions": [
                {"type": "set_title", "value": title},
                *(extra_actions or []),
            ],
            "processing_mode": "continue",
        }
    ]


def _published_orchestration(group, *, title="published", mode="active"):
    user = create_user(group=group)
    orchestration = create_orchestration(
        group_id=group.id,
        name=f"sim-{title}",
        created_by_id=user.id,
    )
    draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(draft.id, _rule(title))
    published = publish_draft(orchestration.id, actor_id=user.id)
    set_runtime_state(
        orchestration.id,
        enabled=True,
        mode=mode,
        compatibility_mode="hybrid",
    )
    return orchestration, published, user


def _event(route, *, title="original", dedup="sim-1"):
    return {
        "source": route.source,
        "forced_route_id": route.id,
        "dedup_key": dedup,
        "external_id": dedup,
        "title": title,
        "message": "message",
        "severity": "warning",
        "status": "firing",
        "labels": {"environment": "prod"},
        "payload": {"token": "must-not-leak"},
    }


def test_simulate_draft_compares_with_active_without_persisting_state(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team)
    orchestration, published, user = _published_orchestration(group)

    draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(
        draft.id,
        _rule(
            "draft",
            extra_actions=[
                {"type": "set_severity", "value": "critical"},
                {"type": "suppress", "reason": "maintenance candidate"},
            ],
        ),
    )

    event = _event(route)
    original = copy.deepcopy(event)
    result = simulate_event(
        orchestration.id,
        event,
        version_id=draft.id,
        compare_with_active=True,
    )

    assert result["executed"] is True
    assert result["version_id"] == draft.id
    assert result["final_context"]["event"]["title"] == "draft"
    assert result["active"]["version_id"] == published.id
    assert result["active"]["final_context"]["event"]["title"] == "published"
    assert result["active_draft_diff"]["changed"] is True
    assert result["input_output_diff"]["changed"] is True
    changed_paths = {change["path"] for change in result["input_output_diff"]["changes"]}
    assert "event.title" in changed_paths
    assert "event.severity" in changed_paths
    assert result["disposition"]["type"] == "suppress"
    assert result["initial_context"]["raw"]["token"] == "***REDACTED***"
    assert event == original
    assert OrchestrationExecution.select().count() == 0
    assert PendingOrchestratedEvent.select().count() == 0
    assert AutomationExecution.select().count() == 0


def test_raw_alertmanager_payload_reports_selected_normalizer(db):
    source, event, count = normalize_simulation_payload(
        source="alertmanager",
        payload={
            "alerts": [
                {
                    "status": "firing",
                    "fingerprint": "fingerprint-1",
                    "labels": {"alertname": "DiskFull", "severity": "critical"},
                    "annotations": {"summary": "Disk full"},
                }
            ]
        },
    )

    assert source == "alertmanager"
    assert count == 1
    assert event["dedup_key"] == "fingerprint-1"
    assert event["title"] == "Disk full"


def test_replay_alert_and_execution_never_modify_production_state(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team)
    orchestration, published, _ = _published_orchestration(group)
    alert = create_alert(route)
    execution = OrchestrationExecution.create(
        group=group,
        orchestration=orchestration,
        version=published,
        source="alertmanager",
        event_fingerprint="execution-event",
        matched_rule_count=0,
        trace_json={
            "mode": "shadow",
            "initial_context": {
                "event": _event(route, dedup="execution-event"),
                "raw": {},
            },
        },
    )

    alert_count = Alert.select().count()
    execution_count = OrchestrationExecution.select().count()
    result = replay_events(
        orchestration.id,
        alert_ids=[alert.id],
        execution_ids=[execution.id],
        version_id=published.id,
    )

    assert result["count"] == 2
    assert result["successful"] == 2
    assert result["production_state_modified"] is False
    assert Alert.select().count() == alert_count
    assert OrchestrationExecution.select().count() == execution_count
    assert AutomationExecution.select().count() == 0


def test_shadow_execution_records_actual_result_metrics_and_full_explain(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team)
    orchestration, _, _ = _published_orchestration(
        group,
        title="shadow-title",
        mode="shadow",
    )

    result = upsert_alert(_event(route, title="actual-title", dedup="shadow-1"))

    execution = OrchestrationExecution.get()
    assert execution.trace_json["mode"] == "shadow"
    assert execution.trace_json["actual_result"]["route_id"] == route.id
    assert execution.trace_json["actual_result"]["title"] == "actual-title"

    metrics = shadow_metrics(orchestration.id)
    assert metrics["metrics"]["executions"] == 1
    assert metrics["metrics"]["title_changes"] == 1
    assert metrics["metrics"]["routing_changes"] == 0

    explain = (
        AlertExplainStep.select()
        .where(
            (AlertExplainStep.trace == result.trace.row.id)
            & (AlertExplainStep.stage == "orchestration")
        )
        .order_by(AlertExplainStep.position.asc())
        .first()
    )
    executions = explain.data["orchestration"]["executions"]
    assert executions[0]["trace"]["result"]["rules"][0]["matched"] is True


def test_list_executions_redacts_trace_secrets(db):
    group = create_group()
    orchestration, published, _ = _published_orchestration(group)
    execution = OrchestrationExecution.create(
        group=group,
        orchestration=orchestration,
        version=published,
        source="webhook",
        trace_json={"initial_context": {"raw": {"api_token": "secret"}}},
    )

    rows = list_executions(
        orchestration.id,
        include_trace=True,
    )

    assert rows[0]["id"] == execution.id
    assert rows[0]["trace"]["initial_context"]["raw"]["api_token"] == "***REDACTED***"


def test_simulation_never_enqueues_webhook_actions(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team)
    user = create_user(group=group)
    action = create_webhook_action(
        group_id=group.id,
        name="simulated diagnostics",
        url="https://example.test/diagnostics",
    )
    orchestration = create_orchestration(
        group_id=group.id,
        name="simulated-webhook",
        created_by_id=user.id,
    )
    draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(
        draft.id,
        _rule(
            "simulate only",
            extra_actions=[
                {"type": "enqueue_webhook", "action_id": action.id},
            ],
        ),
    )

    result = simulate_event(
        orchestration.id,
        _event(route, dedup="sim-webhook"),
        version_id=draft.id,
    )

    assert result["executed"] is True
    requests = result["final_context"]["result"]["webhooks"]
    assert requests == [{"action_id": action.id}]
    assert AutomationExecution.select().count() == 0
    assert OrchestrationExecution.select().count() == 0


def test_simulation_rejects_oversized_payload(monkeypatch):
    monkeypatch.setattr(Config, "ORCHESTRATION_SIMULATION_MAX_PAYLOAD_BYTES", 1024)

    with pytest.raises(OrchestrationSimulationError, match="simulation limit"):
        normalize_simulation_payload(
            source="webhook",
            payload={"title": "x" * 2048},
        )


def test_shadow_metrics_do_not_compare_legacy_rows_without_actual_result(db):
    group = create_group()
    orchestration, published, _ = _published_orchestration(group, mode="shadow")
    OrchestrationExecution.create(
        group=group,
        orchestration=orchestration,
        version=published,
        source="webhook",
        trace_json={
            "mode": "shadow",
            "result": {
                "context": {
                    "event": {"title": "candidate"},
                    "result": {},
                }
            },
        },
    )

    result = shadow_metrics(orchestration.id)

    assert result["metrics"]["executions"] == 1
    assert result["metrics"]["comparable_executions"] == 0
    assert result["metrics"]["not_comparable"] == 1
    assert result["metrics"]["title_changes"] == 0


def test_active_comparison_uses_one_time_snapshot(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team)
    orchestration, published, _ = _published_orchestration(group, title="same")

    result = simulate_event(
        orchestration.id,
        _event(route, dedup="same-time"),
        version_id=published.id,
        compare_with_active=True,
    )

    assert result["evaluated_at"] == result["active"]["evaluated_at"]
    assert result["active_draft_diff"]["changed"] is False


def test_replay_reports_high_drop_rate_without_applying_it(db, monkeypatch):
    group = create_group()
    team = create_team(group)
    route = create_route(team)
    user = create_user(group=group)
    orchestration = create_orchestration(
        group_id=group.id,
        name="drop-replay",
        created_by_id=user.id,
    )
    draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(
        draft.id,
        [
            {
                "name": "drop candidate",
                "condition_tree": {},
                "actions": [{"type": "drop", "reason": "candidate"}],
                "processing_mode": "continue",
            }
        ],
    )
    alert = create_alert(route)
    alert_count = Alert.select().count()
    monkeypatch.setattr(Config, "ORCHESTRATION_REPLAY_DROP_WARNING_PERCENT", 50)

    result = replay_events(
        orchestration.id,
        alert_ids=[alert.id],
        version_id=draft.id,
    )

    assert result["summary"]["dispositions"] == {"drop": 1}
    assert result["summary"]["drop_percentage"] == 100.0
    assert result["warnings"][0]["code"] == "high_drop_rate"
    assert Alert.select().count() == alert_count
