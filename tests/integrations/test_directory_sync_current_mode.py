"""Switch authoritative duty checks independently of the calendar import."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.modules.common import utc_now
from app.modules.db.models import DirectorySyncCurrent as Current, DirectorySyncSource as Source, Rotation
from app.services.directory_sync import service
from app.services.directory_sync.config import SyncConfig, SyncError, current_api_enabled
from app.services.directory_sync.runtime import import_metadata
from app.services.oncall import get_current_oncall_user
from tests.integrations.test_directory_sync import (
    binding,
    fetched as fetched,
    snapshot as snapshot,
    source as source,
)

URL = "/api/admin/directory-sync"


def save(client, headers, source_id, **config):
    source = Source.get_by_id(source_id)
    response = client.put(f"{URL}/{source_id}", headers=headers, json={
        "name": source.name, "group_id": source.group_id, "revision": source.revision,
        "enabled": source.enabled, "config": {**source.config, **config},
    })
    assert response.status_code == 200, response.json
    return response.json


def test_switching_current_api_preserves_import_and_uses_saved_replacements(
    client, admin_headers, source, fetched, monkeypatch,
):
    source.enabled = True
    source.save()
    service.run(source.id)
    calls = []

    def fetch_current(_client, ids):
        calls.append(ids)
        return [{"id": key, "status": "active", "user_id": "u1"} for key in ids]

    monkeypatch.setattr(service, "fetch_current", fetch_current)
    service.refresh_current(source.id)
    rotation = Rotation.get_by_id(binding(source, "rotation", "s1").local_id)
    assert get_current_oncall_user(rotation).username == "first"
    Source.update(current_error="current: previous error").where(Source.id == source.id).execute()
    before = Source.get_by_id(source.id)
    disabled = save(client, admin_headers, source.id, current_enabled=False)
    assert disabled["approved"] and disabled["enabled"]
    assert disabled["next_current_at"] is None
    assert disabled["current_error"] is None
    assert disabled["config"]["operations"] == before.config["operations"]
    assert disabled["config"]["current_fields"] == before.config["current_fields"]
    assert not Current.select().exists()
    assert get_current_oncall_user(rotation).username == "second"  # Imported replacement.
    assert "current_status" not in import_metadata("rotation", rotation.id)
    assert service.process_due_current() == 0
    service.refresh_current(source.id)  # Direct invocations must also honor the switch.
    assert len(calls) == 1
    after = Source.get_by_id(source.id)
    assert after.last_success_at == before.last_success_at
    assert after.last_current_at == before.last_current_at
    assert after.next_run_at == before.next_run_at
    assert after.headers_encrypted == before.headers_encrypted
    assert after.pending_mode is None

    enabled = save(client, admin_headers, source.id, current_enabled=True, current_interval_seconds=45)
    assert enabled["approved"]
    assert enabled["next_current_at"] is not None
    assert get_current_oncall_user(rotation) is None  # Wait for a fresh API answer.
    assert service.process_due_current() == 1
    assert len(calls) == 2
    assert get_current_oncall_user(rotation).username == "first"
    after = Source.get_by_id(source.id)
    assert after.next_current_at == after.last_current_at + timedelta(seconds=45)
    assert after.last_success_at == before.last_success_at
    assert after.next_run_at == before.next_run_at


def test_current_switch_and_interval_preserve_prepared_preview(client, admin_headers, source, fetched):
    preview = service.run(source.id, mode="preview")
    for enabled in (False, True):
        saved = save(client, admin_headers, source.id, current_enabled=enabled, current_interval_seconds=30)
        assert saved["preview_token"] == preview["preview_token"]
        assert not saved["approved"]
    service.run(source.id, mode="apply", preview_token=preview["preview_token"])
    assert Source.get_by_id(source.id).approved_revision == saved["revision"]


@pytest.mark.parametrize("cached_status", ["active", "gap", "unavailable"])
def test_schedule_mode_ignores_any_api_cache(source, fetched, cached_status):
    source.config["current_enabled"] = False
    source.save()
    service.run(source.id)
    rotation = Rotation.get_by_id(binding(source, "rotation", "s1").local_id)
    Current.create(source=source, rotation=rotation, user=binding(source, "user", "u1").local_id,
                   status=cached_status, observed_at=utc_now(), valid_until=utc_now() + timedelta(hours=1))
    assert get_current_oncall_user(rotation).username == "second"
    assert "current_status" not in import_metadata("rotation", rotation.id)


def test_legacy_source_keeps_existing_current_api_behavior(source, fetched):
    source.config.pop("current_enabled", None)
    source.save()
    assert current_api_enabled(source.config)
    assert SyncConfig.model_validate(source.config).current_enabled is True
    service.run(source.id)
    rotation = Rotation.get_by_id(binding(source, "rotation", "s1").local_id)
    assert get_current_oncall_user(rotation) is None
    source.config["operations"].pop("current")
    source.save()
    assert not current_api_enabled(source.config)
    assert get_current_oncall_user(rotation).username == "second"


@pytest.mark.parametrize("value", [None, "false", "true", 0, 1])
def test_current_enabled_requires_a_boolean(source, value):
    with pytest.raises(ValidationError):
        SyncConfig.model_validate({**source.config, "current_enabled": value})


@pytest.mark.parametrize("interval", [10, 45, 90, 3600])
def test_current_interval_save_and_cache_freshness(client, admin_headers, source, fetched, monkeypatch, interval):
    source.enabled = True
    source.save()
    service.run(source.id)
    monkeypatch.setattr(service, "fetch_current", lambda _client, ids: [
        {"id": key, "status": "active", "user_id": "u1"} for key in ids
    ])
    service.refresh_current(source.id)
    before = Source.get_by_id(source.id)
    saved = save(client, admin_headers, source.id, current_interval_seconds=interval)
    assert saved["approved"]
    expected_delay = min(interval, max(5, source.config["current_max_age_seconds"] - 5))
    assert Source.get_by_id(source.id).next_current_at == before.last_current_at + timedelta(seconds=expected_delay)


@pytest.mark.parametrize("interval", [0, 9, 3601])
def test_current_interval_bounds(source, interval):
    with pytest.raises(ValidationError):
        SyncConfig.model_validate({**source.config, "current_interval_seconds": interval})


def test_scheduler_rechecks_switch_before_fetch(source, fetched, monkeypatch):
    source.enabled = True
    source.save()
    service.run(source.id)
    original_claim = service.claim

    def disable_before_claim(source_id, **kwargs):
        changed = Source.get_by_id(source_id)
        changed.config["current_enabled"] = False
        changed.revision += 1
        changed.approved_revision = changed.revision
        changed.save()
        return original_claim(source_id, **kwargs)

    def unexpected_fetch(*_args):
        pytest.fail("A disabled current API must not be called")

    monkeypatch.setattr(service, "claim", disable_before_claim)
    monkeypatch.setattr(service, "fetch_current", unexpected_fetch)
    service.process_due_current()
    assert not Current.select().exists()
    assert Source.get_by_id(source.id).current_lease is None


def test_expired_worker_cannot_restore_current_cache_or_error_after_disable(
    client, admin_headers, source, fetched, monkeypatch,
):
    service.run(source.id)

    def disable_during_fetch(_client, ids):
        Source.update(current_lease_until=utc_now() - timedelta(seconds=1)).where(Source.id == source.id).execute()
        save(client, admin_headers, source.id, current_enabled=False)
        return [{"id": key, "status": "active", "user_id": "u1"} for key in ids]

    monkeypatch.setattr(service, "fetch_current", disable_during_fetch)
    with pytest.raises(SyncError, match="lease changed"):
        service.refresh_current(source.id)
    after = Source.get_by_id(source.id)
    assert after.current_error is None
    assert not after.config["current_enabled"]
    assert after.current_lease is None
    assert not Current.select().exists()
