from uuid import uuid4
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.modules.db.models import MaintenanceWindow, MaintenanceWindowScope
from app.api.schemas.roles import GROUP_USER_ADMIN_ROLE
from app.login import create_access_token
from app.modules.db import services_repo, maintenance_repo
from app.modules.db.models import AlertEvent, AlertGroup, Alert
from app.services.alerts.lifecycle import upsert_alert
from tests.factories import (
    add_user_to_team,
    create_group,
    create_route,
    create_team,
    create_user,
)
from app.modules.db.models import AuditLog
from app.modules.common import as_naive_datetime, as_utc_aware
from app.modules.common import utc_now


def response_items(response):
    payload = response.get_json()

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        return payload.get("items") or payload.get("data") or []

    return []


def create_test_alert_group(*, route, service, suffix, status="firing"):
    result = upsert_test_alert(
        route=route,
        service=service,
        suffix=suffix,
        status=status,
    )

    assert result.group is not None, result

    return AlertGroup.get_by_id(result.group.id)


def extract_alert_group_from_upsert_result(result):
    return result.group


def latest_maintenance_audit(action, window_id):
    return (
        AuditLog
        .select()
        .where(
            AuditLog.action == action,
            AuditLog.object_type == "maintenance_window",
            AuditLog.object_id == window_id,
        )
        .order_by(AuditLog.id.desc())
        .first()
    )


def create_fixed_maintenance_window(
    *,
    team,
    service,
    starts_at,
    ends_at,
    timezone_name="Europe/Moscow",
    status="scheduled",
    behavior="suppress_notifications",
    rrule=None,
):
    window = MaintenanceWindow.create(
        group=team.group,
        team=team,
        name=unique_slug("pytest-maintenance"),
        description="Timezone regression test",
        starts_at=starts_at,
        ends_at=ends_at,
        timezone=timezone_name,
        behavior=behavior,
        status=status,
        enabled=True,
        rrule=rrule,
    )

    MaintenanceWindowScope.create(
        maintenance_window=window,
        scope_type="service",
        service=service,
    )

    return window


def unique_slug(prefix):
    return f"{prefix}-{uuid4().hex[:12]}"


def make_headers(user):
    token, _ = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def create_service(team, *, name="Payments API", enabled=True):
    return services_repo.create_service({
        "team": team.id,
        "slug": unique_slug("service"),
        "name": name,
        "description": "",
        "service_type": "application",
        "environment": "prod",
        "criticality": "medium",
        "tier": "backend",
        "status": "operational",
        "status_source": "manual",
        "status_message": "",
        "default_rotation": None,
        "default_escalation_policy": None,
        "labels": {},
        "tags": [],
        "metadata": {},
        "enabled": enabled,
        "public": False,
        "public_name": "",
        "public_description": "",
        "public_order": 0,
    })


def create_manager_context():
    group = create_group(slug=unique_slug("group"))
    team = create_team(
        group=group,
        slug=unique_slug("team"),
        name="Platform Team",
    )

    service = create_service(team)
    route = create_route(team=team)

    route.service = service
    route.save()

    user = create_user(
        username=unique_slug("manager"),
        group=group,
        group_role=GROUP_USER_ADMIN_ROLE,
    )
    add_user_to_team(team, user, role="manager")

    return group, team, route, service, user, make_headers(user)


def iso(dt):
    return dt.replace(microsecond=0).isoformat() + "Z"


def reload_incident(incident):
    return AlertGroup.get_by_id(incident.id)


def assert_no_pending_group_notification(incident):
    incident = reload_incident(incident)

    assert incident.notification_pending is False
    assert incident.notification_due_at is None
    assert incident.notification_reason is None


def create_window_payload(scope, *, behavior="suppress_notifications"):
    now = utc_now()

    return {
        "name": "Payments deploy",
        "description": "Planned deployment",
        "behavior": behavior,
        "timezone": "UTC",
        "starts_at": iso(now - timedelta(minutes=5)),
        "ends_at": iso(now + timedelta(minutes=60)),
        "scopes": [
            scope,
        ],
    }


def test_create_maintenance_window_for_service(client, db):
    group, team, route, service, user, headers = create_manager_context()

    response = client.post(
        "/api/maintenance-windows",
        json=create_window_payload({
            "scope_type": "service",
            "service_id": service.id,
        }),
        headers=headers,
    )

    assert response.status_code == 201, response.get_json()

    payload = response.get_json()
    assert payload["name"] == "Payments deploy"
    assert payload["behavior"] == "suppress_notifications"
    assert len(payload["scopes"]) == 1
    assert payload["scopes"][0]["scope_type"] == "service"
    assert payload["scopes"][0]["service_id"] == service.id


def test_create_maintenance_window_requires_scope(client, db):
    group, team, route, service, user, headers = create_manager_context()

    payload = create_window_payload({
        "scope_type": "service",
        "service_id": service.id,
    })
    payload["scopes"] = []

    response = client.post(
        "/api/maintenance-windows",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


def test_create_maintenance_window_rejects_invalid_dates(client, db):
    group, team, route, service, user, headers = create_manager_context()
    now = utc_now()

    response = client.post(
        "/api/maintenance-windows",
        json={
            "name": "Bad window",
            "behavior": "suppress_notifications",
            "starts_at": iso(now + timedelta(hours=1)),
            "ends_at": iso(now),
            "scopes": [
                {
                    "scope_type": "service",
                    "service_id": service.id,
                }
            ],
        },
        headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


def test_list_maintenance_windows(client, db):
    group, team, route, service, user, headers = create_manager_context()

    create_response = client.post(
        "/api/maintenance-windows",
        json=create_window_payload({
            "scope_type": "service",
            "service_id": service.id,
        }),
        headers=headers,
    )

    assert create_response.status_code == 201, create_response.get_json()

    response = client.get(
        f"/api/maintenance-windows?service_id={service.id}",
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    assert len(payload) == 1
    assert payload[0]["name"] == "Payments deploy"


def test_update_maintenance_window(client, db):
    group, team, route, service, user, headers = create_manager_context()

    create_response = client.post(
        "/api/maintenance-windows",
        json=create_window_payload({
            "scope_type": "service",
            "service_id": service.id,
        }),
        headers=headers,
    )

    window_id = create_response.get_json()["id"]

    response = client.put(
        f"/api/maintenance-windows/{window_id}",
        json={
            "name": "Updated deploy",
            "behavior": "pause_escalation_only",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    assert payload["name"] == "Updated deploy"
    assert payload["behavior"] == "pause_escalation_only"


def test_cancel_maintenance_window(client, db):
    group, team, route, service, user, headers = create_manager_context()

    create_response = client.post(
        "/api/maintenance-windows",
        json=create_window_payload({
            "scope_type": "service",
            "service_id": service.id,
        }),
        headers=headers,
    )

    window_id = create_response.get_json()["id"]

    response = client.post(
        f"/api/maintenance-windows/{window_id}/cancel",
        json={"reason": "Deployment postponed"},
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()
    assert payload["status"] == "cancelled"
    assert payload["enabled"] is False
    assert payload["cancel_reason"] == "Deployment postponed"


def test_delete_maintenance_window(client, db):
    group, team, route, service, user, headers = create_manager_context()

    create_response = client.post(
        "/api/maintenance-windows",
        json=create_window_payload({
            "scope_type": "service",
            "service_id": service.id,
        }),
        headers=headers,
    )

    window_id = create_response.get_json()["id"]

    response = client.delete(
        f"/api/maintenance-windows/{window_id}",
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["deleted"] is True

    get_response = client.get(
        f"/api/maintenance-windows/{window_id}",
        headers=headers,
    )

    assert get_response.status_code == 404


def test_service_maintenance_suppresses_alert_notifications(client, db):
    group, team, route, service, user, headers = create_manager_context()

    create_response = client.post(
        "/api/maintenance-windows",
        json=create_window_payload({
            "scope_type": "service",
            "service_id": service.id,
        }, behavior="suppress_notifications"),
        headers=headers,
    )

    assert create_response.status_code == 201, create_response.get_json()

    alert_data = {
        "source": route.source,
        "external_id": unique_slug("external"),
        "dedup_key": unique_slug("dedup"),
        "title": "DiskFull",
        "message": "/var is 95% full",
        "severity": "critical",
        "status": "firing",
        "labels": {
            "alertname": "DiskFull",
            "service": service.slug,
        },
        "annotations": {},
        "payload": {},
        "team_slug": team.slug,
    }

    result = upsert_alert(alert_data)
    incident = result.group
    created = result.created_group
    incident = reload_incident(incident)

    assert created is True
    assert incident is not None
    assert incident.status == "firing"
    assert incident.maintenance_suppressed is True
    assert incident.maintenance_window_id == create_response.get_json()["id"]

    assert_no_pending_group_notification(incident)

    event = (
        AlertEvent
        .select()
        .where(
            AlertEvent.group == incident,
            AlertEvent.event_type == "maintenance_matched",
        )
        .get_or_none()
    )

    assert event is not None


def create_active_service_maintenance_window(
    *,
    team,
    service,
    behavior="create_maintenance_incident",
):
    now = utc_now()

    window = MaintenanceWindow.create(
        group=team.group,
        team=team,
        name=unique_slug("pytest-maintenance-service"),
        description="Active service maintenance regression test",
        starts_at=now - timedelta(minutes=5),
        ends_at=now + timedelta(hours=1),
        timezone="UTC",
        behavior=behavior,
        status="scheduled",
        enabled=True,
    )

    MaintenanceWindowScope.create(
        maintenance_window=window,
        scope_type="service",
        service=service,
    )

    return window


def test_service_maintenance_can_create_maintenance_incident(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_active_service_maintenance_window(
        team=team,
        service=service,
        behavior="create_maintenance_incident",
    )

    incident = create_test_alert_group(
        route=route,
        service=service,
        suffix=unique_slug("service-maintenance-incident"),
    )

    incident = reload_alert_group(incident)

    assert incident.status == "maintenance"
    assert incident.maintenance_window_id == window.id
    assert incident.maintenance_behavior == "create_maintenance_incident"
    assert incident.maintenance_suppressed is False

    assert_group_notification_not_queued(incident)

    alert = (
        Alert
        .select()
        .where(Alert.group == incident)
        .order_by(Alert.id.desc())
        .first()
    )

    assert alert is not None
    assert alert.status == "maintenance"
    assert alert.maintenance_window_id == window.id
    assert alert.maintenance_behavior == "create_maintenance_incident"
    assert alert.maintenance_suppressed is False


def test_pause_escalation_only_keeps_firing_but_removes_next_escalation(client, db):
    group, team, route, service, user, headers = create_manager_context()

    create_response = client.post(
        "/api/maintenance-windows",
        json=create_window_payload({
            "scope_type": "service",
            "service_id": service.id,
        }, behavior="pause_escalation_only"),
        headers=headers,
    )

    assert create_response.status_code == 201, create_response.get_json()

    alert_data = {
        "source": route.source,
        "external_id": unique_slug("external"),
        "dedup_key": unique_slug("dedup"),
        "title": "CPUHigh",
        "message": "CPU is high",
        "severity": "critical",
        "status": "firing",
        "labels": {
            "alertname": "CPUHigh",
            "service": service.slug,
        },
        "annotations": {},
        "payload": {},
        "team_slug": team.slug,
    }

    result = upsert_alert(alert_data)
    incident = result.group
    created = result.created_group
    incident = reload_incident(incident)

    assert created is True
    assert incident is not None
    assert incident.status == "firing"
    assert incident.maintenance_behavior == "pause_escalation_only"
    assert incident.next_escalation_at is None


def test_maintenance_window_status_uses_window_timezone(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_fixed_maintenance_window(
        team=team,
        service=service,
        starts_at=datetime(2026, 6, 7, 7, 52, 0),
        ends_at=datetime(2026, 6, 7, 11, 37, 0),
        timezone_name="Europe/Moscow",
    )

    before = datetime(2026, 6, 7, 4, 50, 0, tzinfo=timezone.utc)
    active = datetime(2026, 6, 7, 4, 54, 0, tzinfo=timezone.utc)
    after = datetime(2026, 6, 7, 8, 38, 0, tzinfo=timezone.utc)

    assert maintenance_repo.get_effective_window_status(window, now=before) == "scheduled"
    assert maintenance_repo.get_effective_window_status(window, now=active) == "active"
    assert maintenance_repo.get_effective_window_status(window, now=after) == "finished"


def test_find_active_maintenance_window_uses_window_timezone(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_fixed_maintenance_window(
        team=team,
        service=service,
        starts_at=datetime(2026, 6, 7, 7, 52, 0),
        ends_at=datetime(2026, 6, 7, 11, 37, 0),
        timezone_name="Europe/Moscow",
        behavior="create_maintenance_incident",
    )

    active = datetime(2026, 6, 7, 4, 54, 0, tzinfo=timezone.utc)

    matched = maintenance_repo.find_active_maintenance_window(
        team_id=team.id,
        service_id=service.id,
        now=active,
    )

    assert matched is not None
    assert matched.id == window.id


def test_find_active_maintenance_window_does_not_match_before_local_start(client, db):
    group, team, route, service, user, headers = create_manager_context()

    create_fixed_maintenance_window(
        team=team,
        service=service,
        starts_at=datetime(2026, 6, 7, 7, 52, 0),
        ends_at=datetime(2026, 6, 7, 11, 37, 0),
        timezone_name="Europe/Moscow",
    )

    before = datetime(2026, 6, 7, 4, 50, 0, tzinfo=timezone.utc)

    matched = maintenance_repo.find_active_maintenance_window(
        team_id=team.id,
        service_id=service.id,
        now=before,
    )

    assert matched is None


def test_maintenance_window_api_returns_effective_status(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_fixed_maintenance_window(
        team=team,
        service=service,
        starts_at=datetime(2026, 6, 7, 7, 52, 0),
        ends_at=datetime(2026, 6, 7, 11, 37, 0),
        timezone_name="Europe/Moscow",
        status="scheduled",
    )

    response = client.get(
        f"/api/maintenance-windows/{window.id}",
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()

    assert payload["stored_status"] == "scheduled"
    assert payload["timezone"] == "Europe/Moscow"


def test_recurring_maintenance_window_matches_active_occurrence(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_fixed_maintenance_window(
        team=team,
        service=service,
        starts_at=datetime(2026, 6, 1, 7, 0, 0),
        ends_at=datetime(2026, 6, 1, 8, 0, 0),
        timezone_name="Europe/Moscow",
        behavior="create_maintenance_incident",
        rrule="FREQ=DAILY;COUNT=3",
    )

    active = datetime(2026, 6, 2, 4, 30, 0, tzinfo=timezone.utc)

    assert maintenance_repo.get_effective_window_status(window, now=active) == "active"

    matched = maintenance_repo.find_active_maintenance_window(
        team_id=team.id,
        service_id=service.id,
        now=active,
    )

    assert matched is not None
    assert matched.id == window.id


def test_recurring_maintenance_window_does_not_match_between_occurrences(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_fixed_maintenance_window(
        team=team,
        service=service,
        starts_at=datetime(2026, 6, 1, 7, 0, 0),
        ends_at=datetime(2026, 6, 1, 8, 0, 0),
        timezone_name="Europe/Moscow",
        rrule="FREQ=DAILY;COUNT=3",
    )

    between_occurrences = datetime(2026, 6, 2, 6, 30, 0, tzinfo=timezone.utc)

    assert maintenance_repo.get_effective_window_status(window, now=between_occurrences) == "scheduled"

    matched = maintenance_repo.find_active_maintenance_window(
        team_id=team.id,
        service_id=service.id,
        now=between_occurrences,
    )

    assert matched is None


def test_recurring_maintenance_window_is_finished_after_last_occurrence(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_fixed_maintenance_window(
        team=team,
        service=service,
        starts_at=datetime(2026, 6, 1, 7, 0, 0),
        ends_at=datetime(2026, 6, 1, 8, 0, 0),
        timezone_name="Europe/Moscow",
        rrule="FREQ=DAILY;COUNT=2",
    )

    after_last_occurrence = datetime(2026, 6, 3, 6, 30, 0, tzinfo=timezone.utc)

    assert maintenance_repo.get_effective_window_status(window, now=after_last_occurrence) == "finished"

    matched = maintenance_repo.find_active_maintenance_window(
        team_id=team.id,
        service_id=service.id,
        now=after_last_occurrence,
    )

    assert matched is None


def test_create_maintenance_window_rejects_invalid_rrule(client, db):
    group, team, route, service, user, headers = create_manager_context()

    response = client.post(
        "/api/maintenance-windows",
        headers=headers,
        json={
            "name": unique_slug("pytest-maintenance"),
            "description": "Invalid recurrence",
            "behavior": "suppress_notifications",
            "timezone": "Europe/Moscow",
            "rrule": "BAD=VALUE",
            "starts_at": "2026-06-01T07:00:00",
            "ends_at": "2026-06-01T08:00:00",
            "enabled": True,
            "scopes": [
                {
                    "scope_type": "service",
                    "service_id": service.id,
                }
            ],
        },
    )

    data = response.get_json()

    assert response.status_code == 400
    assert data["error"] == "validation_error"
    assert data["message"] == "Request validation failed"
    assert any(
        detail.get("field") == "rrule"
        and "rrule" in detail.get("message", "")
        for detail in data["details"]
    )


def future_window_times(
    timezone_name="UTC",
    start_days=2,
    duration_hours=1,
):
    zone = ZoneInfo(timezone_name)

    starts_at = (
        datetime.now(zone)
        .replace(tzinfo=None, microsecond=0)
        + timedelta(days=start_days)
    )
    ends_at = starts_at + timedelta(hours=duration_hours)

    return starts_at.isoformat(), ends_at.isoformat()


def test_create_maintenance_window_writes_audit(client, db):
    group, team, route, service, user, headers = create_manager_context()
    starts_at, ends_at = future_window_times("Europe/Moscow")

    response = client.post(
        "/api/maintenance-windows",
        headers=headers,
        json={
            "name": unique_slug("pytest-maintenance"),
            "description": "Audit create",
            "behavior": "suppress_notifications",
            "timezone": "Europe/Moscow",
            "starts_at": starts_at,
            "ends_at": ends_at,
            "enabled": True,
            "scopes": [
                {
                    "scope_type": "service",
                    "service_id": service.id,
                }
            ],
        },
    )

    assert response.status_code == 201, response.get_json()

    payload = response.get_json()
    audit = latest_maintenance_audit(
        "maintenance_window.create",
        payload["id"],
    )

    assert audit is not None
    assert audit.user_id == user.id
    assert audit.group_id == group.id
    assert audit.team_id == team.id
    assert audit.data["name"] == payload["name"]
    assert audit.data["behavior"] == "suppress_notifications"
    assert audit.data["timezone"] == "Europe/Moscow"


def test_update_maintenance_window_writes_audit(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_fixed_maintenance_window(
        team=team,
        service=service,
        starts_at=datetime(2026, 6, 1, 7, 0, 0),
        ends_at=datetime(2026, 6, 1, 8, 0, 0),
        timezone_name="Europe/Moscow",
    )

    response = client.put(
        f"/api/maintenance-windows/{window.id}",
        headers=headers,
        json={
            "name": "Updated deploy",
            "description": "Audit update",
        },
    )

    assert response.status_code == 200, response.get_json()

    audit = latest_maintenance_audit(
        "maintenance_window.update",
        window.id,
    )

    assert audit is not None
    assert audit.user_id == user.id
    assert audit.group_id == group.id
    assert audit.team_id == team.id
    assert audit.data["name"] == "Updated deploy"
    assert audit.data["payload"]["description"] == "Audit update"


def test_cancel_maintenance_window_writes_audit(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_fixed_maintenance_window(
        team=team,
        service=service,
        starts_at=datetime(2026, 6, 1, 7, 0, 0),
        ends_at=datetime(2026, 6, 1, 8, 0, 0),
        timezone_name="Europe/Moscow",
    )

    response = client.post(
        f"/api/maintenance-windows/{window.id}/cancel",
        headers=headers,
        json={
            "reason": "Deployment postponed",
        },
    )

    assert response.status_code == 200, response.get_json()

    audit = latest_maintenance_audit(
        "maintenance_window.cancel",
        window.id,
    )

    assert audit is not None
    assert audit.user_id == user.id
    assert audit.group_id == group.id
    assert audit.team_id == team.id
    assert audit.data["status"] == "cancelled"
    assert audit.data["enabled"] is False
    assert audit.data["payload"]["reason"] == "Deployment postponed"


def test_delete_maintenance_window_writes_audit(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_fixed_maintenance_window(
        team=team,
        service=service,
        starts_at=datetime(2026, 6, 1, 7, 0, 0),
        ends_at=datetime(2026, 6, 1, 8, 0, 0),
        timezone_name="Europe/Moscow",
    )

    response = client.delete(
        f"/api/maintenance-windows/{window.id}",
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    audit = latest_maintenance_audit(
        "maintenance_window.delete",
        window.id,
    )

    assert audit is not None
    assert audit.user_id == user.id
    assert audit.group_id == group.id
    assert audit.team_id == team.id
    assert audit.data["enabled"] is False
    assert audit.data["payload"]["deleted"] is True


def test_recurring_maintenance_window_api_returns_next_occurrence(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_fixed_maintenance_window(
        team=team,
        service=service,
        starts_at=datetime(2026, 6, 1, 7, 0, 0),
        ends_at=datetime(2026, 6, 1, 8, 0, 0),
        timezone_name="Europe/Moscow",
        rrule="FREQ=DAILY;COUNT=3",
    )

    occurrence = maintenance_repo.get_effective_window_occurrence(
        window,
        now=datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc),
    )

    assert occurrence["status"] == "scheduled"
    assert occurrence["recurring"] is True
    assert occurrence["starts_at"] == datetime(2026, 6, 2, 7, 0, 0)
    assert occurrence["ends_at"] == datetime(2026, 6, 2, 8, 0, 0)


def test_recurring_maintenance_window_api_returns_active_occurrence(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_fixed_maintenance_window(
        team=team,
        service=service,
        starts_at=datetime(2026, 6, 1, 7, 0, 0),
        ends_at=datetime(2026, 6, 1, 8, 0, 0),
        timezone_name="Europe/Moscow",
        rrule="FREQ=DAILY;COUNT=3",
    )

    occurrence = maintenance_repo.get_effective_window_occurrence(
        window,
        now=datetime(2026, 6, 2, 4, 30, 0, tzinfo=timezone.utc),
    )

    assert occurrence["status"] == "active"
    assert occurrence["recurring"] is True
    assert occurrence["starts_at"] == datetime(2026, 6, 2, 7, 0, 0)
    assert occurrence["ends_at"] == datetime(2026, 6, 2, 8, 0, 0)



def create_active_team_maintenance_window(*, team, behavior="suppress_notifications"):
    now = utc_now()

    window = MaintenanceWindow.create(
        group=team.group,
        team=team,
        name=unique_slug("pytest-maintenance-team"),
        description="Active team maintenance regression test",
        starts_at=now - timedelta(minutes=5),
        ends_at=now + timedelta(hours=1),
        timezone="UTC",
        behavior=behavior,
        status="scheduled",
        enabled=True,
    )

    MaintenanceWindowScope.create(
        maintenance_window=window,
        scope_type="team",
        team=team,
    )

    return window


def test_team_maintenance_does_not_mark_existing_alert_groups(client, db):
    group, team, route, service, user, headers = create_manager_context()

    old_group = create_test_alert_group(
        route=route,
        service=service,
        suffix=unique_slug("old-alert"),
    )

    create_active_team_maintenance_window(
        team=team,
        behavior="create_maintenance_incident",
    )

    response = client.get(
        "/api/alerts",
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    items = response_items(response)
    serialized = next(item for item in items if item["id"] == old_group.id)

    assert serialized["active_maintenance"] is None


def test_team_maintenance_attaches_to_new_alert_groups(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_active_team_maintenance_window(
        team=team,
        behavior="create_maintenance_incident",
    )

    new_group = create_test_alert_group(
        route=route,
        service=service,
        suffix=unique_slug("new-alert"),
    )

    new_group = AlertGroup.get_by_id(new_group.id)

    assert new_group.maintenance_window_id == window.id
    assert new_group.maintenance_behavior == "create_maintenance_incident"

    response = client.get(
        "/api/alerts",
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    items = response_items(response)
    serialized = next(item for item in items if item["id"] == new_group.id)

    assert serialized["active_maintenance"] is not None
    assert serialized["active_maintenance"]["id"] == window.id
    assert serialized["active_maintenance"]["behavior"] == "create_maintenance_incident"
    assert serialized["active_maintenance"]["occurrence"] is not None


def test_service_serializer_returns_active_team_maintenance(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_active_team_maintenance_window(
        team=team,
        behavior="suppress_notifications",
    )

    response = client.get(
        "/api/services",
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    items = response_items(response)

    serialized = next(item for item in items if item["id"] == service.id)

    assert serialized["active_maintenance"] is not None
    assert serialized["active_maintenance"]["id"] == window.id
    assert serialized["active_maintenance"]["behavior"] == "suppress_notifications"
    assert serialized["active_maintenance"]["occurrence"] is not None


def test_route_serializer_returns_active_team_maintenance(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_active_team_maintenance_window(
        team=team,
        behavior="pause_escalation_only",
    )

    response = client.get(
        "/api/routes",
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    items = response_items(response)
    serialized = next(item for item in items if item["id"] == route.id)

    assert serialized["active_maintenance"] is not None
    assert serialized["active_maintenance"]["id"] == window.id
    assert serialized["active_maintenance"]["behavior"] == "pause_escalation_only"
    assert serialized["active_maintenance"]["occurrence"] is not None


def test_service_serializer_does_not_return_finished_maintenance(client, db):
    group, team, route, service, user, headers = create_manager_context()

    now = utc_now()

    window = MaintenanceWindow.create(
        group=team.group,
        team=team,
        name=unique_slug("pytest-maintenance-finished"),
        description="Finished maintenance regression test",
        starts_at=now - timedelta(hours=2),
        ends_at=now - timedelta(hours=1),
        timezone="UTC",
        behavior="suppress_notifications",
        status="scheduled",
        enabled=True,
    )

    MaintenanceWindowScope.create(
        maintenance_window=window,
        scope_type="team",
        team=team,
    )

    response = client.get(
        "/api/services",
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    items = response_items(response)

    serialized = next(item for item in items if item["id"] == service.id)

    assert serialized["active_maintenance"] is None


def test_route_serializer_does_not_return_cancelled_maintenance(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_active_team_maintenance_window(
        team=team,
        behavior="suppress_notifications",
    )

    window.status = "cancelled"
    window.enabled = False
    window.save()

    response = client.get(
        "/api/routes",
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()

    items = response_items(response)

    serialized = next(item for item in items if item["id"] == route.id)

    assert serialized["active_maintenance"] is None


def maintenance_window_payload_for_service(service, **overrides):
    starts_at, ends_at = future_window_times("Europe/Moscow")
    payload = {
        "name": unique_slug("pytest-maintenance"),
        "description": "RBAC regression test",
        "behavior": "suppress_notifications",
        "timezone": "UTC",
        "starts_at": starts_at,
        "ends_at": ends_at,
        "enabled": True,
        "scopes": [
            {
                "scope_type": "service",
                "service_id": service.id,
            }
        ],
    }

    payload.update(overrides)

    return payload


def test_team_manager_can_create_service_maintenance_window(client, db):
    group, team, route, service, user, headers = create_manager_context()

    response = client.post(
        "/api/maintenance-windows",
        headers=headers,
        json=maintenance_window_payload_for_service(service),
    )

    assert response.status_code == 201, response.get_json()

    payload = response.get_json()

    assert payload["team_id"] == team.id
    assert payload["group_id"] == group.id
    assert payload["scopes"][0]["scope_type"] == "service"
    assert payload["scopes"][0]["service_id"] == service.id


def test_team_manager_cannot_create_maintenance_for_other_team_service(client, db):
    group, team, route, service, user, headers = create_manager_context()
    other_group, other_team, other_route, other_service, other_user, other_headers = (
        create_manager_context()
    )

    payload = maintenance_window_payload_for_service(other_service)

    response = client.post(
        "/api/maintenance-windows",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 403, response.get_json()

    assert (
        MaintenanceWindow
        .select()
        .where(MaintenanceWindow.name == payload["name"])
        .count()
    ) == 0


def test_team_manager_cannot_update_maintenance_scope_to_other_team_service(client, db):
    group, team, route, service, user, headers = create_manager_context()
    other_group, other_team, other_route, other_service, other_user, other_headers = (
        create_manager_context()
    )

    window = create_fixed_maintenance_window(
        team=team,
        service=service,
        starts_at=datetime(2026, 6, 1, 7, 0, 0),
        ends_at=datetime(2026, 6, 1, 8, 0, 0),
        timezone_name="UTC",
    )

    response = client.put(
        f"/api/maintenance-windows/{window.id}",
        headers=headers,
        json={
            "scopes": [
                {
                    "scope_type": "service",
                    "service_id": other_service.id,
                }
            ],
        },
    )

    assert response.status_code == 403, response.get_json()

    scopes = list(MaintenanceWindowScope.select().where(
        MaintenanceWindowScope.maintenance_window == window
    ))

    assert len(scopes) == 1
    assert scopes[0].service_id == service.id


def test_team_manager_can_update_maintenance_metadata_without_scope_payload(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_fixed_maintenance_window(
        team=team,
        service=service,
        starts_at=datetime(2026, 6, 1, 7, 0, 0),
        ends_at=datetime(2026, 6, 1, 8, 0, 0),
        timezone_name="UTC",
    )

    response = client.put(
        f"/api/maintenance-windows/{window.id}",
        headers=headers,
        json={
            "name": "Updated maintenance metadata",
            "description": "Only metadata changed",
        },
    )

    assert response.status_code == 200, response.get_json()

    payload = response.get_json()

    assert payload["name"] == "Updated maintenance metadata"
    assert payload["description"] == "Only metadata changed"

    scopes = list(MaintenanceWindowScope.select().where(
        MaintenanceWindowScope.maintenance_window == window
    ))

    assert len(scopes) == 1
    assert scopes[0].service_id == service.id


def upsert_test_alert(*, route, service, suffix, status="firing"):
    dedup_key = f"pytest-maintenance-{suffix}"
    group_key = f"pytest-maintenance-{suffix}"

    route.matchers = {}
    route.save()

    return upsert_alert(
        {
            "status": status,
            "source": route.source,
            "forced_route_id": route.id,
            "team_id": route.team_id,
            "service_id": service.id,
            "external_id": dedup_key,
            "dedup_key": dedup_key,
            "group_key": group_key,
            "title": f"Maintenance behavior test {suffix}",
            "message": "Maintenance behavior regression test",
            "severity": "critical",
            "labels": {
                "alertname": f"MaintenanceBehavior{suffix}",
                "instance": suffix,
            },
            "annotations": {
                "summary": f"Maintenance behavior test {suffix}",
                "description": "Maintenance behavior regression test",
            },
            "payload": {
                "labels": {
                    "alertname": f"MaintenanceBehavior{suffix}",
                    "instance": suffix,
                },
                "annotations": {
                    "summary": f"Maintenance behavior test {suffix}",
                    "description": "Maintenance behavior regression test",
                },
            },
        }
    )


def reload_alert_group(group):
    return AlertGroup.get_by_id(group.id)


def assert_group_notification_not_queued(group):
    group = reload_alert_group(group)

    assert group.notification_pending is False
    assert group.notification_due_at is None
    assert group.notification_reason is None


def test_maintenance_suppress_notifications_creates_alert_without_notification(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_active_team_maintenance_window(
        team=team,
        behavior="suppress_notifications",
    )

    alert_group = create_test_alert_group(
        route=route,
        service=service,
        suffix=unique_slug("suppress-notifications"),
    )

    alert_group = reload_alert_group(alert_group)

    assert alert_group.maintenance_window_id == window.id
    assert alert_group.maintenance_behavior == "suppress_notifications"
    assert alert_group.maintenance_suppressed is True

    assert_group_notification_not_queued(alert_group)


def test_maintenance_create_maintenance_incident_attaches_window(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_active_team_maintenance_window(
        team=team,
        behavior="create_maintenance_incident",
    )

    alert_group = create_test_alert_group(
        route=route,
        service=service,
        suffix=unique_slug("maintenance-incident"),
    )

    alert_group = reload_alert_group(alert_group)

    assert alert_group.status == "maintenance"
    assert alert_group.maintenance_window_id == window.id
    assert alert_group.maintenance_behavior == "create_maintenance_incident"
    assert alert_group.maintenance_suppressed is False


def test_maintenance_pause_escalation_only_attaches_window_without_next_escalation(client, db):
    group, team, route, service, user, headers = create_manager_context()

    window = create_active_team_maintenance_window(
        team=team,
        behavior="pause_escalation_only",
    )

    alert_group = create_test_alert_group(
        route=route,
        service=service,
        suffix=unique_slug("pause-escalation"),
    )

    alert_group = reload_alert_group(alert_group)

    assert alert_group.maintenance_window_id == window.id
    assert alert_group.maintenance_behavior == "pause_escalation_only"
    assert alert_group.maintenance_suppressed is False
    assert alert_group.next_escalation_at is None


def test_maintenance_suppress_incident_does_not_create_alert_group(client, db):
    group, team, route, service, user, headers = create_manager_context()

    create_active_team_maintenance_window(
        team=team,
        behavior="suppress_incident",
    )

    suffix = unique_slug("suppress-incident")

    result = upsert_test_alert(
        route=route,
        service=service,
        suffix=suffix,
    )

    assert result.group is None

    assert (
        AlertGroup
        .select()
        .where(AlertGroup.group_key == f"pytest-maintenance-{suffix}")
        .count()
    ) == 0


def past_window_times(
    timezone_name="UTC",
    start_hours_ago=2,
    duration_hours=1,
):
    zone = ZoneInfo(timezone_name)

    starts_at = (
        datetime.now(zone)
        .replace(tzinfo=None, microsecond=0)
        - timedelta(hours=start_hours_ago)
    )
    ends_at = starts_at + timedelta(hours=duration_hours)

    return starts_at.isoformat(), ends_at.isoformat()


def test_create_maintenance_window_rejects_past_end_time(
    client,
    auth_headers,
):
    group = create_group()
    team = create_team(group=group)

    timezone_name = "UTC"
    starts_at, ends_at = past_window_times(timezone_name)

    windows_before = MaintenanceWindow.select().count()
    audit_before = AuditLog.select().count()

    payload = {
        "name": "Past maintenance window",
        "description": "Must be rejected by backend validation",
        "behavior": "suppress_notifications",
        "timezone": timezone_name,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "enabled": True,
        "scopes": [
            {
                "scope_type": "team",
                "team_id": team.id,
            },
        ],
    }

    response = client.post(
        "/api/maintenance-windows",
        json=payload,
        headers=auth_headers,
    )

    data = response.get_json()

    assert response.status_code == 400
    assert data["error"] == "validation_error"
    assert data["message"] == "Request validation failed"
    assert any(
        "future" in detail.get("message", "")
        for detail in data.get("details", [])
    )

    assert MaintenanceWindow.select().count() == windows_before
    assert AuditLog.select().count() == audit_before


def test_update_maintenance_window_allows_partial_ends_at_update(client, auth_headers):
    group = create_group()
    team = create_team(group=group)

    timezone_name = "UTC"
    starts_at, ends_at = future_window_times(timezone_name)
    window = create_window_for_team(
        group=group,
        team=team,
        timezone=timezone_name,
        starts_at=starts_at,
        ends_at=ends_at,
    )

    new_ends_at = (
        datetime.fromisoformat(ends_at) + timedelta(hours=1)
    ).isoformat()

    response = client.put(
        f"/api/maintenance-windows/{window.id}",
        json={"ends_at": new_ends_at},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    assert data["ends_at"] == new_ends_at
    assert data["starts_at"] == starts_at


def create_window_for_team(
    group,
    team,
    *,
    name="Payments deploy",
    timezone="UTC",
    starts_at=None,
    ends_at=None,
    behavior="suppress_notifications",
    enabled=True,
):
    if starts_at is None or ends_at is None:
        starts_at, ends_at = future_window_times(timezone)

    window = maintenance_repo.create_maintenance_window(
        group=group,
        team=team,
        name=name,
        description="Planned deployment",
        starts_at=starts_at,
        ends_at=ends_at,
        behavior=behavior,
        timezone=timezone,
        enabled=enabled,
    )

    maintenance_repo.replace_maintenance_window_scopes(
        window.id,
        [
            {
                "scope_type": "team",
                "team_id": team.id,
            },
        ],
    )

    return window


def test_update_maintenance_window_rejects_past_ends_at_in_existing_timezone(
    client,
    auth_headers,
):
    group = create_group()
    team = create_team(group=group)

    timezone_name = "Europe/Moscow"
    zone = ZoneInfo(timezone_name)

    local_now = datetime.now(zone).replace(tzinfo=None, microsecond=0)

    starts_at = (local_now - timedelta(minutes=10)).isoformat()
    ends_at = (local_now + timedelta(hours=1)).isoformat()

    window = create_window_for_team(
        group=group,
        team=team,
        timezone=timezone_name,
        starts_at=starts_at,
        ends_at=ends_at,
    )

    past_but_after_start = (local_now - timedelta(minutes=5)).isoformat()

    response = client.put(
        f"/api/maintenance-windows/{window.id}",
        json={"ends_at": past_but_after_start},
        headers=auth_headers,
    )

    data = response.get_json()

    assert response.status_code == 400
    assert data["error"] == "validation_error"
    assert data["message"] == "Invalid maintenance window update request."


def test_maintenance_window_serializes_wall_clock_times_without_utc_conversion(
    client,
    auth_headers,
):
    group = create_group()
    team = create_team(group=group)

    timezone_name = "Europe/Moscow"
    starts_at, ends_at = future_window_times(timezone_name)

    payload = {
        "name": "Moscow deploy",
        "behavior": "suppress_notifications",
        "timezone": timezone_name,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "enabled": True,
        "scopes": [
            {
                "scope_type": "team",
                "team_id": team.id,
            },
        ],
    }

    response = client.post(
        "/api/maintenance-windows",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 201, response.get_json()

    data = response.get_json()

    assert data["starts_at"] == starts_at
    assert data["ends_at"] == ends_at
    assert not data["starts_at"].endswith("Z")
    assert not data["ends_at"].endswith("Z")


def test_create_maintenance_window_rejects_service_scope_without_service_id(
    client,
    auth_headers,
):
    timezone_name = "UTC"
    starts_at, ends_at = future_window_times(timezone_name)

    payload = {
        "name": "Bad service scope",
        "behavior": "suppress_notifications",
        "timezone": timezone_name,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "enabled": True,
        "scopes": [{"scope_type": "service"}],
    }

    response = client.post(
        "/api/maintenance-windows",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 400
    data = response.get_json()
    assert data["error"] == "validation_error"
    assert any(
        "service_id" in detail.get("message", "")
        for detail in data.get("details", [])
    )


def test_datetime_helpers_keep_utc_and_wall_clock_semantics_separate():
    aware = as_utc_aware("2026-06-08T09:00:00+03:00")
    naive = as_naive_datetime("2026-06-08T09:00:00+03:00")

    assert aware.isoformat() == "2026-06-08T06:00:00+00:00"
    assert naive.isoformat() == "2026-06-08T09:00:00"
    assert aware.tzinfo is not None
    assert naive.tzinfo is None


def test_cancel_maintenance_window_allows_empty_body(client, auth_headers):
    group = create_group()
    team = create_team(group=group)

    timezone_name = "UTC"
    starts_at, ends_at = future_window_times(timezone_name)
    window = create_window_for_team(
        group=group,
        team=team,
        timezone=timezone_name,
        starts_at=starts_at,
        ends_at=ends_at,
    )

    response = client.post(
        f"/api/maintenance-windows/{window.id}/cancel",
        data=b"",
        headers=auth_headers,
        content_type="application/json",
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["status"] == "cancelled"



def test_maintenance_suppress_notifications_pauses_reminders_and_escalation(
    client,
    db,
    monkeypatch,
):
    from app.services.alerts import reminders

    group, team, route, service, user, headers = create_manager_context()

    create_active_team_maintenance_window(
        team=team,
        behavior="suppress_notifications",
    )

    alert_group = create_test_alert_group(
        route=route,
        service=service,
        suffix=unique_slug("paused-lifecycle"),
    )

    alert_group.last_notification_at = utc_now() - timedelta(hours=1)
    alert_group.reminder_count = 10
    alert_group.next_escalation_at = utc_now() - timedelta(minutes=1)
    alert_group.save()

    calls = {
        "escalation": 0,
        "notification": 0,
    }

    def fake_escalate(group):
        calls["escalation"] += 1
        return True

    def fake_notify(group, event_type):
        calls["notification"] += 1
        return 1

    monkeypatch.setattr(reminders, "maybe_escalate_alert", fake_escalate)
    monkeypatch.setattr(reminders, "notify_alert", fake_notify)

    assert reminders.send_unacked_reminders() == 0
    assert calls == {
        "escalation": 0,
        "notification": 0,
    }

    alert_group = reload_alert_group(alert_group)

    assert alert_group.notification_pending is False
    assert alert_group.next_escalation_at is None
    assert alert_group.reminder_count == 10


def test_due_group_notification_is_cancelled_during_maintenance(
    client,
    db,
    monkeypatch,
):
    from app.services.alerts import notification_queue

    group, team, route, service, user, headers = create_manager_context()

    create_active_team_maintenance_window(
        team=team,
        behavior="suppress_notifications",
    )

    alert_group = create_test_alert_group(
        route=route,
        service=service,
        suffix=unique_slug("due-notification"),
    )

    alert_group.notification_pending = True
    alert_group.notification_due_at = utc_now() - timedelta(seconds=1)
    alert_group.notification_reason = "notification"
    alert_group.save()

    sent = []

    monkeypatch.setattr(
        notification_queue,
        "notify_alert",
        lambda group, event_type: sent.append((group.id, event_type)) or 1,
    )

    result = notification_queue.process_due_alert_group_notifications()

    assert result["sent"] == 0
    assert result["skipped"] == 1
    assert sent == []

    assert_group_notification_not_queued(alert_group)


def test_expired_maintenance_resumes_with_one_scheduled_notification(
    client,
    db,
    monkeypatch,
):
    from app.services.alerts import reminders

    group, team, route, service, user, headers = create_manager_context()

    window = create_active_team_maintenance_window(
        team=team,
        behavior="suppress_notifications",
    )

    alert_group = create_test_alert_group(
        route=route,
        service=service,
        suffix=unique_slug("resume-lifecycle"),
    )

    alert_group.last_notification_at = utc_now() - timedelta(hours=1)
    alert_group.reminder_count = 4
    alert_group.next_escalation_at = None
    alert_group.save()

    window.ends_at = utc_now() - timedelta(seconds=1)
    window.save()

    monkeypatch.setattr(
        reminders,
        "notify_alert",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("notification must be queued, not sent by reminder job")
        ),
    )

    assert reminders.send_unacked_reminders() == 0
    assert reminders.send_unacked_reminders() == 0

    alert_group = reload_alert_group(alert_group)

    assert alert_group.maintenance_suppressed is False
    assert alert_group.notification_pending is True
    assert alert_group.notification_reason == "maintenance_ended"
    assert alert_group.notification_due_at is not None
    assert alert_group.reminder_count == 0

    resumed_event = (
        AlertEvent
        .select()
        .where(
            AlertEvent.group == alert_group.id,
            AlertEvent.event_type == "maintenance_notifications_resumed",
        )
        .order_by(AlertEvent.id.desc())
        .first()
    )

    assert resumed_event is not None
    assert (
        AlertEvent
        .select()
        .where(
            AlertEvent.group == alert_group.id,
            AlertEvent.event_type == "maintenance_notifications_resumed",
        )
        .count()
    ) == 1


def test_delayed_user_notification_is_skipped_during_maintenance(
    client,
    db,
):
    from app.modules.db.models import UserNotificationDelivery
    from app.services.notifications.rules import process_due_user_notifications

    group, team, route, service, user, headers = create_manager_context()

    create_active_team_maintenance_window(
        team=team,
        behavior="suppress_notifications",
    )

    alert_group = create_test_alert_group(
        route=route,
        service=service,
        suffix=unique_slug("delayed-user-notification"),
    )

    delivery = UserNotificationDelivery.create(
        group=alert_group.id,
        user=user.id,
        method="email",
        event_type="reminder",
        status="pending",
        scheduled_at=utc_now() - timedelta(seconds=1),
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    assert process_due_user_notifications() == 0

    delivery = UserNotificationDelivery.get_by_id(delivery.id)

    assert delivery.status == "skipped"
    assert delivery.last_error == "maintenance_suppressed"


def test_expired_maintenance_restarts_policy_escalation_from_resume_time(
    client,
    db,
):
    from app.services.alerts import reminders
    from tests.factories import (
        create_escalation_policy,
        create_escalation_policy_rule,
    )

    group, team, route, service, user, headers = create_manager_context()

    window = create_active_team_maintenance_window(
        team=team,
        behavior="suppress_notifications",
    )

    alert_group = create_test_alert_group(
        route=route,
        service=service,
        suffix=unique_slug("resume-policy"),
    )

    policy = create_escalation_policy(team, repeat_count=1)
    rule = create_escalation_policy_rule(
        policy,
        position=1,
        delay_seconds=120,
        target_type="user",
        user=user,
    )

    alert_group.escalation_policy = policy
    alert_group.escalation_rule = rule
    alert_group.next_escalation_at = None
    alert_group.save()

    window.ends_at = utc_now() - timedelta(seconds=1)
    window.save()

    before = utc_now()

    assert reminders.send_unacked_reminders() == 0

    after = utc_now()
    alert_group = reload_alert_group(alert_group)

    assert alert_group.next_escalation_at is not None
    assert before + timedelta(seconds=120) <= alert_group.next_escalation_at
    assert alert_group.next_escalation_at <= after + timedelta(seconds=120)
