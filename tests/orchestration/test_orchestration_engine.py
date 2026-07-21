import copy

from app.services.orchestration.engine import execute_rule_tree
from app.services.orchestration.fields import build_context


def _rule(name, *, condition=None, actions=None, mode="continue", children=None, enabled=True):
    return {
        "name": name,
        "enabled": enabled,
        "condition_tree": condition or {},
        "actions": actions or [],
        "processing_mode": mode,
        "children": children or [],
    }


def test_continue_rules_run_in_order_and_later_conditions_see_mutations():
    rules = [
        _rule(
            "classify",
            actions=[
                {"type": "set_label", "name": "tier", "value": "database"},
                {"type": "set_severity", "value": "critical"},
            ],
        ),
        _rule(
            "route",
            condition={"field": "labels.tier", "operator": "equals", "value": "database"},
            actions=[{"type": "set_team", "team_id": 9}],
        ),
    ]

    result = execute_rule_tree(rules, build_context(event={"severity": "warning"}))

    assert result.outcome == "continue"
    assert result.matched_rule_count == 2
    assert result.context["event"]["severity"] == "critical"
    assert result.context["team"] == {"id": 9}
    assert [trace.matched for trace in result.rules] == [True, True]


def test_stop_processing_mode_prevents_later_siblings():
    rules = [
        _rule("first", actions=[{"type": "set_title", "value": "first"}], mode="stop"),
        _rule("second", actions=[{"type": "set_title", "value": "second"}]),
    ]

    result = execute_rule_tree(rules, build_context())

    assert result.outcome == "stop"
    assert result.stopped_at == "rules[0]"
    assert result.context["event"]["title"] == "first"
    assert len(result.rules) == 1


def test_evaluate_children_runs_children_then_stops_siblings():
    rules = [
        _rule(
            "parent",
            actions=[{"type": "set_label", "name": "parent", "value": "yes"}],
            mode="evaluate_children",
            children=[
                _rule(
                    "child",
                    condition={"field": "labels.parent", "operator": "equals", "value": "yes"},
                    actions=[{"type": "set_title", "value": "child"}],
                )
            ],
        ),
        _rule("sibling", actions=[{"type": "set_title", "value": "sibling"}]),
    ]

    result = execute_rule_tree(rules, build_context())

    assert result.outcome == "stop"
    assert result.context["event"]["title"] == "child"
    assert len(result.rules) == 1
    assert result.rules[0].children[0].matched is True


def test_children_then_continue_returns_to_parent_siblings():
    rules = [
        _rule(
            "parent",
            mode="children_then_continue",
            children=[_rule("child", actions=[{"type": "set_title", "value": "child"}])],
        ),
        _rule("sibling", actions=[{"type": "set_message", "value": "sibling ran"}]),
    ]

    result = execute_rule_tree(rules, build_context())

    assert result.outcome == "continue"
    assert result.context["event"]["title"] == "child"
    assert result.context["event"]["message"] == "sibling ran"
    assert len(result.rules) == 2


def test_disabled_and_unmatched_rules_have_trace_without_actions():
    rules = [
        _rule("disabled", enabled=False, actions=[{"type": "drop"}]),
        _rule(
            "unmatched",
            condition={"field": "severity", "operator": "equals", "value": "critical"},
            actions=[{"type": "drop"}],
        ),
    ]

    result = execute_rule_tree(rules, build_context(event={"severity": "warning"}))

    assert result.outcome == "continue"
    assert result.matched_rule_count == 0
    assert result.rules[0].code == "rule_disabled"
    assert result.rules[1].code == "rule_not_matched"
    assert result.context["result"]["dropped"] is False


def test_drop_action_stops_entire_nested_tree():
    rules = [
        _rule(
            "parent",
            mode="children_then_continue",
            children=[_rule("child", actions=[{"type": "drop"}])],
        ),
        _rule("must not run", actions=[{"type": "set_title", "value": "wrong"}]),
    ]

    result = execute_rule_tree(rules, build_context(event={"title": "original"}))

    assert result.outcome == "drop"
    assert result.context["event"]["title"] == "original"
    assert result.context["result"]["dropped"] is True
    assert result.stopped_at == "rules[0].children[0]"
    assert len(result.rules) == 1


def test_engine_does_not_mutate_input_context():
    context = build_context(event={"title": "original"}, labels={"a": "b"})
    original = copy.deepcopy(context)

    execute_rule_tree(
        [_rule("change", actions=[{"type": "set_title", "value": "changed"}])],
        context,
    )

    assert context == original
