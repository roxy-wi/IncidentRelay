"""Bounded regular-expression helpers.

Python's standard ``re`` engine has no portable timeout on the supported
IncidentRelay Python versions, so orchestration regexes use strict size and
complexity checks before compilation and input-size limits before matching.
"""

from __future__ import annotations

import re
from typing import Pattern

from .errors import RegexSafetyError
from .limits import MAX_REGEX_INPUT_LENGTH, MAX_REGEX_PATTERN_LENGTH


# Reject constructs that are either unnecessary for orchestration matching or
# commonly associated with catastrophic backtracking / hidden complexity.
_FORBIDDEN_PATTERNS = (
    (re.compile(r"\\[1-9]"), "numeric backreferences are not allowed"),
    (re.compile(r"\(\?P="), "named backreferences are not allowed"),
    (re.compile(r"\(\?<[=!]"), "lookbehind is not allowed"),
    (re.compile(r"\(\?\("), "conditional groups are not allowed"),
    (re.compile(r"\(\?>"), "atomic groups are not supported"),
)

# Approximate nested-quantifier detection. This intentionally rejects some
# valid but complex patterns in exchange for predictable ingestion latency.
_NESTED_QUANTIFIER = re.compile(
    r"\((?:[^()\\]|\\.)*(?:\*|\+|\?|\{\d+(?:,\d*)?\})(?:[^()\\]|\\.)*\)"
    r"\s*(?:\*|\+|\{\d+(?:,\d*)?\})"
)
_QUANTIFIED_ALTERNATION = re.compile(
    r"\((?:[^()\\]|\\.)*\|(?:[^()\\]|\\.)*\)"
    r"\s*(?:\*|\+|\{\d+(?:,\d*)?\})"
)
_AMBIGUOUS_DOT_REPEAT = re.compile(r"(?:\.\*|\.\+)\s*(?:\.\*|\.\+)")


def normalize_named_groups(pattern: str) -> str:
    """Accept architecture-style ``(?<name>...)`` named groups safely."""

    return re.sub(r"\(\?<([A-Za-z_][A-Za-z0-9_]*)>", r"(?P<\1>", pattern)


def validate_regex_pattern(pattern: str) -> str:
    if not isinstance(pattern, str):
        raise RegexSafetyError("regex pattern must be a string")
    if len(pattern) > MAX_REGEX_PATTERN_LENGTH:
        raise RegexSafetyError("regex pattern exceeds the size limit")
    if "\x00" in pattern:
        raise RegexSafetyError("regex pattern cannot contain NUL bytes")

    normalized = normalize_named_groups(pattern)
    for detector, message in _FORBIDDEN_PATTERNS:
        if detector.search(normalized):
            raise RegexSafetyError(message)
    if _NESTED_QUANTIFIER.search(normalized):
        raise RegexSafetyError("nested quantified groups are not allowed")
    if _QUANTIFIED_ALTERNATION.search(normalized):
        raise RegexSafetyError("quantified alternation groups are not allowed")
    if _AMBIGUOUS_DOT_REPEAT.search(normalized):
        raise RegexSafetyError("ambiguous repeated wildcard expressions are not allowed")
    if sum(normalized.count(token) for token in ("*", "+", "?", "{")) > 64:
        raise RegexSafetyError("regex pattern has too many quantifiers")
    if normalized.count("|") > 32:
        raise RegexSafetyError("regex pattern has too many alternatives")

    try:
        re.compile(normalized)
    except re.error as exc:
        raise RegexSafetyError(f"invalid regex pattern: {exc.msg}") from exc
    return normalized


def compile_safe_regex(pattern: str, *, flags: int = 0) -> Pattern[str]:
    return re.compile(validate_regex_pattern(pattern), flags)


def bounded_regex_input(value: object) -> str:
    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (str, int, float)):
        text = str(value)
    else:
        raise RegexSafetyError("regex input must be a scalar value")
    if len(text) > MAX_REGEX_INPUT_LENGTH:
        raise RegexSafetyError("regex input exceeds the size limit")
    return text
