from datetime import datetime, timedelta

from app.modules.db.models import AlertGroup, HeartbeatInstance
from app.services.heartbeats.service import process_overdue_heartbeats, receive_heartbeat_ping
from app.services.integrations.auth import hash_token
from tests.factories import (
    add_user_to_team,
    create_group,
    create_heartbeat,
    create_route,
    create_service,
    create_team,
    create_user,
)
from app.modules.common import utc_now


def _fixture():
    group = create_group()
    user = create_user(group=group)
    team = create_team(group)
    add_user_to_team(team, user)
    service = create_service(team, name="Monitoring", slug="monitoring")
    route = create_route(team, source="heartbeat", service=service)
    return group, team, service, route


def _create_instance(heartbeat, instance_key, *, now, status="ok", enabled=True):
    return HeartbeatInstance.create(
        heartbeat=heartbeat,
        instance_key=instance_key,
        status=status,
        enabled=enabled,
        auto_discovered=True,
        last_seen_at=now - timedelta(minutes=10),
        next_expected_at=now - timedelta(minutes=5),
    )


def test_overdue_instance_check_does_not_duplicate_existing_alert_group(db):
    _, team, service, route = _fixture()
    now = utc_now()
    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("instance-duplicate-token"),
        instance_tracking_enabled=True,
        instance_key="instance",
        expected_instances_mode="auto",
    )
    instance = _create_instance(heartbeat, "server-1.example.com", now=now)

    process_overdue_heartbeats(now=now)

    instance = HeartbeatInstance.get_by_id(instance.id)
    first_group_id = instance.current_alert_group_id
    first_group = AlertGroup.get_by_id(first_group_id)

    process_overdue_heartbeats(now=now + timedelta(minutes=1))

    instance = HeartbeatInstance.get_by_id(instance.id)
    assert instance.current_alert_group_id == first_group_id
    assert (
        AlertGroup.select()
        .where(AlertGroup.group_key == first_group.group_key)
        .count()
    ) == 1


def test_disabled_instance_does_not_create_overdue_alert(db):
    _, team, service, route = _fixture()
    now = utc_now()
    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("disabled-instance-token"),
        instance_tracking_enabled=True,
        instance_key="instance",
        expected_instances_mode="auto",
    )
    instance = _create_instance(
        heartbeat, "server-1.example.com", now=now, enabled=False
    )

    result = process_overdue_heartbeats(now=now)

    instance = HeartbeatInstance.get_by_id(instance.id)
    assert result["instances_overdue"] == 0
    assert instance.status == "ok"
    assert instance.current_alert_group_id is None


def test_recovering_one_instance_does_not_hide_second_overdue_instance(db):
    _, team, service, route = _fixture()
    now = utc_now()
    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("partial-instance-recovery-token"),
        instance_tracking_enabled=True,
        instance_key="instance",
        expected_instances_mode="static",
        metadata={
            "expected_instances": [
                "server-1.example.com",
                "server-2.example.com",
            ]
        },
    )
    first = HeartbeatInstance.create(
        heartbeat=heartbeat,
        instance_key="server-1.example.com",
        status="ok",
        enabled=True,
        auto_discovered=False,
        last_seen_at=now - timedelta(minutes=10),
        next_expected_at=now - timedelta(minutes=5),
    )
    second = HeartbeatInstance.create(
        heartbeat=heartbeat,
        instance_key="server-2.example.com",
        status="ok",
        enabled=True,
        auto_discovered=False,
        last_seen_at=now - timedelta(minutes=10),
        next_expected_at=now - timedelta(minutes=5),
    )

    result = process_overdue_heartbeats(now=now)
    assert result["instances_overdue"] == 2

    first = HeartbeatInstance.get_by_id(first.id)
    second = HeartbeatInstance.get_by_id(second.id)
    first_group_id = first.current_alert_group_id
    second_group_id = second.current_alert_group_id

    item, error = receive_heartbeat_ping(
        "partial-instance-recovery-token",
        payload={"status": "completed", "instance": "server-1.example.com"},
        now=now + timedelta(minutes=1),
    )

    assert error is None

    item = item.__class__.get_by_id(item.id)
    first = HeartbeatInstance.get_by_id(first.id)
    second = HeartbeatInstance.get_by_id(second.id)
    first_group = AlertGroup.get_by_id(first_group_id)
    second_group = AlertGroup.get_by_id(second_group_id)

    assert item.status == "overdue"
    assert first.status == "ok"
    assert first.current_alert_group_id is None
    assert first_group.status == "resolved"
    assert second.status == "overdue"
    assert second.current_alert_group_id == second_group_id
    assert second_group.status == "firing"
