from app.services.routing.matcher.matchers import get_nested_value, match_alert, match_value


ALERT = {
    "source": "alertmanager",
    "title": "DiskFull",
    "status": "firing",
    "severity": "critical",
    "labels": {
        "alertname": "DiskFull",
        "instance": "host1",
        "team": "infra",
    },
    "annotations": {
        "summary": "Disk is full",
        "description": "/var is 95% full",
    },
}


def test_get_nested_value_reads_dotted_paths():
    assert get_nested_value(ALERT, "labels.alertname") == "DiskFull"
    assert get_nested_value(ALERT, "annotations.summary") == "Disk is full"
    assert get_nested_value(ALERT, "missing.key") is None


def test_match_value_supports_exact_list_regex_contains_and_not():
    assert match_value("critical", "critical")
    assert match_value("critical", ["warning", "critical"])
    assert match_value("DiskFull", {"regex": "^Disk"})
    assert match_value("/var is 95% full", {"contains": "95%"})
    assert match_value("critical", {"not": "warning"})

    assert not match_value("critical", "warning")
    assert not match_value("DiskFull", {"regex": "^CPU"})
    assert not match_value("/var is 95% full", {"contains": "CPU"})
    assert not match_value("critical", {"not": "critical"})


def test_match_alert_supports_top_level_labels_title_regex_and_fields():
    assert match_alert(ALERT, {})
    assert match_alert(ALERT, {"labels": {"team": "infra"}})
    assert match_alert(ALERT, {"severity": "critical"})
    assert match_alert(ALERT, {"source": "alertmanager"})
    assert match_alert(ALERT, {"title_regex": "^Disk"})
    assert match_alert(ALERT, {"fields": {"labels.alertname": {"regex": "^Disk"}}})

    assert not match_alert(ALERT, {"labels": {"team": "backend"}})
    assert not match_alert(ALERT, {"severity": "warning"})
    assert not match_alert(ALERT, {"source": "zabbix"})
    assert not match_alert(ALERT, {"title_regex": "^CPU"})


def test_match_value_supports_canonical_operator_value_format():
    assert match_value("DB", {"op": "regex", "value": "^(Listener|DB)$"})
    assert match_value("critical", {"op": "equals", "value": "critical"})
    assert match_value("critical", {"op": "eq", "value": "critical"})
    assert match_value("critical", {"op": "not_equals", "value": "warning"})
    assert match_value("critical", {"op": "neq", "value": "warning"})
    assert match_value("database-primary", {"op": "contains", "value": "database"})
    assert match_value("database-primary", {"op": "not_contains", "value": "cache"})

    assert not match_value("API", {"op": "regex", "value": "^(Listener|DB)$"})
    assert not match_value("critical", {"op": "equals", "value": "warning"})
    assert not match_value("critical", {"op": "not_equals", "value": "critical"})
    assert not match_value("database-primary", {"op": "contains", "value": "cache"})
    assert not match_value(
        "database-primary",
        {"op": "not_contains", "value": "database"},
    )


def test_match_value_rejects_unknown_operator():
    assert not match_value("critical", {"op": "unknown", "value": "critical"})
