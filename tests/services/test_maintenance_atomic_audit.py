"""Maintenance window edits, scope replacement, reconciliation and audit are atomic."""

from datetime import timedelta

import pytest

from app.modules.common import utc_now
from app.modules.db.models import AuditLog, MaintenanceWindow, MaintenanceWindowScope
from app.services import maintenance as maintenance_service
from app.modules.db import audit_repo
from tests.services.test_maintenance_windows import (
    create_fixed_maintenance_window,
    create_manager_context,
    create_window_payload,
)


def _fail_audit(*_args, **_kwargs):
    raise RuntimeError("audit persistence failed")


def _window(team, service):
    return create_fixed_maintenance_window(
        team=team,
        service=service,
        starts_at=utc_now() + timedelta(minutes=10),
        ends_at=utc_now() + timedelta(minutes=40),
        timezone_name="UTC",
    )


def test_create_rolls_back_window_and_scopes_when_audit_fails(
    client, db, monkeypatch,
):
    _, _, _, service, _, headers = create_manager_context()
    monkeypatch.setattr(audit_repo, "create_audit_log", _fail_audit)
    before = MaintenanceWindow.select().count()

    response = client.post(
        "/api/maintenance-windows",
        headers=headers,
        json=create_window_payload({"scope_type": "service", "service_id": service.id}),
    )
    assert response.status_code == 500, response.get_json()
    assert response.get_json()["error"] == "Internal Server Error"

    assert MaintenanceWindow.select().count() == before
    assert MaintenanceWindowScope.select().count() == 0


@pytest.mark.parametrize("operation", ["update", "cancel", "delete"])
def test_edit_rolls_back_when_audit_fails(client, db, monkeypatch, operation):
    _, team, _, service, _, headers = create_manager_context()
    window = _window(team, service)
    before = MaintenanceWindowScope.select().where(
        MaintenanceWindowScope.maintenance_window == window.id
    ).count()
    monkeypatch.setattr(audit_repo, "create_audit_log", _fail_audit)
    url = f"/api/maintenance-windows/{window.id}"

    if operation == "update":
        response = client.put(url, headers=headers, json={"name": "Changed"})
    elif operation == "cancel":
        response = client.post(url + "/cancel", headers=headers, json={"reason": "Change"})
    else:
        response = client.delete(url, headers=headers)
    assert response.status_code == 500, response.get_json()
    assert response.get_json()["error"] == "Internal Server Error"

    current = MaintenanceWindow.get_by_id(window.id)
    assert current.name == window.name
    assert current.status == window.status
    assert current.enabled == window.enabled
    assert current.deleted is False
    assert MaintenanceWindowScope.select().where(
        MaintenanceWindowScope.maintenance_window == window.id
    ).count() == before


def test_reconciliation_failure_preserves_committed_config_and_audit(
    db, monkeypatch,
):
    _, team, _, service, user, _ = create_manager_context()
    window = _window(team, service)
    window.reconciled_at = utc_now()
    window.save(only=[MaintenanceWindow.reconciled_at])
    from app.services.alerts import maintenance_state
    real_reconcile = maintenance_state.reconcile_maintenance_window

    def fail_reconciliation(*_args, **_kwargs):
        raise RuntimeError("reconciliation aborted")

    monkeypatch.setattr(
        maintenance_state,
        "reconcile_maintenance_window",
        fail_reconciliation,
    )

    # A transient reconciliation failure is logged for scheduler retry after
    # configuration and command audit have already committed.
    updated = maintenance_service.update_maintenance_window(
        window.id,
        {"name": "New name"},
        user_id=user.id,
    )
    assert updated.id == window.id
    assert MaintenanceWindow.get_by_id(window.id).name == "New name"
    assert MaintenanceWindow.get_by_id(window.id).reconciled_at is None
    monkeypatch.setattr(maintenance_state, "reconcile_maintenance_window", real_reconcile)
    real_reconcile(MaintenanceWindow.get_by_id(window.id))
    assert MaintenanceWindow.get_by_id(window.id).reconciled_at is not None
    command_logs = AuditLog.select().where(
        (AuditLog.object_type == "maintenance_window")
        & (AuditLog.object_id == window.id)
        & (AuditLog.action == "maintenance_window.update")
    )
    assert command_logs.count() == 1
    assert command_logs.get().user_id == user.id
    assert command_logs.get().data["transport"] == "api"


def test_scope_replacement_is_atomic_for_direct_repository_call(db, monkeypatch):
    from app.modules.db import maintenance_repo

    _, team, _, service, _, _ = create_manager_context()
    window = _window(team, service)
    original = [(row.scope_type, row.service_id) for row in
                maintenance_repo.list_maintenance_window_scopes(window.id)]

    def fail_create(*_args, **_kwargs):
        raise RuntimeError("scope insertion failed")

    monkeypatch.setattr(MaintenanceWindowScope, "create", fail_create)

    with pytest.raises(RuntimeError, match="scope insertion failed"):
        maintenance_repo.replace_maintenance_window_scopes(
            window.id,
            [{"scope_type": "team", "team_id": team.id}],
        )

    current = [(row.scope_type, row.service_id) for row in
               maintenance_repo.list_maintenance_window_scopes(window.id)]
    assert current == original
