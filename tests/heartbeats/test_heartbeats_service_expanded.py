from datetime import datetime, timedelta

from app.modules.db.models import AlertGroup, HeartbeatPing
from app.services.heartbeats.service import process_overdue_heartbeats, receive_heartbeat_ping
from app.services.integrations.auth import hash_token
from tests.factories import create_group, create_heartbeat, create_route, create_service, create_team, create_user, add_user_to_team
from app.modules.common import utc_now


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
        last_seen_at=utc_now() - timedelta(minutes=10),
        next_expected_at=utc_now() - timedelta(minutes=5),
        expected_interval_seconds=60,
        grace_period_seconds=60,
    )

    result = process_overdue_heartbeats(now=utc_now())

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
        last_seen_at=utc_now() - timedelta(minutes=10),
        next_expected_at=utc_now() - timedelta(minutes=5),
        expected_interval_seconds=60,
        grace_period_seconds=60,
    )

    process_overdue_heartbeats(now=utc_now())
    heartbeat = heartbeat.__class__.get_by_id(heartbeat.id)
    group_id = heartbeat.current_alert_group_id

    recovered, error = receive_heartbeat_ping(
        "hb-token",
        payload={"status": "completed", "payload": {"rows_loaded": 10}},
        now=utc_now(),
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


def test_auto_discovered_instance_ping_creates_instance_state(db):
    from app.modules.db.models import HeartbeatInstance

    _, team, service, route = _fixture()
    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("fleet-token"),
        instance_tracking_enabled=True,
        instance_key="instance",
        expected_instances_mode="auto",
        auto_discovery_ttl_days=30,
    )

    item, error = receive_heartbeat_ping(
        "fleet-token",
        payload={"status": "completed", "instance": "server-1.example.com"},
        now=utc_now(),
    )

    assert error is None
    assert item.status == "ok"

    instance = HeartbeatInstance.get(
        (HeartbeatInstance.heartbeat == heartbeat.id)
        & (HeartbeatInstance.instance_key == "server-1.example.com")
    )
    assert instance.status == "ok"
    assert instance.auto_discovered is True
    assert instance.last_seen_at is not None


def test_missing_auto_discovered_instance_pages_individually(db):
    from app.modules.db.models import HeartbeatInstance

    _, team, service, route = _fixture()
    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("fleet-token"),
        instance_tracking_enabled=True,
        instance_key="instance",
        expected_instances_mode="auto",
    )
    now = utc_now()
    instance = HeartbeatInstance.create(
        heartbeat=heartbeat,
        instance_key="server-1.example.com",
        status="ok",
        enabled=True,
        auto_discovered=True,
        last_seen_at=now - timedelta(minutes=10),
        next_expected_at=now - timedelta(minutes=5),
    )

    result = process_overdue_heartbeats(now=now)

    assert result["instances_processed"] >= 1
    assert result["instances_overdue"] == 1

    instance = HeartbeatInstance.get_by_id(instance.id)
    heartbeat = heartbeat.__class__.get_by_id(heartbeat.id)
    assert instance.status == "overdue"
    assert instance.current_alert_group_id
    assert heartbeat.status == "overdue"

    group = AlertGroup.get_by_id(instance.current_alert_group_id)
    assert group.group_key.endswith(":instance:server-1.example.com")
    assert group.status == "firing"


def test_static_instance_rejects_unknown_producer(db):
    _, team, service, route = _fixture()
    create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("static-token"),
        instance_tracking_enabled=True,
        expected_instances_mode="static",
        metadata={"expected_instances": ["server-1.example.com"]},
    )

    _, error = receive_heartbeat_ping(
        "static-token",
        payload={"status": "completed", "instance": "server-2.example.com"},
        now=utc_now(),
    )

    assert error is not None
    assert error["error"] == "heartbeat_instance_not_expected"



def test_interval_heartbeat_is_not_overdue_before_deadline(db):
    _, team, service, route = _fixture()
    now = utc_now()

    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("not-due-token"),
        status="ok",
        last_seen_at=now - timedelta(seconds=30),
        next_expected_at=now + timedelta(seconds=30),
        expected_interval_seconds=60,
        grace_period_seconds=60,
    )

    result = process_overdue_heartbeats(now=now)

    heartbeat = heartbeat.__class__.get_by_id(heartbeat.id)
    assert result["overdue"] == 0
    assert heartbeat.status != "overdue"
    assert heartbeat.current_alert_group_id is None


def test_overdue_check_does_not_duplicate_existing_alert_group(db):
    _, team, service, route = _fixture()
    now = utc_now()

    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("duplicate-token"),
        last_seen_at=now - timedelta(minutes=10),
        next_expected_at=now - timedelta(minutes=5),
        expected_interval_seconds=60,
        grace_period_seconds=60,
    )

    process_overdue_heartbeats(now=now)
    heartbeat = heartbeat.__class__.get_by_id(heartbeat.id)
    group_id = heartbeat.current_alert_group_id
    group = AlertGroup.get_by_id(group_id)

    process_overdue_heartbeats(now=now + timedelta(minutes=1))
    heartbeat = heartbeat.__class__.get_by_id(heartbeat.id)

    assert heartbeat.current_alert_group_id == group_id
    assert (
        AlertGroup
        .select()
        .where(AlertGroup.group_key == group.group_key)
        .count()
    ) == 1


def test_ping_recovery_does_not_resolve_alert_when_auto_resolve_is_disabled(db):
    _, team, service, route = _fixture()
    now = utc_now()

    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("manual-resolve-token"),
        auto_resolve=False,
        last_seen_at=now - timedelta(minutes=10),
        next_expected_at=now - timedelta(minutes=5),
        expected_interval_seconds=60,
        grace_period_seconds=60,
    )

    process_overdue_heartbeats(now=now)
    heartbeat = heartbeat.__class__.get_by_id(heartbeat.id)
    group_id = heartbeat.current_alert_group_id

    recovered, error = receive_heartbeat_ping(
        "manual-resolve-token",
        payload={"status": "completed"},
        now=now + timedelta(minutes=1),
    )

    assert error is None
    assert recovered.status == "ok"

    group = AlertGroup.get_by_id(group_id)
    assert group.status == "firing"


def test_ping_payload_persists_run_id_message_and_payload(db):
    _, team, service, route = _fixture()
    now = utc_now()

    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("payload-token"),
        expected_interval_seconds=60,
        grace_period_seconds=60,
    )

    item, error = receive_heartbeat_ping(
        "payload-token",
        payload={
            "status": "completed",
            "run_id": "mysql-backup-2026-07-09",
            "message": "Backup completed",
            "payload": {
                "rows_loaded": 10,
                "duration_seconds": 42,
            },
        },
        now=now,
    )

    assert error is None
    assert item.id == heartbeat.id

    ping = (
        HeartbeatPing
        .select()
        .where(HeartbeatPing.heartbeat == heartbeat.id)
        .order_by(HeartbeatPing.id.desc())
        .get()
    )
    assert ping.event_type == "ping"
    assert ping.message == "Heartbeat ping received"
    assert ping.payload["run_id"] == "mysql-backup-2026-07-09"
    assert ping.payload["message"] == "Backup completed"
    assert ping.payload["payload"]["rows_loaded"] == 10
    assert ping.payload["payload"]["duration_seconds"] == 42


def test_scheduled_daily_heartbeat_is_overdue_when_today_completion_is_missing(db):
    _, team, service, route = _fixture()
    now = datetime(2026, 7, 9, 9, 0)

    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("scheduled-missed-token"),
        mode="scheduled",
        schedule_kind="daily",
        schedule_time="03:00",
        timezone="UTC",
        grace_period_seconds=300,
        last_seen_at=datetime(2026, 7, 7, 12, 1),
        next_expected_at=datetime(2026, 7, 9, 3, 0),
    )

    result = process_overdue_heartbeats(now=now)

    heartbeat = heartbeat.__class__.get_by_id(heartbeat.id)
    assert result["overdue"] == 1
    assert heartbeat.status == "overdue"
    assert heartbeat.current_alert_group_id


def test_scheduled_daily_heartbeat_is_ok_when_today_completion_was_received(db):
    _, team, service, route = _fixture()
    now = datetime(2026, 7, 9, 9, 0)

    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("scheduled-ok-token"),
        mode="scheduled",
        schedule_kind="daily",
        schedule_time="03:00",
        timezone="UTC",
        grace_period_seconds=300,
        last_seen_at=datetime(2026, 7, 9, 3, 1),
        next_expected_at=datetime(2026, 7, 10, 3, 0),
    )

    result = process_overdue_heartbeats(now=now)

    heartbeat = heartbeat.__class__.get_by_id(heartbeat.id)
    assert result["overdue"] == 0
    assert heartbeat.status != "overdue"
    assert heartbeat.current_alert_group_id is None


def test_scheduled_daily_heartbeat_is_not_overdue_before_grace_deadline(db):
    _, team, service, route = _fixture()
    now = datetime(2026, 7, 9, 3, 3)

    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("scheduled-grace-token"),
        mode="scheduled",
        schedule_kind="daily",
        schedule_time="03:00",
        timezone="UTC",
        grace_period_seconds=300,
        last_seen_at=datetime(2026, 7, 8, 3, 1),
        next_expected_at=datetime(2026, 7, 9, 3, 0),
    )

    result = process_overdue_heartbeats(now=now)

    heartbeat = heartbeat.__class__.get_by_id(heartbeat.id)
    assert result["overdue"] == 0
    assert heartbeat.status != "overdue"


def test_scheduled_weekly_heartbeat_is_overdue_when_expected_weekday_was_missed(db):
    _, team, service, route = _fixture()
    now = datetime(2026, 7, 6, 9, 0)  # Monday.

    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("weekly-missed-token"),
        mode="scheduled",
        schedule_kind="weekly",
        schedule_weekday=0,
        schedule_time="03:00",
        timezone="UTC",
        grace_period_seconds=300,
        last_seen_at=datetime(2026, 6, 29, 3, 1),
        next_expected_at=datetime(2026, 7, 6, 3, 0),
    )

    result = process_overdue_heartbeats(now=now)

    heartbeat = heartbeat.__class__.get_by_id(heartbeat.id)
    assert result["overdue"] == 1
    assert heartbeat.status == "overdue"


def test_scheduled_monthly_heartbeat_is_overdue_when_expected_monthday_was_missed(db):
    _, team, service, route = _fixture()
    now = datetime(2026, 7, 9, 9, 0)

    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("monthly-missed-token"),
        mode="scheduled",
        schedule_kind="monthly",
        schedule_monthday=9,
        schedule_time="03:00",
        timezone="UTC",
        grace_period_seconds=300,
        last_seen_at=datetime(2026, 6, 9, 3, 1),
        next_expected_at=datetime(2026, 7, 9, 3, 0),
    )

    result = process_overdue_heartbeats(now=now)

    heartbeat = heartbeat.__class__.get_by_id(heartbeat.id)
    assert result["overdue"] == 1
    assert heartbeat.status == "overdue"


def test_scheduled_heartbeat_uses_configured_timezone_for_deadline(db):
    _, team, service, route = _fixture()
    now = datetime(2026, 7, 9, 0, 10)  # 03:10 Europe/Moscow.

    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("timezone-missed-token"),
        mode="scheduled",
        schedule_kind="daily",
        schedule_time="03:00",
        timezone="Europe/Moscow",
        grace_period_seconds=300,
        last_seen_at=datetime(2026, 7, 8, 23, 0),
        next_expected_at=datetime(2026, 7, 9, 0, 0),
    )

    result = process_overdue_heartbeats(now=now)

    heartbeat = heartbeat.__class__.get_by_id(heartbeat.id)
    assert result["overdue"] == 1
    assert heartbeat.status == "overdue"


def test_auto_discovered_instance_repeated_ping_updates_existing_state(db):
    from app.modules.db.models import HeartbeatInstance

    _, team, service, route = _fixture()
    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("fleet-repeat-token"),
        instance_tracking_enabled=True,
        instance_key="instance",
        expected_instances_mode="auto",
    )

    first_seen = utc_now()
    second_seen = first_seen + timedelta(minutes=1)

    _, error = receive_heartbeat_ping(
        "fleet-repeat-token",
        payload={"status": "completed", "instance": "server-1.example.com"},
        now=first_seen,
    )
    assert error is None

    _, error = receive_heartbeat_ping(
        "fleet-repeat-token",
        payload={
            "status": "completed",
            "instance": "server-1.example.com",
            "run_id": "run-2",
        },
        now=second_seen,
    )
    assert error is None

    instances = list(
        HeartbeatInstance
        .select()
        .where(HeartbeatInstance.heartbeat == heartbeat.id)
    )
    assert len(instances) == 1
    assert instances[0].instance_key == "server-1.example.com"
    assert instances[0].last_seen_at.replace(microsecond=0) == second_seen.replace(microsecond=0)


def test_instance_tracking_uses_custom_instance_key_field(db):
    from app.modules.db.models import HeartbeatInstance

    _, team, service, route = _fixture()
    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("custom-instance-key-token"),
        instance_tracking_enabled=True,
        instance_key="host",
        expected_instances_mode="auto",
    )

    _, error = receive_heartbeat_ping(
        "custom-instance-key-token",
        payload={"status": "completed", "host": "db-1.example.com"},
        now=utc_now(),
    )

    assert error is None
    instance = HeartbeatInstance.get(
        (HeartbeatInstance.heartbeat == heartbeat.id)
        & (HeartbeatInstance.instance_key == "db-1.example.com")
    )
    assert instance.status == "ok"


def test_instance_tracking_requires_instance_identifier(db):
    _, team, service, route = _fixture()
    create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("missing-instance-token"),
        instance_tracking_enabled=True,
        instance_key="instance",
        expected_instances_mode="auto",
    )

    _, error = receive_heartbeat_ping(
        "missing-instance-token",
        payload={"status": "completed"},
        now=utc_now(),
    )

    assert error is not None
    assert error["error"] == "heartbeat_instance_required"


def test_static_expected_instance_without_prior_ping_pages_individually(db):
    from app.modules.db.models import HeartbeatInstance

    _, team, service, route = _fixture()
    now = utc_now()

    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("static-missing-token"),
        instance_tracking_enabled=True,
        instance_key="instance",
        expected_instances_mode="static",
        metadata={"expected_instances": ["server-1.example.com"]},
        last_seen_at=now,
        next_expected_at=now - timedelta(minutes=5),
        expected_interval_seconds=60,
        grace_period_seconds=60,
    )

    HeartbeatInstance.create(
        heartbeat=heartbeat,
        instance_key="server-1.example.com",
        status="new",
        enabled=True,
        auto_discovered=False,
        last_seen_at=None,
        next_expected_at=now - timedelta(minutes=5),
    )

    result = process_overdue_heartbeats(now=now)

    assert result["instances_overdue"] == 1

    instance = HeartbeatInstance.get(
        (HeartbeatInstance.heartbeat == heartbeat.id)
        & (HeartbeatInstance.instance_key == "server-1.example.com")
    )
    assert instance.status == "overdue"
    assert instance.current_alert_group_id

    group = AlertGroup.get_by_id(instance.current_alert_group_id)
    assert group.status == "firing"
    assert group.source == "heartbeat"
    assert group.group_key.endswith(":instance:server-1.example.com")


def test_one_healthy_static_instance_does_not_hide_missing_static_instance(db):
    from app.modules.db.models import HeartbeatInstance

    _, team, service, route = _fixture()
    now = utc_now()

    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("static-two-instances-token"),
        instance_tracking_enabled=True,
        instance_key="instance",
        expected_instances_mode="static",
        metadata={"expected_instances": ["server-1.example.com", "server-2.example.com"]},
        next_expected_at=now - timedelta(minutes=5),
        expected_interval_seconds=60,
        grace_period_seconds=60,
    )

    HeartbeatInstance.create(
        heartbeat=heartbeat,
        instance_key="server-1.example.com",
        status="new",
        enabled=True,
        auto_discovered=False,
        last_seen_at=None,
        next_expected_at=now + timedelta(hours=1),
    )

    HeartbeatInstance.create(
        heartbeat=heartbeat,
        instance_key="server-2.example.com",
        status="new",
        enabled=True,
        auto_discovered=False,
        last_seen_at=None,
        next_expected_at=now - timedelta(minutes=5),
    )

    item, error = receive_heartbeat_ping(
        "static-two-instances-token",
        payload={"status": "completed", "instance": "server-1.example.com"},
        now=now,
    )

    assert error is None
    assert item.status == "ok"

    result = process_overdue_heartbeats(now=now)

    assert result["instances_overdue"] == 1

    server_1 = HeartbeatInstance.get(
        (HeartbeatInstance.heartbeat == heartbeat.id)
        & (HeartbeatInstance.instance_key == "server-1.example.com")
    )
    server_2 = HeartbeatInstance.get(
        (HeartbeatInstance.heartbeat == heartbeat.id)
        & (HeartbeatInstance.instance_key == "server-2.example.com")
    )

    assert server_1.status == "ok"
    assert server_2.status == "overdue"
    assert server_2.current_alert_group_id


def test_ping_recovers_only_overdue_instance_alert(db):
    from app.modules.db.models import HeartbeatInstance

    _, team, service, route = _fixture()
    now = utc_now()

    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("instance-recovery-token"),
        instance_tracking_enabled=True,
        instance_key="instance",
        expected_instances_mode="auto",
    )

    instance = HeartbeatInstance.create(
        heartbeat=heartbeat,
        instance_key="server-1.example.com",
        status="ok",
        enabled=True,
        auto_discovered=True,
        last_seen_at=now - timedelta(minutes=10),
        next_expected_at=now - timedelta(minutes=5),
    )

    process_overdue_heartbeats(now=now)
    instance = HeartbeatInstance.get_by_id(instance.id)
    group_id = instance.current_alert_group_id

    recovered, error = receive_heartbeat_ping(
        "instance-recovery-token",
        payload={"status": "completed", "instance": "server-1.example.com"},
        now=now + timedelta(minutes=1),
    )

    assert error is None
    assert recovered.status == "ok"

    instance = HeartbeatInstance.get_by_id(instance.id)
    assert instance.status == "ok"
    assert instance.current_alert_group_id is None

    group = AlertGroup.get_by_id(group_id)
    assert group.status == "resolved"


def test_paused_heartbeat_does_not_create_overdue_alert(db):
    _, team, service, route = _fixture()
    now = utc_now()

    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("paused-token"),
        status="paused",
        enabled=True,
        last_seen_at=now - timedelta(minutes=10),
        next_expected_at=now - timedelta(minutes=5),
        expected_interval_seconds=60,
        grace_period_seconds=60,
    )

    result = process_overdue_heartbeats(now=now)

    heartbeat = heartbeat.__class__.get_by_id(heartbeat.id)
    assert result["overdue"] == 0
    assert heartbeat.status == "paused"
    assert heartbeat.current_alert_group_id is None


def test_disabled_heartbeat_does_not_create_overdue_alert(db):
    _, team, service, route = _fixture()
    now = utc_now()

    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("disabled-token"),
        enabled=False,
        last_seen_at=now - timedelta(minutes=10),
        next_expected_at=now - timedelta(minutes=5),
        expected_interval_seconds=60,
        grace_period_seconds=60,
    )

    result = process_overdue_heartbeats(now=now)

    heartbeat = heartbeat.__class__.get_by_id(heartbeat.id)
    assert result["overdue"] == 0
    assert heartbeat.current_alert_group_id is None


def test_invalid_heartbeat_token_is_rejected(db):
    _, team, service, route = _fixture()
    create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("valid-token"),
        expected_interval_seconds=60,
        grace_period_seconds=60,
    )

    _, error = receive_heartbeat_ping(
        "wrong-token",
        payload={"status": "completed"},
        now=utc_now(),
    )

    assert error is not None
    assert error["error"] == "heartbeat_not_found"


def test_ping_recovery_sends_resolved_notification_without_double_update(
    monkeypatch,
    db,
):
    _, team, service, route = _fixture()
    now = utc_now()

    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("resolved-notification-token"),
        last_seen_at=now - timedelta(minutes=10),
        next_expected_at=now - timedelta(minutes=5),
        expected_interval_seconds=60,
        grace_period_seconds=60,
    )

    process_overdue_heartbeats(now=now)
    heartbeat = heartbeat.__class__.get_by_id(heartbeat.id)
    group = AlertGroup.get_by_id(heartbeat.current_alert_group_id)

    group.last_notification_at = now - timedelta(minutes=1)
    group.notification_pending = True
    group.notification_due_at = now + timedelta(minutes=1)
    group.notification_reason = "update"
    group.save()

    deliveries = []
    message_updates = []

    monkeypatch.setattr(
        "app.services.heartbeats.service.notify_alert",
        lambda current_group, event_type="notification": deliveries.append(
            (current_group.id, event_type)
        )
        or 1,
    )
    monkeypatch.setattr(
        "app.services.alerts.actions.update_alert_messages",
        lambda current_group, event_type: message_updates.append(
            (current_group.id, event_type)
        )
        or 1,
    )

    recovered, error = receive_heartbeat_ping(
        "resolved-notification-token",
        payload={"status": "completed"},
        now=now + timedelta(minutes=1),
    )

    assert error is None
    assert recovered.status == "ok"
    assert deliveries == [(group.id, "resolved")]
    assert message_updates == []

    group = AlertGroup.get_by_id(group.id)
    assert group.status == "resolved"
    assert group.notification_pending is False
    assert group.notification_due_at is None
    assert group.notification_reason is None


def test_ping_recovery_does_not_send_resolved_without_initial_notification(
    monkeypatch,
    db,
):
    _, team, service, route = _fixture()
    now = utc_now()

    create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("no-resolved-notification-token"),
        last_seen_at=now - timedelta(minutes=10),
        next_expected_at=now - timedelta(minutes=5),
        expected_interval_seconds=60,
        grace_period_seconds=60,
    )

    process_overdue_heartbeats(now=now)

    deliveries = []
    monkeypatch.setattr(
        "app.services.heartbeats.service.notify_alert",
        lambda current_group, event_type="notification": deliveries.append(
            (current_group.id, event_type)
        )
        or 1,
    )

    recovered, error = receive_heartbeat_ping(
        "no-resolved-notification-token",
        payload={"status": "completed"},
        now=now + timedelta(minutes=1),
    )

    assert error is None
    assert recovered.status == "ok"
    assert deliveries == []


def test_instance_ping_recovery_sends_resolved_notification(
    monkeypatch,
    db,
):
    from app.modules.db.models import HeartbeatInstance

    _, team, service, route = _fixture()
    now = utc_now()

    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("instance-resolved-notification-token"),
        instance_tracking_enabled=True,
        instance_key="instance",
        expected_instances_mode="auto",
    )

    instance = HeartbeatInstance.create(
        heartbeat=heartbeat,
        instance_key="server-1.example.com",
        status="ok",
        enabled=True,
        auto_discovered=True,
        last_seen_at=now - timedelta(minutes=10),
        next_expected_at=now - timedelta(minutes=5),
    )

    process_overdue_heartbeats(now=now)
    instance = HeartbeatInstance.get_by_id(instance.id)
    group = AlertGroup.get_by_id(instance.current_alert_group_id)
    group.last_notification_at = now - timedelta(minutes=1)
    group.save(only=[AlertGroup.last_notification_at])

    deliveries = []
    monkeypatch.setattr(
        "app.services.heartbeats.service.notify_alert",
        lambda current_group, event_type="notification": deliveries.append(
            (current_group.id, event_type)
        )
        or 1,
    )

    recovered, error = receive_heartbeat_ping(
        "instance-resolved-notification-token",
        payload={"status": "completed", "instance": "server-1.example.com"},
        now=now + timedelta(minutes=1),
    )

    assert error is None
    assert recovered.status == "ok"
    assert deliveries == [(group.id, "resolved")]
