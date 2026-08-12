"""Shared safety helpers for orchestration traces and JSON payloads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Optional

from app.modules.redaction import redact_secrets
from app.settings import Config


class OrchestrationJsonError(ValueError):
    """Raised when orchestration input cannot be represented safely as JSON."""


def _positive_int(value: Any, default: int, *, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def trace_limits() -> tuple[int, int, int]:
    """Return the configured depth, string and collection trace limits."""
    return (
        _positive_int(
            getattr(Config, "ORCHESTRATION_TRACE_MAX_DEPTH", 12),
            12,
            minimum=0,
        ),
        _positive_int(
            getattr(Config, "ORCHESTRATION_TRACE_MAX_STRING_CHARS", 2048),
            2048,
        ),
        _positive_int(
            getattr(Config, "ORCHESTRATION_TRACE_MAX_ITEMS", 512),
            512,
        ),
    )


def bounded_trace_value(
    value: Any,
    *,
    depth: int = 0,
    max_depth: Optional[int] = None,
    max_string_chars: Optional[int] = None,
    max_items: Optional[int] = None,
) -> Any:
    """Return a bounded JSON-compatible representation of ``value``."""
    if max_depth is None or max_string_chars is None or max_items is None:
        configured_depth, configured_string, configured_items = trace_limits()
        max_depth = configured_depth if max_depth is None else max_depth
        max_string_chars = (
            configured_string
            if max_string_chars is None
            else max_string_chars
        )
        max_items = configured_items if max_items is None else max_items

    max_depth = max(0, int(max_depth))
    max_string_chars = max(1, int(max_string_chars))
    max_items = max(1, int(max_items))

    if depth > max_depth:
        return "<truncated>"

    if isinstance(value, str):
        if len(value) <= max_string_chars:
            return value
        return value[:max_string_chars] + "…"

    if value is None or isinstance(value, (int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return {
            str(key): bounded_trace_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_string_chars=max_string_chars,
                max_items=max_items,
            )
            for key, item in list(value.items())[:max_items]
        }

    if isinstance(value, (list, tuple)):
        return [
            bounded_trace_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_string_chars=max_string_chars,
                max_items=max_items,
            )
            for item in value[:max_items]
        ]

    if isinstance(value, (set, frozenset)):
        ordered = sorted(value, key=lambda item: repr(item))
        return [
            bounded_trace_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_string_chars=max_string_chars,
                max_items=max_items,
            )
            for item in ordered[:max_items]
        ]

    if isinstance(value, BaseException):
        return bounded_trace_value(
            str(value),
            depth=depth,
            max_depth=max_depth,
            max_string_chars=max_string_chars,
            max_items=max_items,
        )

    return bounded_trace_value(
        str(value),
        depth=depth,
        max_depth=max_depth,
        max_string_chars=max_string_chars,
        max_items=max_items,
    )


def safe_trace_value(value: Any) -> Any:
    """Bound trace data and redact secrets through the global redactor."""
    return redact_secrets(bounded_trace_value(value))


def json_size_bytes(value: Any) -> int:
    """Return deterministic UTF-8 JSON size or raise ``OrchestrationJsonError``."""
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise OrchestrationJsonError("value must be JSON-compatible") from exc
    return len(encoded)


def ensure_json_size(
    value: Any,
    *,
    maximum_bytes: int,
    label: str = "Value",
) -> int:
    """Validate a JSON value against a byte limit and return its size."""
    maximum = max(1, int(maximum_bytes))
    size = json_size_bytes(value)
    if size > maximum:
        raise OrchestrationJsonError(
            f"{label} exceeds the {maximum}-byte limit"
        )
    return size


__all__ = [
    "OrchestrationJsonError",
    "bounded_trace_value",
    "ensure_json_size",
    "json_size_bytes",
    "safe_trace_value",
    "trace_limits",
]
