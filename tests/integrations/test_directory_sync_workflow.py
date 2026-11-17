"""Save, preview and apply without manually toggling the source schedule."""

import sqlite3
from datetime import timedelta

import pytest

from app.modules.common import utc_now
from app.modules.db.models import DirectorySyncSource as Source
from app.services.directory_sync import service
from app.services.directory_sync.config import SyncBusy, SyncError
from app.views import directory_sync_view as view
from tests.integrations.test_directory_sync import (
    fetched as fetched,
    snapshot as snapshot,
    source as source,
)
from tests.integrations.test_directory_sync_current_mode import save

URL = "/api/admin/directory-sync"


@pytest.mark.parametrize("mode", ["preview", "apply"])
@pytest.mark.parametrize("credential", ["jwt", "personal_token"])
def test_status_read_during_sqlite_write_transaction(client, admin_headers, admin_user, source, db, mode, credential):
    """A second connection holding the writer lock must not block UI polling."""
    source.pending_mode = mode
    source.save()
    if credential == "personal_token":
        from tests.integrations.test_admin_api_tokens import personal_token

        _, admin_headers = personal_token(admin_user, ["directory-sync:read"], group_id=source.group_id)
    writer = sqlite3.connect(db.database, timeout=0.1)
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE directory_sync_source SET pending_mode = NULL WHERE id = ?", (source.id,))
        response = client.get(f"{URL}/{source.id}", headers=admin_headers)
        assert response.status_code == 200, response.json
        assert response.json["pending_mode"] == mode
        assert response.json["id"] == source.id
        writer.commit()
        assert client.get(f"{URL}/{source.id}", headers=admin_headers).json["pending_mode"] is None
    finally:
        writer.rollback()
        writer.close()


def queue(client, headers, source_id, action):
    source = Source.get_by_id(source_id)
    response = client.post(f"{URL}/{source_id}/{action}", headers=headers, json={
        "revision": source.revision, "preview_token": source.preview_token,
    })
    assert response.status_code == 202, response.json
    return response.json


@pytest.mark.parametrize("enabled", [False, True])
def test_import_edit_preserves_schedule_choice_until_apply(
    client, admin_headers, source, fetched, enabled,
):
    source.enabled = enabled
    source.save()
    service.run(source.id)
    before = Source.get_by_id(source.id)
    saved = save(client, admin_headers, source.id, horizon_months=3)
    assert saved["enabled"] is enabled
    assert not saved["approved"]
    assert saved["schedule_state"] == ("pending_approval" if enabled else "disabled")
    assert saved["next_run_at"] is None
    assert saved["next_current_at"] is None
    assert saved["last_success_at"] == before.last_success_at.isoformat() + "Z"
    assert service.process_due_sources() == service.process_due_current() == 0
    assert client.post(f"{URL}/{source.id}/run", headers=admin_headers,
                       json={"revision": saved["revision"]}).status_code == 409

    queue(client, admin_headers, source.id, "preview")
    assert service.process_due_sources() == 0
    ready = client.get(f"{URL}/{source.id}", headers=admin_headers).json
    assert ready["preview_token"]
    assert not ready["approved"]
    assert ready["enabled"] is enabled
    # Reopening or saving an operational option keeps the prepared plan.
    updated = save(client, admin_headers, source.id, editable=True)
    assert updated["preview_token"] == ready["preview_token"]
    queue(client, admin_headers, source.id, "apply")
    assert service.process_due_sources() == 1
    applied = client.get(f"{URL}/{source.id}", headers=admin_headers).json
    assert applied["approved"]
    assert applied["enabled"] is enabled
    assert applied["schedule_state"] == ("enabled" if enabled else "disabled")
    assert bool(applied["next_run_at"]) is enabled
    assert applied["preview_token"] is None


def test_ready_preview_is_not_consumed_by_scheduled_import(client, admin_headers, source, fetched):
    source.enabled = True
    source.save()
    service.run(source.id)
    Source.update(next_run_at=utc_now()).where(Source.id == source.id).execute()
    preview = service.run(source.id, mode="preview")
    before = Source.get_by_id(source.id)
    assert service.process_due_sources() == 0
    with pytest.raises(SyncBusy):
        service.run(source.id, scheduled=True)
    after = Source.get_by_id(source.id)
    assert after.preview_token == preview["preview_token"]
    assert after.last_success_at == before.last_success_at
    data = client.get(f"{URL}/{source.id}", headers=admin_headers).json
    assert data["schedule_state"] == "preview"
    assert data["next_run_at"] is None
    assert data["preview_token"] == preview["preview_token"]
    queue(client, admin_headers, source.id, "apply")
    assert service.process_due_sources() == 1
    assert Source.get_by_id(source.id).enabled


@pytest.mark.parametrize("changed", [False, True])
def test_expired_preview_only_resumes_previously_approved_imports(
    client, admin_headers, source, fetched, monkeypatch, changed,
):
    source.enabled = True
    source.save()
    service.run(source.id)
    if changed:
        save(client, admin_headers, source.id, horizon_months=3)
    Source.update(next_run_at=utc_now()).where(Source.id == source.id).execute()
    service.run(source.id, mode="preview")
    expired_at = Source.get_by_id(source.id).preview_until + timedelta(seconds=1)
    monkeypatch.setattr(service, "utc_now", lambda: expired_at)
    monkeypatch.setattr(view, "utc_now", lambda: expired_at)
    data = client.get(f"{URL}/{source.id}", headers=admin_headers).json
    assert data["preview_token"] is None
    assert service.process_due_sources() == (0 if changed else 1)
    assert Source.get_by_id(source.id).enabled
    assert (Source.get_by_id(source.id).approved_revision is None) is changed


@pytest.mark.parametrize("stage", ["preview", "apply"])
def test_failed_review_does_not_resume_unapproved_schedule(
    client, admin_headers, source, fetched, monkeypatch, stage,
):
    source.enabled = True
    source.save()
    service.run(source.id)
    save(client, admin_headers, source.id, horizon_months=3)

    def fail(*_args):
        raise SyncError("Injected review failure")

    if stage == "apply":
        service.run(source.id, mode="preview")
    with monkeypatch.context() as patch:
        patch.setattr(service, "fetch_snapshot" if stage == "preview" else "reconcile", fail)
        queue(client, admin_headers, source.id, stage)
        assert service.process_due_sources() == 0
    after = client.get(f"{URL}/{source.id}", headers=admin_headers).json
    assert after["enabled"] and not after["approved"]
    assert after["pending_mode"] is None
    assert after["last_error"] == "Injected review failure"
    assert service.process_due_sources() == service.process_due_current() == 0
    queue(client, admin_headers, source.id, "preview")
    service.process_due_sources()
    queue(client, admin_headers, source.id, "apply")
    assert service.process_due_sources() == 1
    assert Source.get_by_id(source.id).enabled


def test_new_source_can_request_schedule_before_first_preview(client, admin_headers, source):
    response = client.post(URL, headers=admin_headers, json={
        "name": "Scheduled after review", "group_id": source.group_id,
        "config": source.config, "enabled": True,
    })
    assert response.status_code == 201, response.json
    assert response.json["enabled"] and not response.json["approved"]
    assert response.json["schedule_state"] == "pending_approval"
    assert service.process_due_sources() == service.process_due_current() == 0


def test_disabling_schedule_during_review_preserves_preview(client, admin_headers, source, fetched):
    source.enabled = True
    source.save()
    service.run(source.id)
    save(client, admin_headers, source.id, horizon_months=3)
    preview = service.run(source.id, mode="preview")
    current = Source.get_by_id(source.id)
    response = client.put(f"{URL}/{source.id}", headers=admin_headers, json={
        "name": current.name, "group_id": current.group_id,
        "config": current.config, "revision": current.revision, "enabled": False,
    })
    assert response.status_code == 200, response.json
    assert response.json["preview_token"] == preview["preview_token"]
    queue(client, admin_headers, source.id, "apply")
    assert service.process_due_sources() == 1
    after = client.get(f"{URL}/{source.id}", headers=admin_headers).json
    assert after["approved"] and not after["enabled"]
    assert after["schedule_state"] == "disabled"
    assert after["next_run_at"] is None
