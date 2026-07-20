import pytest

from app.services.orchestration.errors import ExtractionError
from app.services.orchestration.fields import build_context
from app.services.orchestration.variables import extract_variables, validate_extractors


@pytest.fixture
def context():
    return build_context(
        event={
            "title": "[PROD][payments] latency high",
            "message": "owner:sre:primary",
            "labels": {"region": "EU-CENTRAL-1"},
        },
        raw={
            "alert": {
                "targets": [
                    {"name": "api"},
                    {"name": "worker"},
                ]
            }
        },
    )


def test_all_required_variable_extraction_modes(context):
    result = extract_variables(
        [
            {
                "type": "extract_regex",
                "source": "event.title",
                "pattern": r"^\[(?<environment>[^]]+)\]\[(?<service>[^]]+)\]",
            },
            {
                "type": "copy_field",
                "source": "labels.region",
                "name": "region_raw",
            },
            {
                "type": "json_path",
                "source": "raw",
                "path": "$.alert.targets[1].name",
                "name": "second_target",
            },
            {
                "type": "split",
                "source": "event.message",
                "delimiter": ":",
                "targets": ["kind", "owner", "level"],
            },
            {
                "type": "set_variable",
                "name": "summary",
                "value": "{{ variables.environment | lower }}-{{ variables.service }}",
            },
            {
                "type": "lowercase",
                "source": "variables.region_raw",
                "name": "region",
            },
        ],
        context,
    )

    assert result.outcome == "continue"
    assert result.variables == {
        "environment": "PROD",
        "service": "payments",
        "region_raw": "EU-CENTRAL-1",
        "second_target": "worker",
        "kind": "owner",
        "owner": "sre",
        "level": "primary",
        "summary": "prod-payments",
        "region": "eu-central-1",
    }
    assert all(step.success for step in result.steps)


def test_extraction_does_not_mutate_input_context(context):
    original = dict(context["variables"])
    result = extract_variables(
        [{"type": "static", "name": "new_value", "value": "x"}], context
    )
    assert result.variables["new_value"] == "x"
    assert context["variables"] == original


def test_failure_modes_are_structured(context):
    extractors = [
        {
            "type": "copy_field",
            "source": "labels.missing",
            "name": "missing",
            "on_failure": "continue",
        },
        {
            "type": "json_path",
            "source": "raw",
            "path": "$.does.not.exist",
            "name": "bad",
            "on_failure": "stop_rule",
        },
        {"type": "static", "name": "unreachable", "value": "x"},
    ]

    result = extract_variables(extractors, context)

    assert result.outcome == "stop_rule"
    assert len(result.steps) == 2
    assert result.steps[0].success is False
    assert result.steps[1].failure_mode == "stop_rule"
    assert "unreachable" not in result.variables


def test_invalid_json_path_and_variable_name_fail_validation():
    issues = validate_extractors(
        [
            {
                "type": "json_path",
                "source": "raw",
                "path": "$..secret",
                "name": "bad-name",
            }
        ]
    )
    codes = {issue.code for issue in issues}
    assert "invalid_json_path" in codes
    assert "invalid_variable_name" in codes


def test_invalid_extractor_cannot_execute(context):
    with pytest.raises(ExtractionError, match="unsupported variable extractor"):
        extract_variables(
            [{"type": "python", "code": "__import__('os').system('id')"}],
            context,
        )


def test_regex_extractor_requires_valid_targets():
    issues = validate_extractors(
        [{"type": "extract_regex", "source": "event.title", "pattern": "^ok$"}]
    )
    assert any(issue.code == "missing_regex_targets" for issue in issues)

    issues = validate_extractors(
        [
            {
                "type": "extract_regex",
                "source": "event.title",
                "pattern": r"^(?P<name>.+)$",
                "name": "target",
                "group": "missing",
            }
        ]
    )
    assert any(issue.code == "invalid_regex_group" for issue in issues)


def test_split_targets_must_be_unique():
    issues = validate_extractors(
        [
            {
                "type": "split",
                "source": "event.message",
                "delimiter": ":",
                "targets": ["owner", "owner"],
            }
        ]
    )
    assert any(issue.code == "duplicate_variable_name" for issue in issues)
