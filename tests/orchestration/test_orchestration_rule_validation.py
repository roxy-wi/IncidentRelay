from app.services.orchestration.validation import validate_rule_definition


def test_rule_validation_combines_condition_extractor_and_template_errors():
    result = validate_rule_definition(
        {
            "field": "unknown.root",
            "operator": "regex",
            "value": "(a+)+$",
        },
        [
            {
                "type": "set_variable",
                "name": "bad-name",
                "value": "{{ event.title | unsafe }}",
            }
        ],
    )

    codes = {issue.code for issue in result["errors"]}
    assert "invalid_field_reference" in codes
    assert "unsafe_regex" in codes
    assert "invalid_variable_name" in codes
    assert "invalid_template" in codes
