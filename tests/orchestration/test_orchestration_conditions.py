import pytest

from app.services.orchestration.conditions import (
    evaluate_condition_tree,
    validate_condition_tree,
)
from app.services.orchestration.errors import ConditionValidationError
from app.services.orchestration.fields import build_context, resolve_field


@pytest.fixture
def context():
    return build_context(
        event={
            "title": "[PROD] Database latency",
            "severity": "critical",
            "count": "12.50",
            "enabled": "yes",
            "labels": {
                "environment": "production",
                "component": "database",
                "owners": ["sre", "dba"],
            },
        },
        raw={"payload": {"source": "grafana"}},
        variables={"region": "eu-central-1"},
        integration={"name": "grafana"},
    )


def test_nested_all_any_none_returns_complete_explain_trace(context):
    tree = {
        "all": [
            {"field": "labels.environment", "operator": "equals", "value": "production"},
            {
                "any": [
                    {"field": "severity", "operator": "equals", "value": "critical"},
                    {"field": "severity", "operator": "equals", "value": "high"},
                ]
            },
            {
                "none": [
                    {"field": "labels.component", "operator": "equals", "value": "frontend"},
                    {"field": "variables.region", "operator": "equals", "value": "us-east-1"},
                ]
            },
        ]
    }

    result = evaluate_condition_tree(tree, context)

    assert result.matched is True
    trace = result.to_dict()
    assert trace["node_type"] == "all"
    assert len(trace["children"]) == 3
    # The any group evaluates both children for Explain, even after a match.
    assert len(trace["children"][1]["children"]) == 2
    assert trace["children"][1]["children"][1]["matched"] is False


@pytest.mark.parametrize(
    ("condition", "matched"),
    [
        ({"field": "event.title", "operator": "contains", "value": "Database"}, True),
        ({"field": "event.title", "operator": "not_contains", "value": "RabbitMQ"}, True),
        ({"field": "event.title", "operator": "starts_with", "value": "[PROD]"}, True),
        ({"field": "event.title", "operator": "ends_with", "value": "latency"}, True),
        ({"field": "event.title", "operator": "regex", "value": r"^\[PROD\]"}, True),
        ({"field": "event.title", "operator": "not_regex", "value": r"resolved$"}, True),
        ({"field": "severity", "operator": "in", "value": ["high", "critical"]}, True),
        ({"field": "severity", "operator": "not_in", "value": ["low", "warning"]}, True),
        ({"field": "labels.owners", "operator": "contains", "value": "dba"}, True),
        ({"field": "labels.environment", "operator": "exists"}, True),
        ({"field": "labels.missing", "operator": "not_exists"}, True),
        ({"field": "event.count", "operator": "greater_than", "value": 12}, True),
        ({"field": "event.count", "operator": "less_or_equal", "value": "12.50"}, True),
        ({"field": "event.enabled", "operator": "is_true"}, True),
        ({"field": "event.enabled", "operator": "is_false"}, False),
        ({"field": "severity", "operator": "eq", "value": "critical"}, True),
    ],
)
def test_supported_operators_are_deterministic(context, condition, matched):
    assert evaluate_condition_tree(condition, context).matched is matched


def test_missing_field_mismatch_has_structured_reason(context):
    result = evaluate_condition_tree(
        {"field": "labels.unknown", "operator": "equals", "value": "x"},
        context,
    )

    assert result.matched is False
    assert result.code == "field_missing"
    assert result.found is False
    assert result.to_dict()["field"] == "labels.unknown"


def test_empty_condition_is_explicit_catch_all(context):
    result = evaluate_condition_tree({}, context)
    assert result.matched is True
    assert result.code == "catch_all"


def test_type_coercion_does_not_treat_boolean_as_number(context):
    assert evaluate_condition_tree(
        {"field": "event.enabled", "operator": "equals", "value": 1}, context
    ).matched is False
    assert evaluate_condition_tree(
        {"field": "event.count", "operator": "equals", "value": 12.5}, context
    ).matched is True


def test_invalid_tree_fails_before_evaluation(context):
    tree = {"all": [], "field": "severity", "operator": "equals", "value": "critical"}
    issues = validate_condition_tree(tree)
    assert any(issue.code == "ambiguous_condition_node" for issue in issues)

    with pytest.raises(ConditionValidationError, match="exactly one"):
        evaluate_condition_tree(tree, context)


def test_invalid_field_root_is_rejected():
    issues = validate_condition_tree(
        {"field": "__class__.__mro__", "operator": "exists"}
    )
    assert any(issue.code == "invalid_field_reference" for issue in issues)


def test_resolver_never_reads_python_attributes(context):
    from app.services.orchestration.errors import FieldResolutionError

    with pytest.raises(FieldResolutionError, match="dunder"):
        resolve_field(context, "event.__class__")


def test_equals_null_keeps_expected_value_in_trace():
    context = build_context(event={"owner": None})
    result = evaluate_condition_tree(
        {"field": "event.owner", "operator": "equals", "value": None},
        context,
    )
    assert result.matched is True
    assert "expected" in result.to_dict()
    assert result.to_dict()["expected"] is None
