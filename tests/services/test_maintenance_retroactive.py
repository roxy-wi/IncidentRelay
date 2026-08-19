from datetime import timedelta

from app.modules.common import utc_now
from app.modules.db.models import (
    AlertGroup,
    MaintenanceWindow,
    MaintenanceWindowAlertApplication,
    MaintenanceWindowScope,
)
from app.services.alerts.maintenance_state import (
    process_maintenance_lifecycle,
    reconcile_maintenance_window,
)
from app.services.maintenance import delete_maintenance_window
from tests.services.test_maintenance_windows import (
    create_manager_context,
    create_test_alert_group,
)


def _window(team, service, *, behavior="suppress_notifications", apply=True, reactivate=True):
    now = utc_now()
    window = MaintenanceWindow.create(
        group=team.group,
        team=team,
        name="Retroactive maintenance",
        starts_at=now - timedelta(minutes=5),
        ends_at=now + timedelta(minutes=30),
        timezone="UTC",
        behavior=behavior,
        status="scheduled",
        enabled=True,
        apply_to_existing=apply,
        reactivate_on_end=reactivate,
    )
    MaintenanceWindowScope.create(
        maintenance_window=window,
        scope_type="service",
        service=service,
    )
    return window


def test_existing_group_is_not_changed_by_default(db):
    _, team, route, service, _, _ = create_manager_context()
    group = create_test_alert_group(route=route, service=service, suffix="default-off")
    group.first_seen_at = utc_now() - timedelta(minutes=10)
    group.save(only=[group.__class__.first_seen_at])
    window = _window(team, service, apply=False)

    result = reconcile_maintenance_window(window)

    group = AlertGroup.get_by_id(group.id)
    assert result["applied"] == 0
    assert group.maintenance_suppressed is False


def test_existing_group_is_suppressed_and_reactivated(db):
    _, team, route, service, _, _ = create_manager_context()
    group = create_test_alert_group(route=route, service=service, suffix="retro-on")
    group.notification_pending = True
    group.notification_due_at = utc_now()
    group.next_escalation_at = utc_now()
    group.save()
    window = _window(team, service, apply=True, reactivate=True)

    first = reconcile_maintenance_window(window)
    group = AlertGroup.get_by_id(group.id)
    assert first["applied"] == 1
    assert group.maintenance_suppressed is True
    assert group.notification_pending is False
    assert group.next_escalation_at is None

    second = reconcile_maintenance_window(window, now=window.ends_at + timedelta(seconds=1))
    group = AlertGroup.get_by_id(group.id)
    assert second["released"] == 1
    assert group.maintenance_suppressed is False
    assert group.notification_pending is True


def test_reactivate_off_retains_effect_until_option_is_enabled(db):
    _, team, route, service, _, _ = create_manager_context()
    group = create_test_alert_group(route=route, service=service, suffix="retain")
    window = _window(team, service, apply=True, reactivate=False)
    reconcile_maintenance_window(window)

    retained = reconcile_maintenance_window(
        window, now=window.ends_at + timedelta(seconds=1)
    )
    application = MaintenanceWindowAlertApplication.get(
        MaintenanceWindowAlertApplication.maintenance_window == window.id,
        MaintenanceWindowAlertApplication.alert_group == group.id,
    )
    assert retained["retained"] == 1
    assert application.active is True
    assert application.retained_at is not None

    window.reactivate_on_end = True
    window.save()
    released = reconcile_maintenance_window(
        window, now=window.ends_at + timedelta(seconds=2)
    )
    assert released["released"] == 1


def test_overlapping_windows_release_only_after_final_effect(db):
    _, team, route, service, _, _ = create_manager_context()
    group = create_test_alert_group(route=route, service=service, suffix="overlap")
    first = _window(team, service, apply=True)
    second = _window(team, service, apply=True)
    reconcile_maintenance_window(first)
    reconcile_maintenance_window(second)

    reconcile_maintenance_window(first, now=first.ends_at + timedelta(seconds=1))
    assert AlertGroup.get_by_id(group.id).maintenance_suppressed is True

    reconcile_maintenance_window(second, now=second.ends_at + timedelta(seconds=1))
    assert AlertGroup.get_by_id(group.id).maintenance_suppressed is False


def test_create_maintenance_incident_preserves_acknowledgement(db):
    _, team, route, service, user, _ = create_manager_context()
    group = create_test_alert_group(route=route, service=service, suffix="ack")
    group.status = "acknowledged"
    group.acknowledged_by = user
    group.acknowledged_at = utc_now()
    group.save()
    window = _window(
        team,
        service,
        behavior="create_maintenance_incident",
        apply=True,
    )

    reconcile_maintenance_window(window)
    assert AlertGroup.get_by_id(group.id).status == "maintenance"

    reconcile_maintenance_window(window, now=window.ends_at + timedelta(seconds=1))
    restored = AlertGroup.get_by_id(group.id)
    assert restored.status == "acknowledged"
    assert restored.acknowledged_by_id == user.id


def test_scheduler_repeated_execution_is_idempotent(db):
    _, team, route, service, _, _ = create_manager_context()
    group = create_test_alert_group(route=route, service=service, suffix="idempotent")
    window = _window(team, service, apply=True)

    first = process_maintenance_lifecycle()
    second = process_maintenance_lifecycle()

    assert first["applied"] >= 1
    assert second["applied"] == 0
    assert (
        MaintenanceWindowAlertApplication.select()
        .where(
            MaintenanceWindowAlertApplication.maintenance_window == window.id,
            MaintenanceWindowAlertApplication.alert_group == group.id,
        )
        .count()
        == 1
    )

def test_suppress_incident_rejects_retroactive_flag(client, db):
    _, team, _, service, _, headers = create_manager_context()
    now = utc_now()
    response = client.post(
        "/api/maintenance-windows",
        headers=headers,
        json={
            "name": "Invalid retroactive suppression",
            "behavior": "suppress_incident",
            "timezone": "UTC",
            "starts_at": (now + timedelta(minutes=1)).isoformat(),
            "ends_at": (now + timedelta(minutes=30)).isoformat(),
            "apply_to_existing": True,
            "reactivate_on_end": True,
            "scopes": [{"scope_type": "service", "service_id": service.id}],
        },
    )
    assert response.status_code == 400

def test_batch_size_does_not_skip_or_release_later_groups(db):
    _, team, route, service, _, _ = create_manager_context()
    groups = [
        create_test_alert_group(route=route, service=service, suffix=f"batch-{index}")
        for index in range(3)
    ]
    window = _window(team, service, apply=True)

    result = reconcile_maintenance_window(window, limit=1)

    assert result["applied"] == 3
    for group in groups:
        assert AlertGroup.get_by_id(group.id).maintenance_suppressed is True

    repeated = reconcile_maintenance_window(window, limit=1)
    assert repeated["applied"] == 0
    assert (
        MaintenanceWindowAlertApplication.select()
        .where(MaintenanceWindowAlertApplication.maintenance_window == window.id)
        .count()
        == 3
    )


def test_delete_releases_retained_effect_even_when_reactivation_is_disabled(db):
    _, team, route, service, user, _ = create_manager_context()
    group = create_test_alert_group(route=route, service=service, suffix="delete")
    window = _window(team, service, apply=True, reactivate=False)
    reconcile_maintenance_window(window)
    assert AlertGroup.get_by_id(group.id).maintenance_suppressed is True

    delete_maintenance_window(window.id, user_id=user.id)

    application = MaintenanceWindowAlertApplication.get(
        MaintenanceWindowAlertApplication.maintenance_window == window.id,
        MaintenanceWindowAlertApplication.alert_group == group.id,
    )
    assert application.active is False
    assert application.release_reason == "deleted"
    assert AlertGroup.get_by_id(group.id).maintenance_suppressed is False
