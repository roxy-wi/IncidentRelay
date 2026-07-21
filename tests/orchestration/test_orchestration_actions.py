import copy

import pytest

from app.services.orchestration.actions import (
    ActionValidationError,
    execute_actions,
    validate_action_list,
)
from app.services.orchestration.fields import build_context


def test_actions_mutate_event_with_templates_and_keep_input_immutable():
    context = build_context(
        event={"title": "old", "message": "old", "severity": "warning"},
        labels={"host": "db-01"},
    )
    original = copy.deepcopy(context)

    result = execute_actions(
        [
            {"type": "set_title", "value": "Database {{ labels.host | upper }}"},
            {"type": "set_message", "template": "{{ event.title }} is unavailable"},
            {"type": "set_severity", "value": "critical"},
            {"type": "set_label", "name": "orchestrated", "value": True},
        ],
        context,
    )

    assert result.context["event"]["title"] == "Database DB-01"
    assert result.context["event"]["message"] == "Database DB-01 is unavailable"
    assert result.context["event"]["severity"] == "critical"
    assert result.context["labels"]["orchestrated"] == "true"
    assert context == original
    assert [step.success for step in result.steps] == [True, True, True, True]
    assert result.steps[0].references == ("labels.host",)


def test_extraction_action_can_feed_later_template_action():
    result = execute_actions(
        [
            {
                "type": "extract_regex",
                "source": "event.message",
                "pattern": r"host=(?P<host>[a-z0-9-]+)",
            },
            {"type": "set_title", "value": "Failure on {{ variables.host }}"},
        ],
        build_context(event={"message": "host=api-17 status=down"}),
    )

    assert result.context["variables"]["host"] == "api-17"
    assert result.context["event"]["title"] == "Failure on api-17"
    assert result.steps[0].code == "extraction_succeeded"


def test_routing_policy_and_grouping_actions_record_explicit_result():
    result = execute_actions(
        [
            {"type": "set_route", "route_id": 11},
            {"type": "set_team", "team_id": 12},
            {"type": "set_service", "service_id": 13},
            {"type": "set_escalation_policy", "escalation_policy_id": 21},
            {"type": "set_notification_policy", "notification_policy_id": 22},
            {"type": "set_priority_policy", "priority_policy_id": 23},
            {
                "type": "set_grouping",
                "dedup_key": "{{ labels.alertname }}:{{ labels.instance }}",
                "group_key": "{{ labels.alertname }}",
                "window_seconds": 300,
                "strategy": "content",
            },
        ],
        build_context(labels={"alertname": "DiskFull", "instance": "db1"}),
    )

    context = result.context
    assert context["route"] == {"id": 11}
    assert context["team"] == {"id": 12}
    assert context["service"] == {"id": 13}
    assert context["result"]["routing"] == {
        "route_id": 11,
        "team_id": 12,
        "service_id": 13,
    }
    assert context["result"]["policies"] == {
        "escalation_policy_id": 21,
        "notification_policy_id": 22,
        "priority_policy_id": 23,
    }
    assert context["event"]["dedup_key"] == "DiskFull:db1"
    assert context["event"]["group_key"] == "DiskFull"
    assert context["result"]["grouping"]["window_seconds"] == 300


def test_custom_fields_labels_notes_and_removals():
    result = execute_actions(
        [
            {"type": "set_custom_field", "name": "runbook", "value": {"id": 7}},
            {"type": "set_label", "name": "environment", "value": "prod"},
            {"type": "add_note", "value": "classified as {{ labels.environment }}"},
            {"type": "remove_custom_field", "name": "old"},
            {"type": "remove_label", "name": "obsolete"},
        ],
        build_context(
            event={"custom_details": {"old": "x"}},
            labels={"obsolete": "1"},
        ),
    )

    assert result.context["event"]["custom_details"] == {"runbook": {"id": 7}}
    assert result.context["labels"] == {"environment": "prod"}
    assert result.context["result"]["notes"] == ["classified as prod"]


def test_runtime_failure_can_continue_and_is_explained():
    result = execute_actions(
        [
            {
                "type": "set_title",
                "value": "{{ variables.missing }}",
                "on_failure": "continue",
            },
            {"type": "set_severity", "value": "critical"},
        ],
        build_context(event={"title": "unchanged"}),
    )

    assert result.outcome == "continue"
    assert result.context["event"]["title"] == "unchanged"
    assert result.context["event"]["severity"] == "critical"
    assert result.steps[0].success is False
    assert result.steps[0].code == "invalid_template"
    assert result.steps[1].success is True


def test_runtime_failure_can_stop_orchestration():
    result = execute_actions(
        [
            {
                "type": "set_title",
                "value_from": "variables.missing",
                "on_failure": "stop_orchestration",
            },
            {"type": "set_severity", "value": "critical"},
        ],
        build_context(event={"severity": "warning"}),
    )

    assert result.outcome == "stop_orchestration"
    assert result.context["event"]["severity"] == "warning"
    assert len(result.steps) == 1
    assert result.steps[0].success is False


def test_disposition_actions_are_explicit_and_drop_is_terminal():
    suppressed = execute_actions([{"type": "suppress"}], build_context())
    assert suppressed.context["result"]["disposition"] == "suppress"
    assert suppressed.context["result"]["suppress_notifications"] is True

    paused = execute_actions([{"type": "pause", "seconds": 120}], build_context())
    assert paused.context["result"]["disposition"] == "pause"
    assert paused.context["result"]["pause_seconds"] == 120

    dropped = execute_actions(
        [
            {"type": "drop"},
            {"type": "set_title", "value": "must not run"},
        ],
        build_context(event={"title": "original"}),
    )
    assert dropped.outcome == "stop_orchestration"
    assert dropped.context["result"]["disposition"] == "drop"
    assert dropped.context["event"]["title"] == "original"
    assert len(dropped.steps) == 1


def test_set_event_action_accepts_only_trigger_or_resolve():
    result = execute_actions(
        [{"type": "set_event_action", "value": "resolve"}],
        build_context(),
    )
    assert result.context["event"]["event_action"] == "resolve"

    issues = validate_action_list([{"type": "set_event_action", "value": "close"}])
    assert any(issue.code == "invalid_event_action" for issue in issues)


def test_invalid_static_reference_is_rejected_before_execution():
    issues = validate_action_list([{"type": "set_team", "team_id": "dynamic"}])
    assert any(issue.code == "invalid_action" for issue in issues)

    with pytest.raises(ActionValidationError):
        execute_actions([{"type": "set_team", "team_id": "dynamic"}], build_context())


def test_unknown_action_is_rejected():
    issues = validate_action_list([{"type": "run_python", "value": "print(1)"}])
    assert issues[0].code == "unsupported_action"
