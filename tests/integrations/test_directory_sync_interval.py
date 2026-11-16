"""Configured duty intervals govern saves, successful checks and retries."""

from datetime import timedelta

import pytest
from peewee import IntegrityError

from app.modules.common import utc_now
from app.modules.db.models import DirectorySyncCurrent as Current, DirectorySyncSource as Source, Rotation
from app.services.directory_sync import runtime, service
from app.services.directory_sync.config import SyncError
from app.services.oncall import get_current_oncall_user
from app.views import directory_sync_view as view
from tests.integrations.test_directory_sync import (
    binding,
    fetched as fetched,
    snapshot as snapshot,
    source as source,
)
from tests.integrations.test_directory_sync_current_mode import save


@pytest.fixture
def clock(monkeypatch):
    now = [utc_now()]
    for module in (service, view, runtime):
        monkeypatch.setattr(module, "utc_now", lambda: now[0])
    return now


def active_duties(_client, ids):
    return [{"id": key, "status": "active", "user_id": "u1"} for key in ids]


@pytest.mark.parametrize("interval", [10, 45, 300, 600, 3600])
def test_saving_interval_reschedules_from_save_time(
    client, admin_headers, source, fetched, monkeypatch, clock, interval,
):
    source.enabled = True
    source.save()
    service.run(source.id)
    monkeypatch.setattr(service, "fetch_current", active_duties)
    service.refresh_current(source.id)
    before = Source.get_by_id(source.id)
    cache = list(Current.select().order_by(Current.id).dicts())
    clock[0] += timedelta(seconds=7)
    due = clock[0] + timedelta(seconds=interval)
    saved = save(client, admin_headers, source.id, current_interval_seconds=interval)
    assert saved["approved"]
    assert saved["pending_mode"] is None
    assert saved["next_current_at"] == due.isoformat() + "Z"
    assert saved["last_current_at"] == before.last_current_at.isoformat() + "Z"
    assert Source.get_by_id(source.id).next_run_at == before.next_run_at
    assert list(Current.select().order_by(Current.id).dicts()) == cache
    # Saving an unrelated setting must not postpone the check again.
    clock[0] += timedelta(seconds=1)
    assert save(client, admin_headers, source.id, editable=True)["next_current_at"] == saved["next_current_at"]
    clock[0] = due - timedelta(seconds=1)
    assert service.process_due_current() == 0
    clock[0] = due
    assert service.process_due_current() == 1
    after = Source.get_by_id(source.id)
    assert after.next_current_at == due + timedelta(seconds=interval)
    assert after.last_current_at == due


@pytest.mark.parametrize("had_success", [False, True])
@pytest.mark.parametrize("interval", [10, 600])
def test_saving_interval_after_failure_replaces_retry_deadline(
    client, admin_headers, source, fetched, monkeypatch, clock, had_success, interval,
):
    source.enabled = True
    source.save()
    service.run(source.id)
    if had_success:
        monkeypatch.setattr(service, "fetch_current", active_duties)
        service.refresh_current(source.id)

    def fail(*_args):
        raise SyncError("current: test failure")

    monkeypatch.setattr(service, "fetch_current", fail)
    clock[0] += timedelta(seconds=1)
    with pytest.raises(SyncError):
        service.refresh_current(source.id)
    before = Source.get_by_id(source.id)
    clock[0] += timedelta(seconds=2)
    due = clock[0] + timedelta(seconds=interval)
    saved = save(client, admin_headers, source.id, current_interval_seconds=interval)
    assert saved["next_current_at"] == due.isoformat() + "Z"
    assert saved["current_error"] == before.current_error
    assert Source.get_by_id(source.id).last_current_at == before.last_current_at
    assert Source.get_by_id(source.id).next_run_at == before.next_run_at
    clock[0] = due - timedelta(seconds=1)
    assert service.process_due_current() == 0
    assert Source.get_by_id(source.id).next_current_at == due
    clock[0] = due
    assert service.process_due_current() == 0  # The attempt fails.
    assert Source.get_by_id(source.id).next_current_at == due + timedelta(seconds=interval)


@pytest.mark.parametrize("interval", [10, 60, 600, 3600])
@pytest.mark.parametrize("error_type", [SyncError, IntegrityError])
def test_failed_attempt_uses_configured_interval(source, fetched, monkeypatch, clock, interval, error_type):
    source.enabled = True
    source.config["current_interval_seconds"] = interval
    source.save()
    service.run(source.id)

    def fail(*_args):
        raise error_type("Injected failure")

    monkeypatch.setattr(service, "fetch_current", fail)
    assert service.process_due_current() == 0
    after = Source.get_by_id(source.id)
    assert after.current_error
    assert after.current_lease is None
    assert after.last_current_at is None
    assert after.next_current_at == clock[0] + timedelta(seconds=interval)


@pytest.mark.parametrize(("expiry_field", "lifetime"), [(None, 120), ("valid_until", 20), ("end", 15)])
def test_cache_expiry_does_not_shorten_poll_interval(source, fetched, monkeypatch, clock, expiry_field, lifetime):
    source.enabled = True
    source.config["current_interval_seconds"] = 600
    source.save()
    service.run(source.id)

    def fetch(client, ids):
        rows = active_duties(client, ids)
        if expiry_field:
            for row in rows:
                row[expiry_field] = (clock[0] + timedelta(seconds=lifetime)).isoformat() + "Z"
        return rows

    monkeypatch.setattr(service, "fetch_current", fetch)
    assert service.process_due_current() == 1
    due = clock[0] + timedelta(seconds=600)
    rotation = Rotation.get_by_id(binding(source, "rotation", "s1").local_id)
    assert get_current_oncall_user(rotation, now=clock[0]).username == "first"
    assert Current.get(Current.rotation == rotation.id).valid_until == clock[0] + timedelta(seconds=lifetime)
    assert Source.get_by_id(source.id).next_current_at == due
    clock[0] += timedelta(seconds=lifetime)
    assert get_current_oncall_user(rotation, now=clock[0]) is None
    assert service.process_due_current() == 0
    clock[0] = due
    assert service.process_due_current() == 1
    assert get_current_oncall_user(rotation, now=clock[0]).username == "first"


def test_paused_source_interval_save_preserves_one_manual_import_check(
    client, admin_headers, source, fetched, monkeypatch, clock,
):
    service.run(source.id)
    before = Source.get_by_id(source.id)
    clock[0] += timedelta(seconds=1)
    saved = save(client, admin_headers, source.id, current_interval_seconds=600)
    assert saved["next_current_at"] == before.next_current_at.isoformat() + "Z"
    monkeypatch.setattr(service, "fetch_current", active_duties)
    assert service.process_due_current() == 1
    saved = save(client, admin_headers, source.id, current_interval_seconds=300)
    assert saved["next_current_at"] is None
    clock[0] += timedelta(hours=1)
    assert service.process_due_current() == 0


@pytest.mark.parametrize("state", ["success", "error", "new_person"])
def test_scheduled_import_preserves_current_deadline(source, fetched, monkeypatch, clock, state):
    source.enabled = True
    source.config["current_interval_seconds"] = 600
    source.save()
    service.run(source.id)

    def fetch(client, ids):
        if state == "error":
            raise SyncError("current: test failure")
        rows = active_duties(client, ids)
        if state == "new_person":
            rows[0]["user_id"] = "not-imported-yet"
        return rows

    monkeypatch.setattr(service, "fetch_current", fetch)
    assert service.process_due_current() == (1 if state == "success" else 0)
    before = Source.get_by_id(source.id)
    clock[0] += timedelta(seconds=10)
    if state != "new_person":
        Source.update(next_run_at=clock[0]).where(Source.id == source.id).execute()
    assert service.process_due_sources() == 1
    assert Source.get_by_id(source.id).next_current_at == before.next_current_at
    assert service.process_due_current() == 0
    clock[0] = before.next_current_at
    assert service.process_due_current() == (1 if state == "success" else 0)
    assert Source.get_by_id(source.id).next_current_at == clock[0] + timedelta(seconds=600)


def test_scheduler_rechecks_deadline_after_interval_save(client, admin_headers, source, fetched, monkeypatch, clock):
    source.enabled = True
    source.save()
    service.run(source.id)
    original_claim = service.claim

    def change_before_claim(source_id, **kwargs):
        save(client, admin_headers, source_id, current_interval_seconds=600)
        return original_claim(source_id, **kwargs)

    def unexpected_fetch(*_args):
        pytest.fail("The new deadline must prevent this scheduled API request")

    monkeypatch.setattr(service, "claim", change_before_claim)
    monkeypatch.setattr(service, "fetch_current", unexpected_fetch)
    assert service.process_due_current() == 0
    assert Source.get_by_id(source.id).next_current_at == clock[0] + timedelta(seconds=600)


def test_expired_worker_cannot_overwrite_saved_interval(client, admin_headers, source, fetched, monkeypatch, clock):
    source.enabled = True
    source.save()
    service.run(source.id)

    def change_during_fetch(api_client, ids):
        Source.update(current_lease_until=clock[0] - timedelta(seconds=1)).where(Source.id == source.id).execute()
        save(client, admin_headers, source.id, current_interval_seconds=600)
        return active_duties(api_client, ids)

    monkeypatch.setattr(service, "fetch_current", change_during_fetch)
    with pytest.raises(SyncError, match="lease changed"):
        service.refresh_current(source.id)
    after = Source.get_by_id(source.id)
    assert after.next_current_at == clock[0] + timedelta(seconds=600)
    assert after.current_error is None
    assert after.current_lease is None
    assert not Current.select().exists()
