"""
Tests for liveness (/healthz) and readiness (/readyz) probes.

These endpoints exist outside the /api/ namespace so they are reachable
without authentication (Kubernetes/HAProxy/ELB probes can't carry
credentials). Behaviour is asserted directly here so regressions don't
silently break load balancer integration.
"""

from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# /healthz: liveness
# ---------------------------------------------------------------------------


def test_healthz_returns_200_and_ok_status(client):
    """/healthz returns 200 with {"status": "ok"} when the process is alive."""
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_healthz_does_not_require_authentication(client):
    """/healthz must work without any auth — load balancers can't carry creds."""
    # No Authorization header, no cookie.
    response = client.get("/healthz")

    assert response.status_code == 200


def test_healthz_returns_200_even_when_database_is_unreachable(client):
    """
    Liveness must NOT depend on the database. A DB outage should not cause
    Kubernetes to restart the pod, since restarting would not help.
    """
    with patch(
        "app.views.health_view.init_database",
        side_effect=RuntimeError("simulated DB outage"),
    ):
        response = client.get("/healthz")

    # /healthz never even calls init_database, but the patch above guarantees
    # that if a future refactor accidentally introduced a DB call, this test
    # would catch it.
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /readyz: readiness
# ---------------------------------------------------------------------------


def test_readyz_returns_200_when_database_and_migrations_are_ok(client):
    """
    Happy path: tests/conftest.py applies all migrations before the test, so
    /readyz should report database=ok, no pending migrations and status=ready.
    """
    response = client.get("/readyz")

    assert response.status_code == 200

    body = response.get_json()
    assert body["status"] == "ready"
    assert body["database"] == "ok"
    assert "pending" not in body["migrations"]
    assert body["migrations"]["total"] >= 1
    assert body["migrations"]["applied"] >= body["migrations"]["total"]


def test_readyz_does_not_require_authentication(client):
    """/readyz must be reachable without credentials too."""
    response = client.get("/readyz")

    # Either 200 (ready) or 503 (not ready), but NOT 401/403 — auth is bypassed.
    assert response.status_code in (200, 503)


def test_readyz_returns_503_when_database_select_fails(client):
    """
    When SELECT 1 raises, readyz reports database=error, status=not_ready
    and HTTP 503 — so the load balancer drops this pod from the rotation.
    """
    def boom(*args, **kwargs):
        raise RuntimeError("connection refused")

    # We patch execute_sql on whatever instance init_database hands back,
    # via the database_proxy module-level singleton.
    from app.db import database_proxy

    with patch.object(database_proxy.obj, "execute_sql", side_effect=boom):
        response = client.get("/readyz")

    assert response.status_code == 503

    body = response.get_json()
    assert body["status"] == "not_ready"
    assert body["database"] == "error"
    assert "connection refused" in body["database_error"]
    # Migration check is skipped when the DB is down — it would be pointless.
    assert "migrations" not in body


def test_readyz_returns_503_when_pending_migrations_exist(client):
    """
    When on-disk migration files exist that are not yet applied, /readyz
    reports them in body.migrations.pending and returns 503.
    """
    # Pretend there's a new migration file on disk that hasn't been applied.
    fake_new_file = "29990101000000_simulated_pending_migration.py"

    real_files = None
    from app.views import health_view
    real_files = health_view.get_migration_files()

    with patch(
        "app.views.health_view.get_migration_files",
        return_value=list(real_files) + [fake_new_file],
    ):
        response = client.get("/readyz")

    assert response.status_code == 503

    body = response.get_json()
    assert body["status"] == "not_ready"
    assert body["database"] == "ok"

    pending = body["migrations"].get("pending") or []
    assert any(name.startswith("29990101000000") for name in pending)


def test_readyz_returns_503_when_migration_check_raises(client):
    """
    If the migration check itself blows up (e.g. file IO error), /readyz
    still surfaces the failure as 503 with a structured error instead of
    crashing the request handler.
    """
    with patch(
        "app.views.health_view.get_migration_files",
        side_effect=OSError("disk gone"),
    ):
        response = client.get("/readyz")

    assert response.status_code == 503

    body = response.get_json()
    assert body["status"] == "not_ready"
    assert body["database"] == "ok"
    assert "error" in body["migrations"]
    assert "disk gone" in body["migrations"]["error"]


# ---------------------------------------------------------------------------
# Cross-endpoint invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/healthz", "/readyz"])
def test_probes_are_outside_api_namespace(path, client):
    """
    Probes deliberately live outside /api/* so that the API authentication
    middleware (enforce_api_authentication) doesn't gate them. Make sure no
    refactor accidentally moves them under /api/.
    """
    assert not path.startswith("/api/")

    response = client.get(path)
    # The status itself is asserted elsewhere; here we just confirm we got a
    # JSON response from the probe blueprint (not an auth redirect or a 404).
    assert response.status_code in (200, 503)
    assert response.is_json
