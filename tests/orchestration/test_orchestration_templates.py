import pytest

from app.services.orchestration.errors import TemplateValidationError
from app.services.orchestration.fields import build_context
from app.services.orchestration.limits import MAX_TEMPLATE_LENGTH
from app.services.orchestration.templates import render_template, validate_template


@pytest.fixture
def context():
    return build_context(
        event={"title": "  API DOWN  ", "labels": {"environment": "PROD"}},
        variables={"service": "payments-api"},
    )


def test_restricted_template_renders_whitelisted_filters(context):
    rendered = render_template(
        "{{ labels.environment | lower }}: {{ event.title | trim | replace('DOWN', 'degraded') }} / {{ variables.service | truncate(8) }}",
        context,
    )
    assert rendered.value == "prod: API degraded / payments"
    assert rendered.references == (
        "labels.environment",
        "event.title",
        "variables.service",
    )


def test_default_filter_handles_missing_field(context):
    rendered = render_template(
        "owner={{ labels.owner | default('unknown') | upper }}",
        context,
    )
    assert rendered.value == "owner=UNKNOWN"


def test_missing_field_without_default_fails(context):
    with pytest.raises(TemplateValidationError, match="does not exist"):
        render_template("{{ labels.owner }}", context)


@pytest.mark.parametrize(
    "template",
    [
        "{{ event.title.__class__ }}",
        "{{ event.title | attr('__class__') }}",
        "{{ __import__('os').system('id') }}",
        "{{ event.title | lower() | unknown }}",
        "{{ event.title | replace(open('/tmp/x'), 'x') }}",
    ],
)
def test_arbitrary_expressions_and_unknown_filters_are_rejected(template):
    assert validate_template(template)


def test_unbalanced_template_is_rejected():
    issues = validate_template("{{ event.title")
    assert any(issue.code == "unbalanced_template_delimiter" for issue in issues)


def test_template_size_and_output_are_limited(context):
    issues = validate_template("x" * (MAX_TEMPLATE_LENGTH + 1))
    assert any(issue.code == "template_size_limit" for issue in issues)

    with pytest.raises(TemplateValidationError, match="output limit"):
        render_template("{{ event.title }}", context, max_output_length=2)
