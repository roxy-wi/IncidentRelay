import pytest

from app.services.severity import normalize_severity, normalize_severity_list


def test_normalize_severity_known_aliases():
    assert normalize_severity("crit") == "critical"
    assert normalize_severity("disaster") == "critical"
    assert normalize_severity("emergency") == "critical"
    assert normalize_severity("avg") == "medium"
    assert normalize_severity("average") == "medium"
    assert normalize_severity("warn") == "warning"
    assert normalize_severity("not_classified") == "info"
    assert normalize_severity("not classified") == "info"


def test_normalize_severity_is_case_and_space_insensitive():
    assert normalize_severity(" Critical ") == "critical"
    assert normalize_severity(" WARNING ") == "warning"
    assert normalize_severity(" Info ") == "info"


def test_normalize_severity_unknown_value_is_preserved():
    assert normalize_severity("custom-severity") == "custom-severity"


def test_normalize_severity_empty_value_returns_empty_string():
    assert normalize_severity(None) == ""
    assert normalize_severity("") == ""


def test_normalize_severity_list_accepts_none_string_and_list():
    assert normalize_severity_list(None) == []
    assert normalize_severity_list("crit") == ["critical"]
    assert normalize_severity_list(["crit", "warn", "info"]) == [
        "critical",
        "warning",
        "info",
    ]


def test_normalize_severity_list_deduplicates_values_after_normalization():
    assert normalize_severity_list(["crit", "critical", "warn", "warning"]) == [
        "critical",
        "warning",
    ]


def test_normalize_severity_list_rejects_invalid_type():
    with pytest.raises(ValueError):
        normalize_severity_list({"severity": "critical"})
