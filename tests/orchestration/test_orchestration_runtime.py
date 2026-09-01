import copy

import pytest

from app.modules.db import alerts_repo, incidents_repo
from app.modules.db.models import (
    EventOrchestration,
    EventOrchestrationRule,
    EventOrchestrationVersion,
    AlertExplainStep,
    AlertExplainTrace,
    OrchestrationExecution,
    OrchestrationIntakeToken,
    PendingOrchestratedEvent,
    ServiceMatchRule,
)
from app.modules.db.orchestrations_repo import (
    OrchestrationConflict,
    OrchestrationValidationError,
    create_orchestration,
    get_or_create_draft,
    publish_draft,
    replace_draft_rules,
    set_runtime_state,
)
from app.services.orchestration.cache import PublishedDefinitionCache
from app.services.orchestration.runtime import (
    attach_runtime_executions,
    run_event_orchestration,
    run_service_orchestration,
)
from app.services.alerts.lifecycle import upsert_alert
from app.services.notifications.policies.resolver import resolve_notification_channels
from app.services.routing.service_resolution import resolve_alert_service
from tests.factories import (
    create_channel,
    create_escalation_policy,
    create_escalation_policy_rule,
    create_group,
    create_notification_policy,
    create_notification_policy_rule,
    create_priority_policy,
    create_priority_policy_rule,
    create_route,
    create_service,
    create_team,
    create_user,
)


@pytest.fixture(autouse=True)
def orchestration_tables(db):
    db.create_tables(
        [
            EventOrchestration,
            EventOrchestrationVersion,
            EventOrchestrationRule,
            OrchestrationIntakeToken,
            AlertExplainStep,
            AlertExplainTrace,
            OrchestrationExecution,
            PendingOrchestratedEvent,
        ],
        safe=True,
    )
    PendingOrchestratedEvent.delete().execute()
    OrchestrationExecution.delete().execute()
    EventOrchestrationRule.delete().execute()
    EventOrchestrationVersion.delete().execute()
    OrchestrationIntakeToken.delete().execute()
    EventOrchestration.delete().execute()
    yield


def _publish(group, rules, *, scope="global", service=None, mode="active", compatibility="hybrid"):
    user = create_user(group=group)
    orchestration = create_orchestration(
        group_id=group.id,
        name=f"{scope}-{service.id if service else 'default'}",
        scope=scope,
        service_id=service.id if service else None,
        created_by_id=user.id,
    )
    draft = get_or_create_draft(orchestration.id, actor_id=user.id)
    replace_draft_rules(draft.id, rules)
    publish_draft(orchestration.id, actor_id=user.id)
    return set_runtime_state(
        orchestration.id,
        enabled=True,
        mode=mode,
        compatibility_mode=compatibility,
    )


def _always(actions):
    return [{
        "name": "always",
        "condition_tree": {},
        "actions": actions,
        "processing_mode": "continue",
    }]


def test_hybrid_runtime_applies_event_routing_service_and_grouping(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    service = create_service(team, name="Database", slug="database")
    _publish(group, _always([
        {"type": "set_title", "value": "Orchestrated title"},
        {"type": "set_route", "route_id": route.id},
        {"type": "set_service", "service_id": service.id},
        {"type": "set_grouping", "group_key": "database-prod", "window_seconds": 120},
    ]))

    alert_data = {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "dedup_key": "db-1",
        "title": "Original",
        "labels": {"environment": "prod"},
        "payload": {},
    }

    result = run_event_orchestration(alert_data)

    assert result.blocked is False
    assert result.compatibility_mode == "hybrid"
    assert result.route.id == route.id
    assert result.service.id == service.id
    assert result.group_key == "database-prod"
    assert result.grouping_window_seconds == 120
    assert alert_data["title"] == "Orchestrated title"
    assert alert_data["service_id"] == service.id
    assert alert_data["orchestration_group_key"] == "database-prod"
    execution = OrchestrationExecution.get_by_id(result.execution_ids[0])
    assert execution.matched_rule_count == 1
    assert execution.trace_json["applied"] is True


def test_shadow_runtime_records_candidate_without_mutating_event(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(
        group,
        _always([{"type": "set_title", "value": "Shadow title"}]),
        mode="shadow",
        compatibility="hybrid",
    )
    alert_data = {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "dedup_key": "shadow-1",
        "title": "Original",
        "labels": {},
        "payload": {},
    }
    original = copy.deepcopy(alert_data)

    result = run_event_orchestration(alert_data)

    assert alert_data == original
    assert result.steps[0].applied is False
    execution = OrchestrationExecution.get_by_id(result.execution_ids[0])
    assert execution.trace_json["result"]["context"]["event"]["title"] == "Shadow title"


def test_service_orchestration_runs_after_global_service_selection(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    service = create_service(team, name="API", slug="api")
    _publish(group, _always([{"type": "set_service", "service_id": service.id}]))
    _publish(
        group,
        _always([{"type": "set_severity", "value": "critical"}]),
        scope="service",
        service=service,
    )
    alert_data = {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "dedup_key": "api-1",
        "title": "API",
        "severity": "warning",
        "labels": {},
        "payload": {},
    }

    result = run_event_orchestration(alert_data)

    assert len(result.steps) == 2
    assert [step.scope for step in result.steps] == ["global", "service"]
    assert alert_data["severity"] == "critical"


def test_orchestration_mode_blocks_when_no_route_is_available(db):
    group = create_group()
    _publish(
        group,
        _always([{"type": "set_title", "value": "No route"}]),
        compatibility="orchestration",
    )
    alert_data = {
        "source": "alertmanager",
        "orchestration_group_id": group.id,
        "dedup_key": "unrouted-1",
        "title": "Original",
        "labels": {},
        "payload": {},
    }

    result = run_event_orchestration(alert_data)

    assert result.blocked is True
    assert result.reason == "Orchestration mode requires a selected route"


def test_legacy_compatibility_mode_does_not_mutate_event(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(
        group,
        _always([{"type": "set_title", "value": "Must not apply"}]),
        compatibility="legacy",
    )
    alert_data = {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "dedup_key": "legacy-1",
        "title": "Original",
        "labels": {},
        "payload": {},
    }

    result = run_event_orchestration(alert_data)

    assert result.compatibility_mode == "legacy"
    assert alert_data["title"] == "Original"
    assert result.steps == []


def test_attach_runtime_executions_sets_alert_and_group_ids(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(group, _always([]))
    alert_data = {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "dedup_key": "attach-1",
        "title": "Attach",
        "labels": {},
        "payload": {},
    }
    runtime = run_event_orchestration(alert_data)
    row = OrchestrationExecution.get_by_id(runtime.execution_ids[0])
    group_obj = type("GroupRef", (), {"id": 101})()
    alert_obj = type("AlertRef", (), {"id": 202})()

    attach_runtime_executions(runtime, group=group_obj, alert=alert_obj)

    row = OrchestrationExecution.get_by_id(row.id)
    assert row.alert_group_id == 101
    assert row.alert_id == 202


def test_published_definition_cache_returns_isolated_copies():
    version = type(
        "Version",
        (),
        {"id": 7, "definition_hash": "abc", "definition_json": {"rules": [{"name": "one"}]}},
    )()
    cache = PublishedDefinitionCache(max_entries=2)

    first = cache.get(version)
    first["rules"][0]["name"] = "changed"
    second = cache.get(version)

    assert second["rules"][0]["name"] == "one"



def test_service_orchestration_runs_after_legacy_service_match(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    service = create_service(team, name="Matched service", slug="matched-service")
    ServiceMatchRule.create(
        team=team,
        route=route,
        service=service,
        name="Match service label",
        position=1,
        enabled=True,
        matchers={"labels": {"service": "matched-service"}},
    )
    _publish(
        group,
        _always([{"type": "set_severity", "value": "critical"}]),
        scope="service",
        service=service,
    )
    alert_data = {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "dedup_key": "legacy-service-1",
        "title": "Matched service",
        "severity": "warning",
        "labels": {"service": "matched-service"},
        "payload": {},
    }

    runtime = run_event_orchestration(alert_data)
    assert runtime.steps == []
    selected_service = resolve_alert_service(route, alert_data)

    runtime = run_service_orchestration(
        alert_data,
        runtime,
        route=route,
        team=team,
        service=selected_service,
    )

    assert selected_service.id == service.id
    assert [step.scope for step in runtime.steps] == ["service"]
    assert alert_data["severity"] == "critical"


def test_hybrid_rejected_candidate_is_not_recorded_as_applied(db):
    group = create_group()
    team = create_team(group)
    fallback_route = create_route(team, source="alertmanager")
    disabled_route = create_route(team, source="alertmanager")
    _publish(group, _always([{"type": "set_route", "route_id": disabled_route.id}]))
    disabled_route.enabled = False
    disabled_route.save()
    alert_data = {
        "source": "alertmanager",
        "forced_route_id": fallback_route.id,
        "dedup_key": "rejected-route-1",
        "title": "Fallback",
        "labels": {},
        "payload": {},
    }

    runtime = run_event_orchestration(alert_data)

    assert runtime.blocked is False
    assert runtime.route.id == fallback_route.id
    assert runtime.steps[0].applied is False
    assert runtime.steps[0].outcome == "rejected"
    execution = OrchestrationExecution.get_by_id(runtime.execution_ids[0])
    assert execution.trace_json["applied"] is False
    assert "disabled" in execution.trace_json["rejected_reason"]


def test_execution_trace_redacts_sensitive_payload_values(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(group, _always([]), mode="shadow")
    alert_data = {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "dedup_key": "secret-1",
        "title": "Secret",
        "labels": {},
        "payload": {
            "token": "must-not-be-stored",
            "nested": {"client_secret": "also-secret"},
        },
    }

    runtime = run_event_orchestration(alert_data)

    execution = OrchestrationExecution.get_by_id(runtime.execution_ids[0])
    raw = execution.trace_json["initial_context"]["raw"]
    assert raw["token"] == "***REDACTED***"
    assert raw["nested"]["client_secret"] == "***REDACTED***"



def test_runtime_state_requires_published_version(db):
    group = create_group()
    user = create_user(group=group)
    orchestration = create_orchestration(
        group_id=group.id,
        name="Unpublished runtime",
        created_by_id=user.id,
    )

    with pytest.raises(OrchestrationConflict, match="Published version"):
        set_runtime_state(
            orchestration.id,
            enabled=True,
            mode="active",
            compatibility_mode="hybrid",
        )


def test_runtime_state_rejects_incoherent_enabled_and_mode(db):
    group = create_group()
    user = create_user(group=group)
    orchestration = create_orchestration(
        group_id=group.id,
        name="Invalid runtime state",
        created_by_id=user.id,
    )

    with pytest.raises(OrchestrationValidationError, match="enabled must be true"):
        set_runtime_state(
            orchestration.id,
            enabled=False,
            mode="active",
            compatibility_mode="hybrid",
        )



def test_lifecycle_applies_runtime_mutation_and_attaches_execution(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(group, _always([{"type": "set_title", "value": "Runtime title"}]))
    alert_data = {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": "runtime-lifecycle-1",
        "dedup_key": "runtime-lifecycle-1",
        "title": "Original title",
        "message": "Original message",
        "severity": "warning",
        "status": "firing",
        "labels": {"alertname": "RuntimeLifecycle"},
        "payload": {},
    }

    result = upsert_alert(alert_data)

    assert result.alert.title == "Runtime title"
    execution = OrchestrationExecution.get(
        OrchestrationExecution.event_fingerprint == "runtime-lifecycle-1"
    )
    assert execution.alert_id == result.alert.id
    assert execution.alert_group_id == result.group.id


def test_lifecycle_runs_service_orchestration_for_legacy_service_match(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    service = create_service(team, name="Lifecycle service", slug="lifecycle-service")
    ServiceMatchRule.create(
        team=team,
        route=route,
        service=service,
        name="Lifecycle service matcher",
        position=1,
        enabled=True,
        matchers={"labels": {"service": "lifecycle-service"}},
    )
    _publish(
        group,
        _always([{"type": "set_severity", "value": "critical"}]),
        scope="service",
        service=service,
    )
    alert_data = {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": "runtime-service-lifecycle-1",
        "dedup_key": "runtime-service-lifecycle-1",
        "title": "Service lifecycle",
        "message": "Service lifecycle",
        "severity": "warning",
        "status": "firing",
        "labels": {
            "alertname": "RuntimeServiceLifecycle",
            "service": "lifecycle-service",
        },
        "payload": {},
    }

    result = upsert_alert(alert_data)

    assert result.alert.service_id == service.id
    assert result.alert.severity == "critical"
    execution = OrchestrationExecution.get(
        OrchestrationExecution.event_fingerprint == "runtime-service-lifecycle-1"
    )
    assert execution.alert_id == result.alert.id


def test_lifecycle_uses_orchestration_grouping_window(db, monkeypatch):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(
        group,
        _always([{"type": "set_grouping", "window_seconds": 17}]),
    )
    captured = {}

    from app.modules.db import alerts_repo

    original_find_existing_alert = alerts_repo.find_existing_alert

    def capture_window(source, dedup_key, window_seconds):
        captured["window_seconds"] = window_seconds
        return original_find_existing_alert(source, dedup_key, window_seconds)

    monkeypatch.setattr(alerts_repo, "find_existing_alert", capture_window)
    alert_data = {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": "runtime-window-1",
        "dedup_key": "runtime-window-1",
        "title": "Runtime window",
        "message": "Runtime window",
        "severity": "warning",
        "status": "firing",
        "labels": {"alertname": "RuntimeWindow"},
        "payload": {},
    }

    upsert_alert(alert_data)

    assert captured["window_seconds"] == 17


def test_lifecycle_persists_orchestration_notification_policy_override(db):
    group = create_group()
    team = create_team(group)
    route = create_route(
        team,
        source="alertmanager",
        notification_channel_mode="route_only",
    )
    channel = create_channel(group, team)
    policy = create_notification_policy(team)
    rule = create_notification_policy_rule(
        policy,
        channels=[channel],
    )
    _publish(
        group,
        _always([
            {
                "type": "set_notification_policy",
                "notification_policy_id": policy.id,
            },
        ]),
    )
    alert_data = {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": "runtime-notification-policy-1",
        "dedup_key": "runtime-notification-policy-1",
        "title": "Notification policy override",
        "message": "Notification policy override",
        "severity": "warning",
        "status": "firing",
        "labels": {"alertname": "RuntimeNotificationPolicy"},
        "payload": {},
    }

    result = upsert_alert(alert_data)
    resolution = resolve_notification_channels(result.group)

    assert result.alert.notification_policy_id == policy.id
    assert result.group.notification_policy_id == policy.id
    assert resolution.policy_id == policy.id
    assert resolution.mode == "service_policy"
    assert resolution.matched_rule_ids == [rule.id]
    assert [resolved.id for resolved in resolution.channels] == [channel.id]
    assert "orchestration_notification_policy_override" in resolution.notes
    assert resolution.channel_sources[channel.id] == [
        {
            "source": "orchestration_policy",
            "rule_id": rule.id,
        },
    ]


def test_lifecycle_applies_orchestration_escalation_and_priority_policies(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    assignee = create_user(group=group)

    escalation_policy = create_escalation_policy(team)
    escalation_rule = create_escalation_policy_rule(
        escalation_policy,
        delay_seconds=0,
        target_type="user",
        user=assignee,
    )

    priority = incidents_repo.get_priority_by_slug("p1")
    priority_policy = create_priority_policy(team)
    priority_rule = create_priority_policy_rule(
        priority_policy,
        priority,
        matchers={},
    )

    _publish(
        group,
        _always([
            {
                "type": "set_escalation_policy",
                "escalation_policy_id": escalation_policy.id,
            },
            {
                "type": "set_priority_policy",
                "priority_policy_id": priority_policy.id,
            },
        ]),
    )
    alert_data = {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": "runtime-policy-selection-1",
        "dedup_key": "runtime-policy-selection-1",
        "title": "Policy selection",
        "message": "Policy selection",
        "severity": "info",
        "status": "firing",
        "labels": {"alertname": "RuntimePolicySelection"},
        "payload": {},
    }

    result = upsert_alert(alert_data)

    assert result.alert.escalation_policy_id == escalation_policy.id
    assert result.alert.escalation_rule_id == escalation_rule.id
    assert result.alert.assignee_id == assignee.id
    assert result.group.escalation_policy_id == escalation_policy.id
    assert result.group.escalation_rule_id == escalation_rule.id
    assert result.group.assignee_id == assignee.id
    assert result.group.priority_slug == "p1"

    priority_step = next(
        step
        for step in alerts_repo.list_alert_explain_steps(result.trace.row)
        if step.code == "priority_resolution"
    )
    assert priority_step.data["policy_id"] == priority_policy.id
    assert priority_step.data["policy_source"] == "orchestration"
    assert priority_step.data["rule_id"] == priority_rule.id


def test_global_orchestration_can_record_compact_alert_trace(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(
        group,
        _always([{"type": "set_trace_level", "level": "compact"}]),
    )
    alert_data = {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": "runtime-trace-compact-1",
        "dedup_key": "runtime-trace-compact-1",
        "title": "Compact trace",
        "message": "Compact trace",
        "severity": "warning",
        "status": "firing",
        "labels": {"alertname": "RuntimeTraceCompact"},
        "payload": {"large": {"diagnostic": "value"}},
    }

    result = upsert_alert(alert_data)

    assert result.trace_id
    trace = AlertExplainTrace.get(AlertExplainTrace.trace_id == result.trace_id)
    steps = list(
        AlertExplainStep.select().where(AlertExplainStep.trace == trace.id)
    )
    assert trace.trace_level == "compact"
    assert trace.input_summary == {}
    assert trace.result == {}
    assert steps
    assert all(step.data == {} for step in steps)


def test_global_orchestration_can_disable_alert_trace_storage(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(
        group,
        _always([{"type": "set_trace_level", "level": "disabled"}]),
    )
    alert_data = {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": "runtime-trace-disabled-1",
        "dedup_key": "runtime-trace-disabled-1",
        "title": "Disabled trace",
        "message": "Disabled trace",
        "severity": "warning",
        "status": "firing",
        "labels": {"alertname": "RuntimeTraceDisabled"},
        "payload": {"large": {"diagnostic": "value"}},
    }

    trace_count_before = AlertExplainTrace.select().count()
    step_count_before = AlertExplainStep.select().count()
    result = upsert_alert(alert_data)

    assert result.group is not None
    assert result.alert is not None
    assert result.trace_id is None
    assert AlertExplainTrace.select().count() == trace_count_before
    assert AlertExplainStep.select().count() == step_count_before


def test_last_matching_global_trace_level_action_wins(db):
    group = create_group()
    team = create_team(group)
    route = create_route(team, source="alertmanager")
    _publish(
        group,
        _always([
            {"type": "set_trace_level", "level": "compact"},
            {"type": "set_trace_level", "level": "full"},
        ]),
    )
    alert_data = {
        "source": "alertmanager",
        "forced_route_id": route.id,
        "external_id": "runtime-trace-last-wins-1",
        "dedup_key": "runtime-trace-last-wins-1",
        "title": "Last trace action wins",
        "message": "Last trace action wins",
        "severity": "warning",
        "status": "firing",
        "labels": {"alertname": "RuntimeTraceLastWins"},
        "payload": {},
    }

    result = upsert_alert(alert_data)
    trace = AlertExplainTrace.get(AlertExplainTrace.trace_id == result.trace_id)

    assert trace.trace_level == "full"
    assert trace.input_summary["title"] == "Last trace action wins"
