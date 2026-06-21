import pytest

from app.services.integrations.normalizers.librenms import (
    normalize_librenms,
    normalize_librenms_severity,
    normalize_librenms_status,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", "resolved"),
        (0, "resolved"),
        ("ok", "resolved"),
        ("clear", "resolved"),
        ("cleared", "resolved"),
        ("recover", "resolved"),
        ("recovery", "resolved"),
        ("recovered", "resolved"),
        ("resolve", "resolved"),
        ("resolved", "resolved"),
        ("closed", "resolved"),
        ("1", "firing"),
        (1, "firing"),
        ("2", "firing"),
        ("alert", "firing"),
        ("firing", "firing"),
        (None, "firing"),
        ("", "firing"),
    ],
)
def test_normalize_librenms_status(value, expected):
    assert normalize_librenms_status(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("critical", "critical"),
        ("crit", "critical"),
        ("error", "critical"),
        ("err", "critical"),
        ("high", "critical"),
        ("warning", "warning"),
        ("warn", "warning"),
        ("medium", "warning"),
        ("info", "info"),
        ("informational", "info"),
        ("notice", "info"),
        ("low", "info"),
        ("ok", "info"),
        ("clear", "info"),
        ("normal", "info"),
        ("custom", "custom"),
        ("", "info"),
        (None, "info"),
    ],
)
def test_normalize_librenms_severity(value, expected):
    assert normalize_librenms_severity(value) == expected


def test_normalize_librenms_full_payload():
    result = normalize_librenms({
        "id": "12345",
        "uid": "lnms-alert-12345",
        "state": "1",
        "severity": "critical",
        "title": "Device down",
        "message": "Device router1 is unreachable",
        "hostname": "router1",
        "device_id": "77",
        "ip": "10.0.0.1",
        "os": "ios",
        "type": "network",
        "hardware": "Cisco IOS",
        "version": "17.9",
        "location": "DC1",
        "rule": "Device down",
        "timestamp": "2026-06-17 10:00:00",
        "team": "sre",
        "librenms_url": "https://librenms.example.com",
        "labels": {
            "environment": "prod",
        },
    })

    assert len(result) == 1

    alert = result[0]

    assert alert["source"] == "librenms"
    assert alert["team_slug"] == "sre"
    assert alert["external_id"] == "lnms-alert-12345"
    assert alert["title"] == "Device down"
    assert alert["message"] == "Device router1 is unreachable"
    assert alert["severity"] == "critical"
    assert alert["status"] == "firing"
    assert alert["payload"]["uid"] == "lnms-alert-12345"
    assert alert["dedup_key"]

    assert alert["labels"]["environment"] == "prod"
    assert alert["labels"]["hostname"] == "router1"
    assert alert["labels"]["device_id"] == "77"
    assert alert["labels"]["ip"] == "10.0.0.1"
    assert alert["labels"]["os"] == "ios"
    assert alert["labels"]["type"] == "network"
    assert alert["labels"]["hardware"] == "Cisco IOS"
    assert alert["labels"]["version"] == "17.9"
    assert alert["labels"]["location"] == "DC1"
    assert alert["labels"]["rule"] == "Device down"
    assert alert["labels"]["librenms_id"] == "12345"
    assert alert["labels"]["librenms_uid"] == "lnms-alert-12345"
    assert alert["labels"]["librenms_state"] == "1"
    assert alert["labels"]["librenms_timestamp"] == "2026-06-17 10:00:00"
    assert alert["labels"]["librenms_severity"] == "critical"
    assert alert["labels"]["event_link"] == (
        "https://librenms.example.com/device/device=router1/"
    )


def test_normalize_librenms_recovery_keeps_stable_dedup_key():
    firing = normalize_librenms({
        "uid": "lnms-alert-12345",
        "state": "1",
        "severity": "critical",
        "title": "Device down",
        "message": "Device router1 is unreachable",
        "hostname": "router1",
        "rule": "Device down",
    })[0]

    recovery = normalize_librenms({
        "uid": "lnms-alert-12345",
        "state": "0",
        "severity": "ok",
        "title": "Device down",
        "message": "Device router1 recovered",
        "hostname": "router1",
        "rule": "Device down",
    })[0]

    assert firing["status"] == "firing"
    assert recovery["status"] == "resolved"
    assert firing["external_id"] == recovery["external_id"]
    assert firing["dedup_key"] == recovery["dedup_key"]


def test_normalize_librenms_uses_rule_as_title_when_title_missing():
    alert = normalize_librenms({
        "uid": "lnms-alert-12345",
        "state": "1",
        "severity": "warning",
        "rule": "Port utilization high",
        "hostname": "switch1",
    })[0]

    assert alert["title"] == "Port utilization high"
    assert alert["message"] == "Device: switch1"
    assert alert["severity"] == "warning"
    assert alert["labels"]["hostname"] == "switch1"
    assert alert["labels"]["rule"] == "Port utilization high"


def test_normalize_librenms_builds_message_when_message_missing():
    alert = normalize_librenms({
        "uid": "lnms-alert-12345",
        "state": "1",
        "severity": "warning",
        "title": "Port utilization high",
        "rule": "High interface utilization",
        "hostname": "switch1",
        "elapsed": "5m",
    })[0]

    assert alert["message"] == (
        "Device: switch1\n"
        "Rule: High interface utilization\n"
        "Elapsed: 5m"
    )


def test_normalize_librenms_uses_labels_as_fallbacks():
    alert = normalize_librenms({
        "state": "1",
        "labels": {
            "alertname": "LibreNMS custom alert",
            "hostname": "router1",
            "severity": "warning",
            "team": "sre",
        },
    })[0]

    assert alert["source"] == "librenms"
    assert alert["team_slug"] == "sre"
    assert alert["title"] == "LibreNMS custom alert"
    assert alert["severity"] == "warning"
    assert alert["labels"]["hostname"] == "router1"
    assert alert["dedup_key"]


def test_normalize_librenms_preserves_existing_label_values():
    alert = normalize_librenms({
        "uid": "lnms-alert-12345",
        "state": "1",
        "severity": "critical",
        "title": "Device down",
        "hostname": "router1",
        "device_id": "77",
        "labels": {
            "hostname": "custom-hostname",
            "device_id": "custom-device-id",
        },
    })[0]

    assert alert["labels"]["hostname"] == "custom-hostname"
    assert alert["labels"]["device_id"] == "custom-device-id"


def test_normalize_librenms_uses_explicit_fingerprint():
    alert = normalize_librenms({
        "uid": "lnms-alert-12345",
        "state": "1",
        "severity": "critical",
        "title": "Device down",
        "hostname": "router1",
        "fingerprint": "custom-librenms-fingerprint",
    })[0]

    assert alert["dedup_key"] == "custom-librenms-fingerprint"


def test_normalize_librenms_prefers_explicit_event_link():
    alert = normalize_librenms({
        "uid": "lnms-alert-12345",
        "state": "1",
        "severity": "critical",
        "title": "Device down",
        "hostname": "router1",
        "event_link": "https://librenms.example.com/alerts/12345",
        "librenms_url": "https://librenms.example.com",
    })[0]

    assert alert["labels"]["event_link"] == (
        "https://librenms.example.com/alerts/12345"
    )


def test_normalize_librenms_builds_device_link_from_device_id_when_hostname_missing():
    alert = normalize_librenms({
        "uid": "lnms-alert-12345",
        "state": "1",
        "severity": "critical",
        "title": "Device down",
        "device_id": "77",
        "librenms_url": "https://librenms.example.com",
    })[0]

    assert alert["labels"]["device_id"] == "77"
    assert alert["labels"]["event_link"] == (
        "https://librenms.example.com/device/device=77/"
    )


def test_normalize_librenms_uses_alert_id_when_uid_missing():
    alert = normalize_librenms({
        "alert_id": "12345",
        "state": "1",
        "severity": "critical",
        "title": "Device down",
        "hostname": "router1",
    })[0]

    assert alert["external_id"] == "12345"
    assert alert["dedup_key"]
