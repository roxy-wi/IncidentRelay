from __future__ import annotations

import logging

import app.views.health_view as health_view


class _HealthyDatabase:
    def __init__(self):
        self.closed = True

    def is_closed(self):
        return self.closed

    def connect(self, reuse_if_open=False):
        self.closed = False

    def execute_sql(self, query):
        assert query == "SELECT 1"
        return None

    def close(self):
        self.closed = True


class _BrokenDatabase(_HealthyDatabase):
    def execute_sql(self, query):
        raise RuntimeError(
            "postgresql://incidentrelay:super-secret@db.internal/incidentrelay"
        )


def test_healthz_is_independent_from_database(client, monkeypatch):
    def fail_if_called():
        raise AssertionError("healthz must not initialize the database")

    monkeypatch.setattr(health_view, "init_database", fail_if_called)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_readyz_returns_ready_when_database_and_migrations_are_ready(
    client,
    monkeypatch,
):
    database = _HealthyDatabase()
    monkeypatch.setattr(health_view, "init_database", lambda: database)
    monkeypatch.setattr(
        health_view,
        "get_applied_migrations",
        lambda: ["001_initial", "002_alerts"],
    )
    monkeypatch.setattr(
        health_view,
        "get_migration_files",
        lambda: ["001_initial.py", "002_alerts.py"],
    )

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ready",
        "database": "ok",
        "migrations": {"applied": 2, "total": 2},
    }
    assert database.is_closed() is True


def test_readyz_reports_pending_migrations_without_internal_paths(
    client,
    monkeypatch,
):
    database = _HealthyDatabase()
    monkeypatch.setattr(health_view, "init_database", lambda: database)
    monkeypatch.setattr(
        health_view,
        "get_applied_migrations",
        lambda: ["001_initial"],
    )
    monkeypatch.setattr(
        health_view,
        "get_migration_files",
        lambda: ["001_initial.py", "002_alerts.py"],
    )

    response = client.get("/readyz")
    payload = response.get_json()

    assert response.status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["database"] == "ok"
    assert payload["migrations"] == {
        "applied": 1,
        "total": 2,
        "pending": ["002_alerts"],
    }
    assert ".py" not in response.get_data(as_text=True)
    assert "/var/" not in response.get_data(as_text=True)


def test_readyz_does_not_expose_database_exception(
    client,
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(
        health_view,
        "init_database",
        lambda: _BrokenDatabase(),
    )

    with caplog.at_level(logging.WARNING, logger="oncall.health"):
        response = client.get("/readyz")

    body = response.get_data(as_text=True)
    payload = response.get_json()

    assert response.status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["database"] == "error"
    assert payload["database_error"] == "database check failed"

    assert "super-secret" not in body
    assert "postgresql://" not in body
    assert "db.internal" not in body
    assert "RuntimeError" not in body
    assert "Traceback" not in body

    assert any(
        "readyz database check failed" in record.getMessage()
        for record in caplog.records
    )


def test_readyz_does_not_expose_migration_exception(
    client,
    monkeypatch,
    caplog,
):
    database = _HealthyDatabase()
    monkeypatch.setattr(health_view, "init_database", lambda: database)

    def fail_migration_lookup():
        raise RuntimeError("migration table public.schema_migrations is missing")

    monkeypatch.setattr(
        health_view,
        "get_applied_migrations",
        fail_migration_lookup,
    )

    with caplog.at_level(logging.WARNING, logger="oncall.health"):
        response = client.get("/readyz")

    body = response.get_data(as_text=True)
    payload = response.get_json()

    assert response.status_code == 503
    assert payload["status"] == "not_ready"
    assert payload["database"] == "ok"
    assert payload["migrations"] == {"error": "migration check failed"}

    assert "public.schema_migrations" not in body
    assert "RuntimeError" not in body
    assert "Traceback" not in body

    assert any(
        "readyz migration check failed" in record.getMessage()
        for record in caplog.records
    )
