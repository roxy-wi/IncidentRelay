from unittest.mock import patch

from prometheus_client import CONTENT_TYPE_LATEST
from prometheus_client.parser import text_string_to_metric_families

import app.services.readiness as metrics_readiness
from app.settings import Config
from app.version import get_service_version


def _parse(response):
    """Parse a /metrics response into a name -> family mapping."""
    body = response.get_data(as_text=True)
    families = {}
    for family in text_string_to_metric_families(body):
        families[family.name] = family
    return families


def _enabled(monkeypatch, token=""):
    """Enable the endpoint for one test (monkeypatch undoes it after)."""
    monkeypatch.setattr(Config, "METRICS_ENABLED", True)
    monkeypatch.setattr(Config, "METRICS_AUTH_TOKEN", token)


class _BrokenDatabase:
    """
    Database stub whose connection handling works but queries fail.

    The failure message mimics a Peewee OperationalError carrying the
    connection string, so the test can assert that credentials from a
    database exception never reach the exposition body.
    """

    def __init__(self):
        self._closed = True

    def is_closed(self):
        return self._closed

    def connect(self, reuse_if_open=False):
        self._closed = False

    def execute_sql(self, query):
        raise RuntimeError(
            "postgresql://incidentrelay:super-secret@db.internal/incidentrelay"
        )

    def close(self):
        self._closed = True


def test_metrics_disabled_by_default(client):
    """Without configuration the endpoint must not exist at all (404)."""
    response = client.get("/metrics")

    assert response.status_code == 404


def test_metrics_disabled_by_default_even_with_auth_header(client):
    """A bearer header must not unlock a disabled endpoint."""
    response = client.get(
        "/metrics",
        headers={"Authorization": "Bearer any-token"},
    )

    assert response.status_code == 404


def test_metrics_disabled_post_also_answers_404(client):
    """
    Flask answers 405 during URL matching before any view code runs, which
    would reveal that /metrics exists. While disabled, every method must
    behave as if the endpoint does not exist.
    """
    response = client.post("/metrics")
    assert response.status_code == 404

    response = client.delete("/metrics")
    assert response.status_code == 404


def test_metrics_disabled_options_also_answers_404(client):
    """
    Flask answers automatic OPTIONS with 200 before any view code runs,
    so /metrics must list OPTIONS to keep the endpoint undiscoverable.
    """
    response = client.options("/metrics")

    assert response.status_code == 404


def test_metrics_enabled_post_answers_405(client, monkeypatch):
    """While enabled, non-GET methods get the regular 405."""
    _enabled(monkeypatch)

    response = client.post("/metrics")

    assert response.status_code == 405


def test_metrics_enabled_options_answers_405(client, monkeypatch):
    """Listing OPTIONS keeps the enabled endpoint's 405 consistent."""
    _enabled(monkeypatch)

    response = client.options("/metrics")

    assert response.status_code == 405


def test_metrics_enabled_returns_prometheus_exposition(client, monkeypatch):
    """When enabled, /metrics serves valid Prometheus text exposition."""
    _enabled(monkeypatch)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.content_type == CONTENT_TYPE_LATEST

    families = _parse(response)
    assert "incidentrelay_build_info" in families
    assert "incidentrelay_database_up" in families
    assert "incidentrelay_migrations_pending" in families
    assert "incidentrelay_http_requests" in families


def test_metrics_build_info_reports_service_version(client, monkeypatch):
    """build_info must carry the running version, for deploy dashboards."""
    _enabled(monkeypatch)

    response = client.get("/metrics")
    families = _parse(response)

    version_samples = [
        sample.value
        for sample in families["incidentrelay_build_info"].samples
        if sample.labels.get("version") == get_service_version()
    ]
    assert version_samples == [1.0]


def test_metrics_reports_healthy_database(client, monkeypatch):
    """Migrated and reachable database: db up = 1, pending migrations = 0."""
    _enabled(monkeypatch)

    response = client.get("/metrics")

    assert response.status_code == 200
    families = _parse(response)

    def gauge_value(name):
        return families[name].samples[0].value

    assert gauge_value("incidentrelay_database_up") == 1.0
    assert gauge_value("incidentrelay_migrations_pending") == 0.0


def test_metrics_http_counter_counts_requests(client, monkeypatch):
    """HTTP requests must show up in the request counter while enabled."""
    _enabled(monkeypatch)

    client.get("/metrics")
    client.get("/metrics")

    response = client.get("/metrics")
    families = _parse(response)

    get_200 = [
        sample.value
        for sample in families["incidentrelay_http_requests"].samples
        if sample.labels == {"method": "GET", "status": "200"}
        and sample.name.endswith("_total")
    ]
    assert get_200
    assert max(get_200) >= 3


def test_metrics_latency_histogram_observes_requests(client, monkeypatch):
    _enabled(monkeypatch)

    client.get("/metrics")
    response = client.get("/metrics")

    families = _parse(response)
    counts = [
        sample.value
        for sample in families[
            "incidentrelay_http_request_duration_seconds"
        ].samples
        if sample.name.endswith("_count")
        and sample.labels.get("method") == "GET"
    ]
    assert counts
    assert max(counts) >= 1


def test_metrics_endpoint_survives_database_outage(client, monkeypatch):
    """Broken database must not break /metrics: db_up=0, body stays clean."""
    _enabled(monkeypatch)

    with patch.object(
        metrics_readiness,
        "init_database",
        lambda: _BrokenDatabase(),
    ):
        response = client.get("/metrics")

    assert response.status_code == 200

    families = _parse(response)
    assert families["incidentrelay_database_up"].samples[0].value == 0.0
    assert "incidentrelay_migrations_pending" not in families

    body = response.get_data(as_text=True)
    assert "RuntimeError" not in body
    assert "Traceback" not in body
    assert "super-secret" not in body
    assert "db.internal" not in body


def test_metrics_endpoint_survives_database_init_failure(client, monkeypatch):
    """
    The implicit DB connect is bypassed for /metrics (app/__init__.py),
    and the scrape-time probe itself must swallow init failures too.
    """
    _enabled(monkeypatch)

    def broken_init():
        raise RuntimeError("connection refused")

    with patch.object(metrics_readiness, "init_database", broken_init):
        response = client.get("/metrics")

    assert response.status_code == 200

    families = _parse(response)
    assert families["incidentrelay_database_up"].samples[0].value == 0.0


def test_metrics_served_while_app_database_connect_fails(client, monkeypatch):
    _enabled(monkeypatch)

    from app.db import database_proxy

    # Make sure before_request would really attempt a connect if the
    # bypass were removed.
    database_proxy.obj.close()

    def broken_connect(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(database_proxy.obj, "connect", broken_connect)

    response = client.get("/metrics")

    assert response.status_code == 200


def test_metrics_migration_check_failure_degrades_gauges(client, monkeypatch):
    _enabled(monkeypatch)

    with patch.object(
        metrics_readiness,
        "get_migration_files",
        side_effect=OSError("disk gone"),
    ):
        response = client.get("/metrics")

    assert response.status_code == 200

    families = _parse(response)
    assert families["incidentrelay_database_up"].samples[0].value == 1.0
    assert "incidentrelay_migrations_pending" not in families


def test_metrics_token_required_when_configured(client, monkeypatch):
    """With a token configured, requests without it get 401."""
    _enabled(monkeypatch, token="correct-horse-battery-staple")

    response = client.get("/metrics")

    assert response.status_code == 401


def test_metrics_token_wrong_value_rejected(client, monkeypatch):
    """A wrong bearer token must get 401."""
    _enabled(monkeypatch, token="correct-horse-battery-staple")

    response = client.get(
        "/metrics",
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401


def test_metrics_non_ascii_token_rejected_not_500(client, monkeypatch):
    """
    hmac.compare_digest rejects non-ASCII str arguments, so the token
    check compares bytes. A scanner sending a latin-1 header value must
    get 401, not an unhandled TypeError (500).
    """
    _enabled(monkeypatch, token="correct-horse-battery-staple")

    response = client.get(
        "/metrics",
        headers={"Authorization": "Bearer café"},
    )

    assert response.status_code == 401


def test_metrics_non_ascii_configured_token_accepted(client, monkeypatch):
    """A non-ASCII token from the UTF-8 config file must still work."""
    _enabled(monkeypatch, token="café-token")

    response = client.get(
        "/metrics",
        headers={"Authorization": "Bearer café-token"},
    )

    assert response.status_code == 200


def test_metrics_token_correct_value_accepted(client, monkeypatch):
    """The configured bearer token grants access to the exposition."""
    _enabled(monkeypatch, token="correct-horse-battery-staple")

    response = client.get(
        "/metrics",
        headers={"Authorization": "Bearer correct-horse-battery-staple"},
    )

    assert response.status_code == 200

    body = response.get_data(as_text=True)
    assert "correct-horse-battery-staple" not in body
    families = _parse(response)
    assert "incidentrelay_database_up" in families
