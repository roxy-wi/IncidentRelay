import re


def get_nested_value(payload, key):
    """
    Read a value from a nested dict using dot notation.
    """

    current = payload
    for part in key.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def match_value(actual_value, expected_value):
    """
    Match a value against a matcher.
    """

    if isinstance(expected_value, list):
        return actual_value in expected_value
    if isinstance(expected_value, dict):
        if "regex" in expected_value:
            return re.search(expected_value["regex"], str(actual_value or "")) is not None
        if "not" in expected_value:
            return not match_value(actual_value, expected_value["not"])
        if "contains" in expected_value:
            return str(expected_value["contains"]) in str(actual_value or "")
    return str(actual_value) == str(expected_value)


def match_alert(alert_data, matchers):
    """
    Check whether normalized alert data matches a matcher object.
    """

    if not matchers:
        return True

    for key in ["severity", "source", "title"]:
        if key in matchers and not match_value(alert_data.get(key), matchers[key]):
            return False

    if "title_regex" in matchers and re.search(matchers["title_regex"], alert_data.get("title") or "") is None:
        return False

    labels = alert_data.get("labels") or {}
    for label_name, expected_value in (matchers.get("labels") or {}).items():
        if not match_value(labels.get(label_name), expected_value):
            return False

    for field_name, expected_value in (matchers.get("fields") or {}).items():
        if not match_value(get_nested_value(alert_data, field_name), expected_value):
            return False

    return True
