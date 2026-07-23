import pytest

from app.services.orchestration.safety import (
    OrchestrationJsonError,
    ensure_json_size,
    safe_trace_value,
)
from app.settings import Config


def test_safe_trace_value_uses_global_redaction_and_configured_limits(monkeypatch):
    monkeypatch.setattr(Config, "ORCHESTRATION_TRACE_MAX_DEPTH", 1, raising=False)
    monkeypatch.setattr(
        Config,
        "ORCHESTRATION_TRACE_MAX_STRING_CHARS",
        4,
        raising=False,
    )
    monkeypatch.setattr(Config, "ORCHESTRATION_TRACE_MAX_ITEMS", 1, raising=False)

    value = safe_trace_value(
        {
            "token": "secret-token",
            "message": "abcdefgh",
            "nested": {"child": {"too": "deep"}},
        }
    )

    # Collection limiting happens before redaction and preserves insertion order.
    assert value == {"token": "***REDACTED***"}


def test_safe_trace_value_truncates_strings_and_depth(monkeypatch):
    monkeypatch.setattr(Config, "ORCHESTRATION_TRACE_MAX_DEPTH", 1, raising=False)
    monkeypatch.setattr(
        Config,
        "ORCHESTRATION_TRACE_MAX_STRING_CHARS",
        4,
        raising=False,
    )
    monkeypatch.setattr(Config, "ORCHESTRATION_TRACE_MAX_ITEMS", 10, raising=False)

    value = safe_trace_value(
        {
            "message": "abcdefgh",
            "nested": {"child": {"too": "deep"}},
        }
    )

    assert value["message"] == "abcd…"
    assert value["nested"]["child"] == "<truncated>"


def test_ensure_json_size_uses_utf8_byte_size():
    assert ensure_json_size("é", maximum_bytes=4) == 4

    with pytest.raises(OrchestrationJsonError, match="exceeds"):
        ensure_json_size("é", maximum_bytes=3, label="Payload")
