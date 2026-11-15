"""Validate real current-duty response mappings and safe failure diagnostics."""

import json
from datetime import timedelta

import pytest

from app.modules.common import utc_now
from app.modules.db.models import DirectorySyncCurrent as Current, DirectorySyncSource as Source
from app.services.directory_sync import client as client_module, service
from app.services.directory_sync.client import ApiClient
from app.services.directory_sync.config import SyncConfig, SyncError, org_service_preset
from app.services.directory_sync.fetch import fetch_current, map_current_status
from tests.integrations.test_directory_sync import fetched, snapshot, source  # noqa: F401


@pytest.mark.parametrize(("fields", "record", "reason"), [
    ({}, {}, "is not configured"),
    ({"status": "status"}, {"duty": {"status": "active"}}, "path was not found"),
    ({"status": "status"}, {"status": None}, "resolved to null"),
    ({"status": "status"}, {"status": {"value": "active"}}, "JSON object"),
    ({"status": "status"}, {"status": ["active"]}, "JSON array"),
    ({"status": "status"}, {"status": True}, "JSON boolean"),
    ({"status": "status"}, {"status": 1}, "JSON number"),
    ({"status": "status"}, {"status": " "}, "empty string"),
    ({"status": "status"}, {"status": " ACTIVE "}, "differs from 'active'"),
    ({"status": "status"}, {"status": "response-secret"}, "unsupported string"),
    ({"status": {"path": "status", "values": {"ON": "active"}}},
     {"status": "response-secret"}, "values has no entry"),
    ({"status": {"path": "status", "values": []}}, {"status": "active"}, "invalid mapping"),
    ({"status": {"value": None, "path": "missing"}}, {}, "resolved to null"),
])
def test_current_status_explains_mapping_failures_without_response_values(fields, record, reason):
    with pytest.raises(SyncError) as caught:
        map_current_status(record, fields, 3)
    message = str(caught.value)
    assert "current: response item 3: current_fields.status" in message
    assert reason in message
    assert "Expected active, gap, unavailable or ambiguous" in message
    assert "response-secret" not in message


@pytest.mark.parametrize(("spec", "record", "expected"), [
    ("duty.status", {"duty": {"status": "active"}}, "active"),
    ({"path": "status", "values": {"ON_DUTY": "active"}}, {"status": "ON_DUTY"}, "active"),
    ({"path": "missing", "default": "gap"}, {}, "gap"),
    ({"path": "status", "values": {}, "default": "unavailable"}, {"status": "OTHER"}, "unavailable"),
    ({"value": "ambiguous", "path": "missing"}, {}, "ambiguous"),
])
def test_current_status_preserves_explicit_mappings_and_defaults(spec, record, expected):
    assert map_current_status(record, {"status": spec}, 1) == expected


@pytest.mark.parametrize("mode", ["batch", "per_schedule"])
@pytest.mark.parametrize("status", ["active", "gap", "unavailable", "ambiguous"])
def test_current_status_through_http_client(monkeypatch, mode, status):
    config = SyncConfig.model_validate(org_service_preset())
    config.current_fetch = mode
    config.current_fields["status"] = {"path": "state.code", "values": {"EXTERNAL": status}}
    calls = []

    def transport(_url, **kwargs):
        ids = json.loads(kwargs["body"])["scheduleUuids"]
        calls.append(ids)
        rows = [{"scheduleUuid": key, "state": {"code": "EXTERNAL"}, "currentEmployeeUuid": "u1"}
                for key in ids]
        return 200, {}, json.dumps({"duties": rows[0] if mode == "per_schedule" else rows}).encode()

    monkeypatch.setattr(client_module, "_request_once", transport)
    rows = fetch_current(ApiClient(config, {}), ["s1", "s2"])
    assert [row["id"] for row in rows] == ["s1", "s2"]
    assert [row["status"] for row in rows] == [status, status]
    assert calls == ([["s1"], ["s2"]] if mode == "per_schedule" else [["s1", "s2"]])


@pytest.mark.parametrize("value", [None, "invalid-record", [None], [["active"]]])
def test_current_per_schedule_rejects_non_object_records(monkeypatch, value):
    config = SyncConfig.model_validate(org_service_preset())
    config.current_fetch = "per_schedule"
    monkeypatch.setattr(client_module, "_request_once", lambda *_args, **_kwargs:
                        (200, {}, json.dumps({"duties": value}).encode()))
    with pytest.raises(SyncError, match="operations.current.items must select an object"):
        fetch_current(ApiClient(config, {}), ["s1"])


def test_invalid_current_status_preserves_cache_and_full_schedule(client, admin_headers, source, fetched, monkeypatch):
    service.run(source.id)
    statuses = ["active", "active"]

    def transport(_url, **_kwargs):
        rows = [{"scheduleUuid": key, "status": status, "currentEmployeeUuid": "u1"}
                for key, status in zip(("s1", "s2"), statuses)]
        return 200, {}, json.dumps({"duties": rows}).encode()

    monkeypatch.setattr(client_module, "_request_once", transport)
    service.refresh_current(source.id)
    before = Source.get_by_id(source.id)
    cached = list(Current.select().order_by(Current.id).dicts())
    statuses[1] = {"sensitive-value": "do-not-expose"}
    failed_at = utc_now()
    monkeypatch.setattr(service, "utc_now", lambda: failed_at)
    with pytest.raises(SyncError, match="response item 2.*JSON object"):
        service.refresh_current(source.id)
    after = Source.get_by_id(source.id)
    assert list(Current.select().order_by(Current.id).dicts()) == cached
    assert after.last_success_at == before.last_success_at
    assert after.last_current_at == before.last_current_at
    assert after.next_run_at == before.next_run_at
    assert after.next_current_at == failed_at + timedelta(seconds=15)
    assert after.current_lease is None
    response = client.get(f"/api/admin/directory-sync/{source.id}", headers=admin_headers)
    assert response.status_code == 200
    assert response.json["current_error"] == after.current_error
    assert "current_fields.status" in after.current_error
    assert "do-not-expose" not in response.get_data(as_text=True)
    statuses[1] = "gap"
    service.refresh_current(source.id)
    assert Source.get_by_id(source.id).current_error is None
