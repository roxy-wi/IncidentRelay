import copy

import pytest

from app.services.integrations.normalizers import registry
from app.services.integrations.normalizers.registry import (
    SUPPORTED_NORMALIZER_SOURCES,
    UnknownNormalizerSource,
    normalize_for_source,
)


def test_registry_contains_all_supported_integration_normalizers():
    assert SUPPORTED_NORMALIZER_SOURCES == {
        "alertmanager",
        "aws_sns",
        "datadog",
        "grafana",
        "librenms",
        "rmon",
        "sentry",
        "uptime_kuma",
        "webhook",
        "zabbix",
    }


def test_normalize_for_source_can_protect_caller_payload():
    payload = {
        "alerts": [
            {
                "status": "firing",
                "fingerprint": "registry-1",
                "labels": {"alertname": "DiskFull"},
                "annotations": {"summary": "Disk full"},
            }
        ]
    }
    original = copy.deepcopy(payload)

    events = normalize_for_source(
        "alertmanager",
        payload,
        copy_payload=True,
    )

    assert events[0]["dedup_key"] == "registry-1"
    assert payload == original


def test_normalize_for_source_passes_sentry_context(monkeypatch):
    captured = {}

    def fake_normalizer(payload, headers, route_config):
        captured.update(
            payload=payload,
            headers=headers,
            route_config=route_config,
        )
        return [{"source": "sentry"}]

    monkeypatch.setitem(
        registry._NORMALIZERS,
        "sentry",
        fake_normalizer,
    )

    result = normalize_for_source(
        "sentry",
        {"data": "event"},
        headers={"X-Test": "header"},
        route_config={"base_url": "https://sentry.example"},
    )

    assert result == [{"source": "sentry"}]
    assert captured["headers"] == {"X-Test": "header"}
    assert captured["route_config"] == {
        "base_url": "https://sentry.example"
    }


def test_unknown_normalizer_source_is_rejected():
    with pytest.raises(UnknownNormalizerSource):
        normalize_for_source("missing", {})
