"""Live Change Intelligence controls, authorization and transactional audit."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.api.openapi.spec import build_openapi_spec
from app.api.schemas.system_settings import SystemSettingsUpdate
from app.modules.db import tokens_repo
from app.modules.db.models import AuditLog, ChangeEvent, ChangeJob, SystemSettings, User
from app.services import system_settings
from app.services.change_intelligence import worker
from app.services.integrations.auth import hash_token
from app.settings import Config, Settings, settings
from tests.factories import create_group, create_user
from tests.integrations.test_change_events import intake, send, setup_identity
from tests.integrations.test_change_integration_groups import headers
from tests.integrations.test_change_integrations import credential

__all__ = ["intake", "setup_identity"]
URL = "/api/admin/system-settings"
ACTION = "system_settings.updated"
ADVANCED_DEFAULTS = {
    "change_max_future_seconds": 300,
    "change_events_per_minute": 600,
    "change_events_per_change": 1000,
    "change_worker_interval_seconds": 5,
    "change_worker_jobs_per_tick": 20,
    "change_worker_batch_size": 100,
    "change_worker_lease_seconds": 60,
    "change_worker_max_attempts": 8,
    "change_worker_retry_base_seconds": 5,
    "change_worker_retry_max_seconds": 300,
    "change_pending_ttl_seconds": 604800,
    "change_pending_poll_seconds": 60,
}


def test_apply_without_restart_and_resume_existing_jobs(client, intake, admin_headers):
    def update(**switches):
        response = client.patch(URL, headers=admin_headers, json=switches)
        assert response.status_code == 200, response.json
        return response.json

    state = update(change_worker_enabled=False)
    assert state["change_worker_enabled"] is False
    accepted = send(client, intake)
    assert accepted.status_code == 201
    assert accepted.json["correlation_status"] == "not_enabled"
    job = ChangeJob.get(ChangeJob.job_type == "resolve_references")
    assert worker.process_change_jobs() == 0
    assert ChangeJob.get_by_id(job.id).state == "pending"

    update(change_intake_enabled=False, change_worker_enabled=True)
    assert send(client, intake, event_id="second").status_code == 404
    assert ChangeEvent.select().count() == 1
    assert worker.process_change_jobs() > 0
    assert ChangeJob.get_by_id(job.id).state == "done"

    update(change_intake_enabled=True)
    retry = send(client, intake)
    assert retry.status_code == 200
    assert retry.json["event_uid"] == accepted.json["event_uid"]
    assert retry.json["correlation_status"] == "queued"
    assert ChangeEvent.select().count() == 1


def test_audit_records_actor_and_effective_diff_once(client, admin_headers, admin_user):
    body = {"change_intake_enabled": True, "change_worker_enabled": False}
    for _ in range(2):
        result = client.patch(URL, headers=admin_headers, json=body)
        assert result.status_code == 200
    assert client.get(URL, headers=admin_headers).json == result.json
    logs = list(AuditLog.select().where(AuditLog.action == ACTION))
    assert len(logs) == 1
    log = logs[0]
    assert log.user_id == admin_user.id and log.created_at
    assert log.data["changes"] == {
        "change_intake_enabled": {"before": False, "after": True},
        "change_worker_enabled": {"before": True, "after": False},
    }


@pytest.mark.parametrize("role", [None, "viewer", "user_admin"])
def test_only_global_admin_can_read_or_edit(client, role, monkeypatch):
    monkeypatch.setattr(Config, "API_AUTH_REQUIRED", False)
    auth = headers(create_user(group=create_group(), group_role=role)) if role else {}
    expected = 403 if role else 401
    assert client.get(URL, headers=auth).status_code == expected
    assert client.patch(URL, headers=auth, json={"change_intake_enabled": True}).status_code == expected
    current = SystemSettings.get_by_id(1)
    assert current.change_intake_enabled is False and current.change_worker_enabled is True


@pytest.mark.parametrize("body", [
    {}, {"change_worker_enabled": None}, {"change_intake_enabled": "false"},
    {"change_worker_enabled": 1}, {"other": True}, {"change_intake_enabled": True, "other": False},
])
def test_invalid_settings_preserve_values(client, admin_headers, body):
    assert client.patch(URL, headers=admin_headers, json=body).status_code == 400
    current = SystemSettings.get_by_id(1)
    assert current.change_intake_enabled is False and current.change_worker_enabled is True
    assert not AuditLog.select().where(AuditLog.action == ACTION).exists()


def test_settings_read_only_database_values(
    client, admin_headers, monkeypatch, tmp_path
):
    config = tmp_path / "test.conf"
    config.write_text(
        "[change_intelligence]\nintake_enabled = true\nworker_enabled = false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "parser", Settings(config).parser)
    monkeypatch.setenv("INCIDENTRELAY__CHANGE_INTELLIGENCE__INTAKE_ENABLED", "true")
    monkeypatch.setenv(
        "INCIDENTRELAY__CHANGE_INTELLIGENCE__WORKER_ENABLED__FILE", str(tmp_path / "gone")
    )
    monkeypatch.setenv("INCIDENTRELAY__CHANGE_INTELLIGENCE__WORKER_INTERVAL_SECONDS", "999")
    state = client.get(URL, headers=admin_headers).json
    assert state == {
        **ADVANCED_DEFAULTS,
        "change_intake_enabled": False,
        "change_worker_enabled": True,
    }
    response = client.patch(URL, headers=admin_headers, json={"change_worker_enabled": False})
    assert response.status_code == 200
    assert system_settings.get_settings().change_worker_enabled is False
    assert system_settings.get_settings().change_intake_enabled is False


def test_audit_failure_rolls_back_both_switches(client, admin_headers, admin_user, monkeypatch):
    before = client.get(URL, headers=admin_headers).json

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(system_settings, "record_audit", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        system_settings.update_settings(
            SystemSettingsUpdate(change_intake_enabled=True, change_worker_enabled=False), actor_id=admin_user.id
        )
    assert client.get(URL, headers=admin_headers).json == before


def test_concurrent_edits_preserve_both_values_and_audit(db, admin_user, client, admin_headers):
    ready = Barrier(2)
    other_admin = create_user(is_admin=True)

    def edit(values, actor_id):
        with db.connection_context():
            ready.wait(timeout=10)
            system_settings.update_settings(SystemSettingsUpdate(**values), actor_id=actor_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(edit, {"change_intake_enabled": True}, admin_user.id),
            pool.submit(edit, {"change_worker_enabled": False}, other_admin.id),
        ]
        for future in futures:
            future.result(timeout=20)
    assert client.get(URL, headers=admin_headers).json == {
        **ADVANCED_DEFAULTS,
        "change_intake_enabled": True,
        "change_worker_enabled": False,
    }
    assert AuditLog.select().where(AuditLog.action == ACTION).count() == 2


def test_settings_api_contract(app, client, admin_headers):
    response = client.get(URL, headers=admin_headers)
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json == {
        **ADVANCED_DEFAULTS, "change_intake_enabled": False, "change_worker_enabled": True,
    }
    paths = build_openapi_spec()["paths"]
    assert set(paths[URL]) == {"get", "patch"}
    properties = paths[URL]["patch"]["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert set(properties) == set(response.json)
    for name in ADVANCED_DEFAULTS:
        assert properties[name]["type"] == "integer"
        assert properties[name]["minimum"] <= response.json[name] <= properties[name]["maximum"]
    removed = "/api/admin/change-integrations/settings"
    assert removed not in paths
    assert all(rule.rule != removed for rule in app.url_map.iter_rules())


def test_group_scope_cannot_modify_global_settings(client, admin_headers):
    for suffix, body in [
        ("?group_id=1", {"change_intake_enabled": True}),
        ("", {"group_id": 1, "change_intake_enabled": True}),
    ]:
        assert client.patch(URL + suffix, headers=admin_headers, json=body).status_code == 400
    assert system_settings.get_settings().change_intake_enabled is False


@pytest.mark.parametrize("auth_required", [False, True])
def test_settings_accept_admin_personal_token_and_reject_machine_token(
    client, setup_identity, admin_user, monkeypatch, auth_required
):
    monkeypatch.setattr(Config, "API_AUTH_REQUIRED", auth_required)
    _, raw = credential(setup_identity)
    tokens_repo.create_api_token(
        "personal", "personal", hash_token("personal"), ["*"], user_id=admin_user.id
    )
    for token, status in ((raw, 403), ("personal", 200)):
        auth = {"Authorization": f"Bearer {token}"}
        assert client.get(URL, headers=auth).status_code == status
        assert client.patch(URL, headers=auth, json={"change_intake_enabled": True}).status_code == status


def test_service_rechecks_revoked_admin_before_writing(admin_user):
    User.update(is_admin=False).where(User.id == admin_user.id).execute()
    with pytest.raises(system_settings.SystemSettingsAccessDenied):
        system_settings.update_settings(SystemSettingsUpdate(change_intake_enabled=True), actor_id=admin_user.id)
    assert system_settings.get_settings().change_intake_enabled is False
    assert not AuditLog.select().where(AuditLog.action == ACTION).exists()


def test_advanced_settings_are_saved_and_audited_together(client, admin_headers):
    patch = {name: value + 1 for name, value in ADVANCED_DEFAULTS.items()}
    for _ in range(2):
        result = client.patch(URL, headers=admin_headers, json=patch)
        assert result.status_code == 200
        assert {name: result.json[name] for name in patch} == patch
    log = AuditLog.get(AuditLog.action == ACTION)
    assert AuditLog.select().where(AuditLog.action == ACTION).count() == 1
    assert log.data["changes"] == {
        name: {"before": ADVANCED_DEFAULTS[name], "after": value} for name, value in patch.items()
    }


@pytest.mark.parametrize("invalid", [True, "5", None, 1.5, 2**31])
def test_integer_settings_reject_invalid_types_and_overflow(client, admin_headers, invalid):
    result = client.patch(URL, headers=admin_headers, json={
        "change_worker_interval_seconds": invalid, "change_intake_enabled": True,
    })
    assert result.status_code == 400
    assert system_settings.get_settings().change_intake_enabled is False
    assert not AuditLog.select().where(AuditLog.action == ACTION).exists()


def test_advanced_boundaries_and_partial_retry_window(client, admin_headers):
    def patch(**values):
        return client.patch(URL, headers=admin_headers, json=values)

    assert patch(change_max_future_seconds=0, change_worker_batch_size=1000).status_code == 200
    for name, value in [
        ("change_max_future_seconds", -1), ("change_worker_lease_seconds", 9),
        ("change_worker_batch_size", 1001), ("change_worker_jobs_per_tick", 101),
        ("change_events_per_change", 10001), ("change_pending_ttl_seconds", 59),
        ("change_pending_poll_seconds", 4), ("change_worker_interval_seconds", 0),
    ]:
        assert patch(**{name: value}).status_code == 400
    before = client.get(URL, headers=admin_headers).json
    assert patch(change_worker_retry_max_seconds=4, change_intake_enabled=True).status_code == 400
    assert client.get(URL, headers=admin_headers).json == before
    assert patch(change_worker_retry_base_seconds=4, change_worker_retry_max_seconds=4).status_code == 200
    assert patch(change_worker_retry_base_seconds=5).status_code == 400


def test_conflicting_concurrent_retry_edits_recheck_the_locked_row(db, admin_user):
    ready = Barrier(2)
    other_admin = create_user(is_admin=True)

    def edit(values, actor_id):
        with db.connection_context():
            ready.wait(timeout=10)
            try:
                system_settings.update_settings(SystemSettingsUpdate(**values), actor_id=actor_id)
            except system_settings.InvalidRetryWindow:
                return False
            return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        higher_base = pool.submit(edit, {"change_worker_retry_base_seconds": 200}, admin_user.id)
        lower_max = pool.submit(edit, {"change_worker_retry_max_seconds": 100}, other_admin.id)
        assert sorted([higher_base.result(timeout=20), lower_max.result(timeout=20)]) == [False, True]

    row = system_settings.get_settings()
    assert (row.change_worker_retry_base_seconds, row.change_worker_retry_max_seconds) in {
        (200, 300), (5, 100),
    }
    assert AuditLog.select().where(AuditLog.action == ACTION).count() == 1
