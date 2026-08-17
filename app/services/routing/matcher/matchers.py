import logging

import regex


logger = logging.getLogger("oncall.routing.matcher")

MATCHER_REGEX_TIMEOUT_SECONDS = 0.05
MATCHER_REGEX_MAX_PATTERN_LENGTH = 1024
MATCHER_REGEX_MAX_INPUT_LENGTH = 65536


def safe_regex_search(pattern, value):
    """Evaluate an untrusted matcher regex with strict size and time bounds."""
    pattern = str(pattern or "")
    text = str(value or "")

    if len(pattern) > MATCHER_REGEX_MAX_PATTERN_LENGTH:
        return False
    if len(text) > MATCHER_REGEX_MAX_INPUT_LENGTH:
        return False

    try:
        return regex.search(
            pattern,
            text,
            timeout=MATCHER_REGEX_TIMEOUT_SECONDS,
        ) is not None
    except TimeoutError:
        logger.warning("matcher regex timed out")
        return False
    except regex.error:
        return False


def _validate_regex_pattern(pattern):
    """Validate regex syntax without running it against attacker input."""
    pattern = str(pattern or "")

    if len(pattern) > MATCHER_REGEX_MAX_PATTERN_LENGTH:
        raise ValueError("regex pattern is too long")

    try:
        regex.compile(pattern)
    except regex.error as exc:
        raise ValueError("invalid regex pattern") from exc


def _validate_matcher_value_regexes(value):
    if not isinstance(value, dict):
        return

    operator = value.get("op")
    if operator is not None:
        normalized_operator = {
            "eq": "equals",
            "ne": "not_equals",
            "neq": "not_equals",
        }.get(str(operator).strip().lower(), str(operator).strip().lower())
        if normalized_operator == "regex":
            _validate_regex_pattern(value.get("value"))

    if "regex" in value:
        _validate_regex_pattern(value.get("regex"))

    if "not" in value:
        _validate_matcher_value_regexes(value.get("not"))


def validate_matcher_regexes(matchers):
    """Raise ValueError when a matcher contains an invalid regex."""
    normalized = normalize_matchers(matchers)

    if "title_regex" in normalized:
        _validate_regex_pattern(normalized.get("title_regex"))

    for key in ("source", "title"):
        if key in normalized:
            _validate_matcher_value_regexes(normalized.get(key))

    for container_name in ("labels", "fields"):
        for value in (normalized.get(container_name) or {}).values():
            _validate_matcher_value_regexes(value)


MATCHER_STRUCTURED_KEYS = {
    "severity",
    "source",
    "title",
    "title_regex",
    "labels",
    "fields",
}


def normalize_matchers(matchers):
    """Normalize matcher object before matching.

    Flat Prometheus-style matcher:

        {
            "alertname": "DiskFull",
            "instance": "host1",
            "severity": "critical"
        }

    becomes:

        {
            "labels": {
                "alertname": "DiskFull",
                "instance": "host1",
                "severity": "critical"
            }
        }

    Structured matcher is kept supported.
    """
    if not isinstance(matchers, dict):
        return {}

    normalized = {}
    labels = {}

    if isinstance(matchers.get("labels"), dict):
        labels.update(matchers["labels"])

    if isinstance(matchers.get("fields"), dict):
        normalized["fields"] = matchers["fields"]

    for key, value in matchers.items():
        if key in {"labels", "fields"}:
            continue

        if key in {"source", "title", "title_regex"}:
            normalized[key] = value
            continue

        # For service rules, unknown top-level keys are Prometheus labels.
        # Keep severity as label too, because incoming Prometheus alerts usually
        # carry it in labels.severity.
        labels[key] = value

    if labels:
        normalized["labels"] = labels

    return normalized


def get_nested_value(payload, key):
    """Read a value from a nested dict using dot notation."""
    current = payload

    for part in key.split("."):
        if not isinstance(current, dict):
            return None

        current = current.get(part)

    return current


def match_value(actual_value, expected_value):
    """Match a value against a matcher."""
    if isinstance(expected_value, list):
        return actual_value in expected_value

    if isinstance(expected_value, dict):
        operator = expected_value.get("op")

        if operator is not None:
            operator = {
                "eq": "equals",
                "ne": "not_equals",
                "neq": "not_equals",
            }.get(str(operator).strip().lower(), str(operator).strip().lower())
            operator_value = expected_value.get("value")
            actual_text = str(actual_value)
            expected_text = str(operator_value)

            if operator == "regex":
                return safe_regex_search(
                    operator_value,
                    actual_value,
                )

            if operator == "equals":
                return actual_text == expected_text

            if operator == "not_equals":
                return actual_text != expected_text

            if operator == "contains":
                return str(operator_value or "") in str(actual_value or "")

            if operator == "not_contains":
                return str(operator_value or "") not in str(actual_value or "")

            return False

        if "regex" in expected_value:
            return safe_regex_search(
                expected_value["regex"],
                actual_value,
            )

        if "not" in expected_value:
            return not match_value(
                actual_value,
                expected_value["not"],
            )

        if "contains" in expected_value:
            return str(expected_value["contains"]) in str(actual_value or "")

    return str(actual_value) == str(expected_value)


def match_alert(alert_data, matchers):
    """Check whether normalized alert data matches a matcher object."""
    matchers = normalize_matchers(matchers)

    if not matchers:
        return True

    for key in ["source", "title"]:
        if key in matchers and not match_value(alert_data.get(key), matchers[key]):
            return False

    if "title_regex" in matchers and not safe_regex_search(
        matchers["title_regex"],
        alert_data.get("title") or "",
    ):
        return False

    labels = alert_data.get("labels") or {}

    for label_name, expected_value in (matchers.get("labels") or {}).items():
        actual_value = labels.get(label_name)

        if actual_value is None and label_name in {"severity", "status"}:
            actual_value = alert_data.get(label_name)

        if not match_value(actual_value, expected_value):
            return False

    for field_name, expected_value in (matchers.get("fields") or {}).items():
        if not match_value(
            get_nested_value(alert_data, field_name),
            expected_value,
        ):
            return False

    return True
