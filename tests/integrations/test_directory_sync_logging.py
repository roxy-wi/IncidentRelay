"""Synchronization failures reach role logs without disclosing upstream data."""

import json
import logging
from types import SimpleNamespace

import pytest
from peewee import IntegrityError, OperationalError, SqliteDatabase

from app.modules.logger import EventOnlyFilter, JsonFormatter
from app.modules.db.models import DirectorySyncBinding as Binding, DirectorySyncCurrent as Current, DirectorySyncSource as Source
from app.services.sync.directory import service
from app.services.sync.directory.config import SyncApiError, SyncBusy, SyncError
from app.services.sync.directory.diagnostics import log_failure
from tests.integrations.test_directory_sync import (
    binding,
    fetched as fetched,
    snapshot as snapshot,
    source as source,
)


@pytest.fixture
def sync_log(tmp_path, request):
    """Read the same filtered JSON output used by app and scheduler files."""
    path = tmp_path / "directory-sync.jsonl"
    logger = logging.getLogger("oncall.directory_sync")
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    handler.addFilter(EventOnlyFilter(getattr(request, "param", "scheduler")))
    old_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        yield lambda: [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(old_level)


@pytest.mark.parametrize("sync_log", ["app", "scheduler"], indirect=True)
def test_current_failure_reaches_role_log_with_safe_context(source, fetched, monkeypatch, sync_log):
    service.run(source.id)

    def fail(*_args):
        try:
            raise RuntimeError("private-response-value")
        except RuntimeError as error:
            raise SyncApiError("current: API request timed out", status_code=504) from error

    monkeypatch.setattr(service, "fetch_current", fail)
    with pytest.raises(SyncError):
        service.refresh_current(source.id)
    records = sync_log()
    assert len(records) == 1
    record = records[0]
    assert record["source_id"] == source.id
    assert record["operation"] == "current"
    assert record["error_id"]
    assert "timed out" in record["error_message"]
    assert any(frame["function"] == "fail" for cause in record["exceptions"] for frame in cause["frames"])
    assert "private-response-value" not in json.dumps(records)
    assert "PAT secret-test" not in json.dumps(records)


def test_current_foreign_key_failure_keeps_cache_and_reports_constraint(source, fetched, monkeypatch, sync_log):
    service.run(source.id)
    monkeypatch.setattr(service, "fetch_current", lambda _client, ids: [
        {"id": key, "status": "active", "user_id": "u1"} for key in ids
    ])
    service.refresh_current(source.id)
    before = Source.get_by_id(source.id)
    cache = list(Current.select().order_by(Current.id).dicts())
    person = binding(source, "user", "u1")
    Binding.update(local_id=2147483647).where(Binding.id == person.id).execute()
    with pytest.raises(SyncError, match="FOREIGN KEY"):
        service.refresh_current(source.id)
    after = Source.get_by_id(source.id)
    assert list(Current.select().order_by(Current.id).dicts()) == cache
    assert after.last_current_at == before.last_current_at
    assert after.last_success_at == before.last_success_at
    assert after.current_lease is None
    record = sync_log()[0]
    assert record["database_error"]["kind"] == "foreign_key"
    assert "IntegrityError" in {cause["type"] for cause in record["exceptions"]}
    assert "FOREIGN KEY" in after.current_error


@pytest.mark.parametrize("mode", ["preview", "run", "apply"])
def test_full_sync_errors_are_logged_once(source, fetched, monkeypatch, sync_log, mode):
    preview = service.run(source.id, mode="preview")

    def fail(*_args):
        raise SyncError("Controlled reconciliation failure")

    monkeypatch.setattr(service, "reconcile", fail)
    with pytest.raises(SyncError):
        service.run(source.id, mode=mode, preview_token=preview["preview_token"])
    assert len(sync_log()) == 1
    assert sync_log()[0]["operation"] == mode
    assert sync_log()[0]["source_id"] == source.id


def test_claim_failure_is_logged_without_raw_exception_text(source, monkeypatch, sync_log):
    def fail(*_args, **_kwargs):
        raise OperationalError("private-database-value")

    monkeypatch.setattr(service, "claim", fail)
    with pytest.raises(OperationalError):
        service.refresh_current(source.id)
    records = sync_log()
    assert len(records) == 1
    assert records[0]["error_type"] == "OperationalError"
    assert "private-database-value" not in json.dumps(records)


def test_inspect_and_validation_failures_are_logged(client, admin_headers, source, monkeypatch, sync_log):
    from app.views import directory_sync_view

    def fail(*_args, **_kwargs):
        raise SyncApiError("teams: API request timed out", status_code=504)

    monkeypatch.setattr(directory_sync_view.ApiClient, "request", fail)
    response = client.post(f"/api/admin/directory-sync/{source.id}/sample", headers=admin_headers)
    assert response.status_code == 504
    records = sync_log()
    assert len(records) == 1
    assert records[0]["source_id"] == source.id
    assert "timed out" in records[0]["error_message"]
    response = client.put(f"/api/admin/directory-sync/{source.id}", headers=admin_headers,
                          json={"headers": {"Authorization": "private-header-value"}})
    assert response.status_code == 400
    records = sync_log()
    assert len(records) == 2
    assert records[1]["http_status"] == 400
    assert "private-header-value" not in json.dumps(records)


@pytest.mark.parametrize("kind", ["unique", "not_null"])
def test_cache_write_constraint_details_are_logged(source, fetched, monkeypatch, sync_log, db, kind):
    service.run(source.id)
    monkeypatch.setattr(service, "fetch_current", lambda _client, ids: [
        {"id": key, "status": "active", "user_id": "u1"} for key in ids
    ])
    create = Current.create

    def fail(**values):
        if kind == "unique":
            create(**values)
        else:
            values["observed_at"] = None
        return create(**values)

    monkeypatch.setattr(Current, "create", fail)
    with pytest.raises(SyncError):
        service.refresh_current(source.id)
    assert not Current.select().exists()
    detail = sync_log()[0]["database_error"]
    assert detail["kind"] == kind
    if isinstance(db, SqliteDatabase) or kind == "not_null":
        column = "rotation_id" if kind == "unique" else "observed_at"
        assert detail["columns"] == [f"directory_sync_current.{column}"]
    assert Source.get_by_id(source.id).current_lease is None


@pytest.mark.parametrize("stage", ["record_error", "release_lease"])
def test_error_persistence_and_cleanup_failures_are_logged(source, fetched, monkeypatch, sync_log, stage):
    update = Source.update

    def fail_update(*args, **kwargs):
        if ((stage == "record_error" and "last_error" in kwargs)
                or (stage == "release_lease" and "lease" in kwargs and kwargs["lease"] is None)):
            raise OperationalError("private-database-value")
        return update(*args, **kwargs)

    def fail_fetch(*_args):
        raise SyncError("Controlled fetch failure")

    monkeypatch.setattr(Source, "update", fail_update)
    if stage == "record_error":
        monkeypatch.setattr(service, "fetch_snapshot", fail_fetch)
    with pytest.raises(OperationalError):
        service.run(source.id)
    records = sync_log()
    assert len(records) == 1
    assert records[0]["error_type"] == "OperationalError"
    assert records[0]["source_id"] == source.id
    assert "private-database-value" not in json.dumps(records)
    if stage == "record_error":
        assert "SyncError" in {cause["type"] for cause in records[0]["exceptions"]}


@pytest.mark.parametrize("sync_log", ["app", "scheduler"], indirect=True)
def test_busy_warning_is_not_filtered_out(source, sync_log):
    service.claim(source.id, current=True)
    with pytest.raises(SyncBusy):
        service.refresh_current(source.id)
    assert len(sync_log()) == 1
    assert sync_log()[0]["level"] == "WARNING"


@pytest.mark.parametrize("inside_operation", [False, True])
def test_worker_failures_are_logged_once(source, monkeypatch, sync_log, inside_operation):
    from app.services.scheduler import directory_sync_job

    def fail(*_args, **_kwargs):
        raise OperationalError("private-worker-value")

    if inside_operation:
        monkeypatch.setattr(service, "claim", fail)
        monkeypatch.setattr(service, "process_due_current", lambda: service.refresh_current(source.id))
    else:
        monkeypatch.setattr(service, "process_due_current", fail)
    assert directory_sync_job(current=True) == 0
    records = sync_log()
    assert len(records) == 1
    assert records[0]["operation"] == ("current" if inside_operation else "current_worker")
    assert "private-worker-value" not in json.dumps(records)


@pytest.mark.parametrize("backend", ["sqlite_unknown", "sqlite_check", "postgresql", "mysql"])
def test_driver_messages_and_unknown_identifiers_never_enter_logs(sync_log, backend):
    if backend == "sqlite_unknown":
        error = IntegrityError("UNIQUE constraint failed: private-database-value")
    elif backend == "sqlite_check":
        error = IntegrityError("CHECK constraint failed: private-database-value")
    else:
        driver = Exception("private-database-value")
        if backend == "postgresql":
            driver.pgcode = "23503"
            driver.diag = SimpleNamespace(table_name="private-database-value", column_name="private-column-value")
        else:
            driver.args = (1452, "private-database-value")
        error = IntegrityError(driver, "private-database-value")
    log_failure(error, operation="current")
    records = sync_log()
    assert "private-database-value" not in json.dumps(records)
    assert "private-column-value" not in json.dumps(records)
    assert "columns" not in records[0]["database_error"]
