import pytest

from app.services.orchestration.conditions import evaluate_condition_tree, validate_condition_tree
from app.services.orchestration.errors import RegexSafetyError
from app.services.orchestration.fields import build_context
from app.services.orchestration.limits import MAX_REGEX_INPUT_LENGTH, MAX_REGEX_PATTERN_LENGTH
from app.services.orchestration.regex import compile_safe_regex


def test_nested_quantifier_is_rejected():
    with pytest.raises(RegexSafetyError, match="nested quantified"):
        compile_safe_regex(r"(a+)+$")


def test_quantified_alternation_is_rejected():
    with pytest.raises(RegexSafetyError, match="quantified alternation"):
        compile_safe_regex(r"(a|aa)+$")


def test_backreference_and_lookbehind_are_rejected():
    with pytest.raises(RegexSafetyError, match="backreferences"):
        compile_safe_regex(r"(a)\1")
    with pytest.raises(RegexSafetyError, match="lookbehind"):
        compile_safe_regex(r"(?<=a)b")


def test_regex_pattern_size_is_limited():
    issues = validate_condition_tree(
        {
            "field": "event.title",
            "operator": "regex",
            "value": "a" * (MAX_REGEX_PATTERN_LENGTH + 1),
        }
    )
    assert any(issue.code == "unsafe_regex" for issue in issues)


def test_regex_input_size_is_bounded_without_crashing():
    context = build_context(event={"title": "a" * (MAX_REGEX_INPUT_LENGTH + 1)})
    result = evaluate_condition_tree(
        {"field": "event.title", "operator": "regex", "value": "^a+$"},
        context,
    )
    assert result.matched is False
    assert result.code == "unsafe_regex"


def test_architecture_named_group_syntax_is_supported():
    regex = compile_safe_regex(r"^\[(?<environment>[^]]+)\]")
    match = regex.search("[prod] API down")
    assert match is not None
    assert match.groupdict() == {"environment": "prod"}
