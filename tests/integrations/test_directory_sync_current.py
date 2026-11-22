"""Validate real current-duty response mappings and safe failure diagnostics."""

import json
from datetime import timedelta

import pytest

from app.modules.common import utc_now
from app.modules.db.models import DirectorySyncCurrent as Current, DirectorySyncSource as Source
from app.services.sync.directory import client as client_module, service
from app.services.sync.directory.client import ApiClient
from app.services.sync.directory.config import SyncConfig, SyncError, org_service_preset
from app.services.sync.directory.fetch import fetch_current, map_current_status
from tests.integrations.test_directory_sync import (
    binding,
    fetched as fetched,
    snapshot as snapshot,
    source as source,
)


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


def test_org_service_preset_handles_not_configured_without_losing_other_statuses(source, fetched, monkeypatch):
    service.run(source.id)
    statuses = ["active", "gap", "unavailable", "ambiguous", "not_configured"]
    monkeypatch.setattr(ApiClient, "records", lambda _client, _operation, context: [
        {"scheduleUuid": key, "status": status, "currentEmployeeUuid": "u1" if status == "active" else None}
        for key, status in zip(context["schedule_ids"], statuses, strict=True)
    ])
    config = SyncConfig.model_validate(org_service_preset())
    rows = fetch_current(ApiClient(config, {}), [f"s{i}" for i in range(5)])
    assert [row["status"] for row in rows] == ["active", "gap", "unavailable", "ambiguous", "unavailable"]
    statuses[:] = ["not_configured", "active"]
    service.refresh_current(source.id)
    assert Source.get_by_id(source.id).current_error is None
    unavailable = Current.get(Current.rotation == binding(source, "rotation", "s1").local_id)
    assert unavailable.status == "unavailable" and unavailable.user_id is None
    assert Current.get(Current.rotation == binding(source, "rotation", "s2").local_id).status == "active"
    with pytest.raises(SyncError, match="values has no entry"):
        map_current_status({"status": "unexpected-new-status"}, config.current_fields, 1)


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


@pytest.mark.parametrize("mode", ["batch", "per_schedule"])
def test_invalid_current_status_updates_healthy_slots_and_clears_failed_cache(
    client, admin_headers, source, fetched, monkeypatch, caplog, mode,
):
    source.config["current_fetch"] = mode
    # Existing sources may still use the original direct field mapping.
    source.config["current_fields"]["status"] = "status"
    source.save()
    service.run(source.id)
    statuses = ["active", "active"]

    def transport(_url, **kwargs):
        ids = json.loads(kwargs["body"])["scheduleUuids"]
        rows = [{"scheduleUuid": key, "status": status, "currentEmployeeUuid": "u1"}
                for key, status in zip(("s1", "s2"), statuses, strict=True) if key in ids]
        return 200, {}, json.dumps({"duties": rows}).encode()

    monkeypatch.setattr(client_module, "_request_once", transport)
    service.refresh_current(source.id)
    before = Source.get_by_id(source.id)
    healthy_id = binding(source, "rotation", "s1").local_id
    failed_id = binding(source, "rotation", "s2").local_id
    statuses[0] = "gap"
    statuses[1] = {"sensitive-value": "do-not-expose"}
    failed_at = utc_now() + timedelta(seconds=1)
    monkeypatch.setattr(service, "utc_now", lambda: failed_at)
    with pytest.raises(SyncError, match="response item 2.*JSON object"):
        service.refresh_current(source.id)
    after = Source.get_by_id(source.id)
    healthy = Current.get(Current.rotation == healthy_id)
    assert healthy.status == "gap" and healthy.user_id is None
    assert healthy.observed_at == failed_at
    assert not Current.select().where(Current.rotation == failed_id).exists()
    assert after.last_success_at == before.last_success_at
    assert after.last_current_at == before.last_current_at
    assert after.next_run_at == before.next_run_at
    assert after.next_current_at == failed_at + timedelta(seconds=source.config["current_interval_seconds"])
    assert after.current_lease is None
    response = client.get(f"/api/admin/directory-sync/{source.id}", headers=admin_headers)
    assert response.status_code == 200
    assert response.json["current_error"] == after.current_error
    assert "current_fields.status" in after.current_error
    assert "updated for 1 of 2 schedules; 1 failed" in after.current_error
    assert f"Rotation {failed_id}:" in after.current_error
    logs = [record.extra for record in caplog.records if record.name == "oncall.directory_sync"]
    assert any(log["operation"] == "current.status" and log["rotation_id"] == failed_id for log in logs)
    assert "do-not-expose" not in response.get_data(as_text=True)
    assert "do-not-expose" not in str(logs)
    statuses[1] = "gap"
    service.refresh_current(source.id)
    assert Source.get_by_id(source.id).current_error is None


def test_invalid_status_does_not_stop_later_batches(monkeypatch):
    config = SyncConfig.model_validate(org_service_preset())
    calls = []

    def records(_client, _operation, context):
        ids = context["schedule_ids"]
        calls.append(ids)
        return [{"scheduleUuid": key, "status": "unknown" if key == "s0" else "gap"} for key in ids]

    monkeypatch.setattr(ApiClient, "records", records)
    rows = fetch_current(ApiClient(config, {}), [f"s{i}" for i in range(501)])
    assert [len(batch) for batch in calls] == [500, 1]
    assert isinstance(rows[0]["_status_error"], SyncError)
    assert all(row["status"] == "gap" for row in rows[1:])


def test_all_invalid_statuses_clear_cached_assignees_and_report_failure(source, fetched, monkeypatch):
    service.run(source.id)
    statuses = ["active", "active"]
    monkeypatch.setattr(ApiClient, "records", lambda *_args: [
        {"scheduleUuid": key, "status": status, "currentEmployeeUuid": "u1"}
        for key, status in zip(("s1", "s2"), statuses, strict=True)
    ])
    service.refresh_current(source.id)
    before = Source.get_by_id(source.id)
    statuses[:] = ["unknown", "unknown"]
    with pytest.raises(SyncError, match="updated for 0 of 2 schedules; 2 failed"):
        service.refresh_current(source.id)
    assert not Current.select().where(Current.source == source.id).exists()
    after = Source.get_by_id(source.id)
    assert after.last_current_at == before.last_current_at
    assert after.next_run_at == before.next_run_at
    assert after.current_lease is None


@pytest.mark.parametrize("ids", [["s1"], ["s1", "s1"], ["s1", "foreign"]])
def test_partial_status_handling_does_not_relax_response_identity(monkeypatch, ids):
    config = SyncConfig.model_validate(org_service_preset())
    monkeypatch.setattr(ApiClient, "records", lambda *_args: [
        {"scheduleUuid": key, "status": "unknown"} for key in ids
    ])
    with pytest.raises(SyncError, match="every requested schedule exactly once"):
        fetch_current(ApiClient(config, {}), ["s1", "s2"])
