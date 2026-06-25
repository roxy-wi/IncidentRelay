from types import SimpleNamespace

from app.services.links import build_source_event_url


def test_build_source_event_url_reads_alert_labels():
    alert = SimpleNamespace(
        labels={
            "event_link": "https://grafana.example.com/alerting/123",
        },
    )

    assert build_source_event_url(alert) == (
        "https://grafana.example.com/alerting/123"
    )


def test_build_source_event_url_reads_group_common_labels():
    group = SimpleNamespace(
        common_labels={
            "event_link": "https://sentry.example.com/issues/42",
        },
    )

    assert build_source_event_url(group) == (
        "https://sentry.example.com/issues/42"
    )


def test_build_source_event_url_uses_legacy_generator_url():
    alert = SimpleNamespace(
        labels={
            "generator_url": "https://prometheus.example.com/graph?g0.expr=up",
        },
    )

    assert build_source_event_url(alert) == (
        "https://prometheus.example.com/graph?g0.expr=up"
    )


def test_build_source_event_url_rejects_unsafe_scheme():
    alert = SimpleNamespace(
        labels={
            "event_link": "javascript:alert(1)",
        },
    )

    assert build_source_event_url(alert) == ""
