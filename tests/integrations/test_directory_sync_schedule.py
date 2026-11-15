"""Expose the actual scheduler deadlines without implying disabled work will run."""

from datetime import datetime, timedelta

import pytest

from app.modules.common import utc_now
from tests.integrations.test_directory_sync import source  # noqa: F401


@pytest.mark.parametrize("listing", [False, True])
def test_source_reports_utc_scheduler_deadlines(client, admin_headers, source, listing):
    source.enabled = True
    source.approved_revision = source.revision
    source.last_success_at = datetime(2026, 11, 15, 10, 30, 20)
    source.last_current_at = source.last_success_at + timedelta(minutes=1)
    source.next_run_at = source.last_success_at + timedelta(hours=1)
    source.next_current_at = source.last_current_at + timedelta(seconds=15)
    source.current_error = "current: response error"
    source.save()
    url = "/api/admin/directory-sync" + ("" if listing else f"/{source.id}")
    response = client.get(url, headers=admin_headers)
    assert response.status_code == 200
    data = response.json[0] if listing else response.json
    assert data["last_success_at"] == "2026-11-15T10:30:20Z"
    assert data["next_run_at"] == "2026-11-15T11:30:20Z"
    assert data["next_current_at"] == "2026-11-15T10:31:35Z"
    assert data["current_running"] is False


@pytest.mark.parametrize(("enabled", "approved", "last_sync", "current_checked", "has_current", "full_due", "current_due"), [
    (False, False, False, False, True, False, False),
    (True, False, True, True, True, False, False),
    (False, True, True, True, True, False, False),
    (False, True, True, False, True, False, True),  # One refresh after a manual import.
    (True, True, True, True, False, True, False),
    (True, True, True, True, True, True, True),
])
def test_source_only_exposes_scheduled_work(client, admin_headers, source, enabled, approved,
                                           last_sync, current_checked, has_current, full_due, current_due):
    now = utc_now()
    source.enabled = enabled
    source.approved_revision = source.revision if approved else None
    source.last_success_at = now if last_sync else None
    source.last_current_at = now if current_checked else None
    if not has_current:
        source.config["operations"].pop("current")
    source.save()
    data = client.get(f"/api/admin/directory-sync/{source.id}", headers=admin_headers).json
    assert bool(data["next_run_at"]) is full_due
    assert bool(data["next_current_at"]) is current_due


@pytest.mark.parametrize("live", [True, False])
def test_current_running_uses_live_lease(client, admin_headers, source, live):
    source.current_lease = "worker"
    source.current_lease_until = utc_now() + timedelta(minutes=1 if live else -1)
    source.save()
    data = client.get(f"/api/admin/directory-sync/{source.id}", headers=admin_headers).json
    assert data["current_running"] is live
