from datetime import datetime, timedelta

from app.modules.db.models import AlertGroup, HeartbeatPing
from app.services.heartbeats.service import process_overdue_heartbeats, receive_heartbeat_ping
from app.services.integrations.auth import hash_token
from tests.factories import create_group, create_heartbeat, create_route, create_service, create_team, create_user, add_user_to_team


def _fixture():
    group = create_group()
    user = create_user(group=group)
    team = create_team(group)
    add_user_to_team(team, user)
    service = create_service(team, name="Monitoring", slug="monitoring")
    route = create_route(team, source="heartbeat", service=service)
    return group, team, service, route


def test_overdue_heartbeat_creates_regular_alert_group(db):
    _, team, service, route = _fixture()
    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("hb-token"),
        last_seen_at=datetime.utcnow() - timedelta(minutes=10),
        next_expected_at=datetime.utcnow() - timedelta(minutes=5),
        expected_interval_seconds=60,
        grace_period_seconds=60,
    )

    result = process_overdue_heartbeats(now=datetime.utcnow())

    assert result["processed"] >= 1
    assert result["overdue"] == 1

    heartbeat = heartbeat.__class__.get_by_id(heartbeat.id)
    assert heartbeat.status == "overdue"
    assert heartbeat.current_alert_group_id

    group = AlertGroup.get_by_id(heartbeat.current_alert_group_id)
    assert group.source == "heartbeat"
    assert group.team_id == team.id
    assert group.route_id == route.id
    assert group.service_id == service.id
    assert group.status == "firing"
    assert group.priority_slug == "p2"
    assert "Heartbeat overdue" in group.title


def test_ping_recovers_overdue_heartbeat_and_resolves_alert(db):
    _, team, service, route = _fixture()
    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("hb-token"),
        last_seen_at=datetime.utcnow() - timedelta(minutes=10),
        next_expected_at=datetime.utcnow() - timedelta(minutes=5),
        expected_interval_seconds=60,
        grace_period_seconds=60,
    )

    process_overdue_heartbeats(now=datetime.utcnow())
    heartbeat = heartbeat.__class__.get_by_id(heartbeat.id)
    group_id = heartbeat.current_alert_group_id

    recovered, error = receive_heartbeat_ping(
        "hb-token",
        payload={"status": "completed", "payload": {"rows_loaded": 10}},
        now=datetime.utcnow(),
    )

    assert error is None
    assert recovered.status == "ok"
    assert recovered.current_alert_group_id is None
    assert recovered.last_seen_at is not None

    group = AlertGroup.get_by_id(group_id)
    assert group.status == "resolved"

    events = list(HeartbeatPing.select().where(HeartbeatPing.heartbeat == recovered.id))
    assert {event.event_type for event in events} >= {"overdue", "recovery"}


def test_ping_endpoint_accepts_get_without_auth(client, db):
    _, team, service, route = _fixture()
    create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("public-token"),
        expected_interval_seconds=60,
        grace_period_seconds=60,
    )

    response = client.get("/api/heartbeats/ping/public-token")

    assert response.status_code == 200
    assert response.get_json()["ok"] is True


def test_non_heartbeat_route_is_rejected(client, db, admin_headers):
    _, team, service, _ = _fixture()
    route = create_route(team, source="alertmanager", service=service)

    response = client.post(
        "/api/heartbeats",
        headers=admin_headers,
        json={
            "team_id": team.id,
            "route_id": route.id,
            "service_id": service.id,
            "name": "Prometheus Watchdog",
            "slug": "prometheus-watchdog",
            "mode": "interval",
            "expected_interval_seconds": 60,
            "grace_period_seconds": 60,
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "route_source_mismatch"
