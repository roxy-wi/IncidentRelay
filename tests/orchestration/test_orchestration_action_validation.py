from app.services.orchestration.validation import validate_rule_definition


def test_publication_validation_accepts_supported_actions():
    result = validate_rule_definition(
        {},
        [
            {"type": "set_title", "value": "{{ labels.alertname }}"},
            {"type": "set_team", "team_id": 7},
            {"type": "set_grouping", "group_key": "{{ labels.service }}", "window_seconds": 60},
            {"type": "suppress"},
        ],
    )

    assert result["errors"] == []


def test_publication_validation_rejects_unknown_or_malformed_actions():
    result = validate_rule_definition(
        {},
        [
            {"type": "execute_shell", "value": "rm -rf /"},
            {"type": "set_team", "team_id": "{{ variables.team }}"},
            {"type": "pause", "seconds": 0},
        ],
    )

    codes = {issue.code for issue in result["errors"]}
    assert "unsupported_action" in codes
    assert "invalid_action" in codes
    assert "invalid_pause_duration" in codes

def test_publication_validation_rejects_noncanonical_add_label_action():
    result = validate_rule_definition(
        {},
        [{"type": "add_label", "key": "tier", "value": "data"}],
    )

    assert [(issue.path, issue.code) for issue in result["errors"]] == [
        ("rule.actions[0].type", "unsupported_action"),
    ]

