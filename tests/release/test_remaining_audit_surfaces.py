"""Cross-module audit regression tests for operator configuration mutations."""

from app.modules.db import tokens_repo
from app.modules.db.models import AuditLog, BusinessService
from app.services.integrations.auth import hash_token
from tests.factories import (
    attach_channel,
    create_channel,
    create_group,
    create_heartbeat,
    create_route,
    create_team,
    unique,
)


def _audit(action, *, object_id):
    return AuditLog.get(AuditLog.action == action, AuditLog.object_id == object_id)


def test_auth_password_change_has_audit_without_password_data(client, admin_headers, admin_user, db):
    response = client.post(
        "/api/auth/change-password",
        headers=admin_headers,
        json={"old_password": "password-123", "new_password": "new-test-password-123"},
    )
    assert response.status_code == 200, response.get_json()

    record = _audit("profile.password.change", object_id=admin_user.id)
    assert record.user_id == admin_user.id
    assert record.api_token_id is None
    assert record.data["transport"] == "api"
    assert "new-test-password-123" not in str(record.data)


def test_business_service_manual_status_is_audited_in_group(client, admin_headers, db):
    group = create_group()
    item = BusinessService.create(
        group=group, slug=unique("service"), name="Payments", enabled=True,
    )
    response = client.post(
        f"/api/business-services/{item.id}/manual-status",
        headers=admin_headers,
        json={"status": "degraded", "message": "Testing status override"},
    )
    assert response.status_code == 200, response.get_json()

    record = _audit("business_service.manual_status.set", object_id=item.id)
    assert record.group_id == group.id
    assert record.data["transport"] == "api"
    assert record.data["status"] == "degraded"
    assert "Testing status override" not in str(record.data)


def test_heartbeat_token_rotation_audit_never_stores_secret(client, admin_headers, db):
    team = create_team(create_group())
    route = create_route(team, source="heartbeat")
    heartbeat = create_heartbeat(team, route)

    response = client.post(
        f"/api/heartbeats/{heartbeat.id}/regenerate-token",
        headers=admin_headers,
    )
    assert response.status_code == 200, response.get_json()

    record = _audit("heartbeat.token.rotate", object_id=heartbeat.id)
    assert record.team_id == team.id
    assert record.group_id == team.group_id
    assert record.data["transport"] == "api"
    assert "token" not in record.data
    assert response.get_json().get("token") not in str(record.data)


def test_calendar_feed_api_token_audit_preserves_actor_and_token(client, admin_user, db):
    team = create_team(create_group())
    raw = unique("feed-audit-token")
    token = tokens_repo.create_token(
        name="feed-audit", token_prefix=raw[:12], token_hash=hash_token(raw),
        scopes=["calendar:write"], user=admin_user.id,
    )
    headers = {"Authorization": f"Bearer {raw}"}
    created = client.post("/api/calendar/feeds", headers=headers, json={"team_id": team.id})
    assert created.status_code == 201, created.get_json()
    feed_id = created.get_json()["id"]

    record = _audit("calendar_feed.create", object_id=feed_id)
    assert record.api_token_id == token.id
    assert record.user_id == admin_user.id
    assert record.team_id == team.id
    assert record.data["transport"] == "api"
    assert created.get_json()["token"] not in str(record.data)

    rotated = client.post(f"/api/calendar/feeds/{feed_id}/token", headers=headers)
    assert rotated.status_code == 200, rotated.get_json()
    rotation_record = _audit("calendar_feed.token.rotate", object_id=feed_id)
    assert rotation_record.api_token_id == token.id
    assert rotation_record.data["transport"] == "api"
    assert rotated.get_json()["token"] not in str(rotation_record.data)


def test_notification_rule_crud_has_one_audit_per_mutation(client, admin_headers, db):
    created = client.post(
        "/api/profile/notification-rules",
        headers=admin_headers,
        json={"method": "browser_push", "event_types": ["notification"]},
    )
    assert created.status_code == 201, created.get_json()
    rule_id = created.get_json()["id"]

    updated = client.put(
        f"/api/profile/notification-rules/{rule_id}",
        headers=admin_headers, json={"delay_seconds": 30},
    )
    assert updated.status_code == 200, updated.get_json()
    deleted = client.delete(
        f"/api/profile/notification-rules/{rule_id}", headers=admin_headers,
    )
    assert deleted.status_code == 200, deleted.get_json()

    actions = [row.action for row in AuditLog.select().where(
        AuditLog.object_type == "user_notification_rule",
        AuditLog.object_id == rule_id,
    ).order_by(AuditLog.id)]
    assert actions == [
        "profile.notification_rule.create",
        "profile.notification_rule.update",
        "profile.notification_rule.delete",
    ]


def test_route_channel_unlink_is_audited_only_if_link_existed(client, admin_headers, db):
    group = create_group()
    team = create_team(group)
    route = create_route(team)
    channel = create_channel(group, team)
    attach_channel(route, channel)

    url = f"/api/routes/{route.id}/channels/{channel.id}"
    assert client.delete(url, headers=admin_headers).status_code == 200
    assert client.delete(url, headers=admin_headers).status_code == 200

    records = list(AuditLog.select().where(
        AuditLog.action == "route.channel.remove", AuditLog.object_id == route.id,
    ))
    assert len(records) == 1
    assert records[0].team_id == team.id


def test_rejected_password_change_has_no_success_audit(client, admin_headers, admin_user, db):
    response = client.post(
        "/api/auth/change-password", headers=admin_headers,
        json={"old_password": "incorrect", "new_password": "new-test-password-123"},
    )
    assert response.status_code == 400
    assert not AuditLog.select().where(
        AuditLog.action == "profile.password.change",
        AuditLog.object_id == admin_user.id,
    ).exists()


def test_manual_impact_snapshot_audit_is_team_scoped(client, admin_headers, db):
    team = create_team(create_group())
    created = client.post(
        "/api/services/impact/snapshots", headers=admin_headers,
        json={"team_id": team.id, "include_operational": True},
    )
    assert created.status_code == 201, created.get_json()
    snapshot_id = created.get_json()["id"]
    record = _audit("service_impact.snapshot.create", object_id=snapshot_id)
    assert record.team_id == team.id
    assert record.data["team_ids"] == [team.id]
    assert record.data["transport"] == "api"


def test_request_audit_preserves_domain_source_separately_from_transport(app, db):
    from app.services.audit import write_audit
    with app.test_request_context("/api/routes", method="POST"):
        write_audit(
            "route.audit_fixture", object_type="route", object_id=101,
            data={"source": "alertmanager"},
        )
    record = _audit("route.audit_fixture", object_id=101)
    assert record.data["source"] == "alertmanager"
    assert record.data["transport"] == "api"
