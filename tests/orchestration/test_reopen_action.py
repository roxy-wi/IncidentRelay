"""Publication/runtime contract for opt-in AlertGroup reopen."""

import pytest

from app.services.orchestration.actions import validate_action, execute_actions
from app.services.orchestration.fields import build_context


@pytest.mark.parametrize("value", [-1, True, 1.5, "300", None, 86401])
def test_reopen_window_rejects_invalid_type_or_range(value):
    issues = validate_action({"type": "set_grouping", "reopen_window_seconds": value})
    assert any(issue.path.endswith("reopen_window_seconds") for issue in issues)


@pytest.mark.parametrize("value", [0, 1, 300, 86400])
def test_reopen_window_is_independent_of_grouping_window(value):
    issues = validate_action({
        "type": "set_grouping", "reopen_window_seconds": value,
    })
    assert not issues
    result = execute_actions([
        {"type": "set_grouping", "window_seconds": 17},
        {"type": "set_grouping", "reopen_window_seconds": value},
    ], build_context(labels={"alertname": "DiskFull"}))
    grouping = result.context["result"]["grouping"]
    assert grouping["window_seconds"] == 17
    assert grouping["reopen_window_seconds"] == value
