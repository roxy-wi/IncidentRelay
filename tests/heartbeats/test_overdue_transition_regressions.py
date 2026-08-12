from datetime import timedelta
from types import SimpleNamespace

from app.modules.common import utc_now
from app.modules.db.models import HeartbeatInstance, HeartbeatPing
from app.services.heartbeats import service as heartbeat_service
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


def _fixture():
    group = create_group()
    user = create_user(group=group)
    team = create_team(group)
    add_user_to_team(team, user)
    service = create_service(team, name="Monitoring", slug="monitoring")
    route = create_route(team, source="heartbeat", service=service)
    return team, service, route


def _no_alert_group(*args, **kwargs):
    return SimpleNamespace(group=None)


def test_repeated_overdue_without_alert_group_does_not_duplicate_event(db, monkeypatch):
    team, service, route = _fixture()
    now = utc_now().replace(microsecond=0)
    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("overdue-no-group-token"),
        status="ok",
        last_seen_at=now - timedelta(minutes=10),
        next_expected_at=now - timedelta(minutes=5),
        expected_interval_seconds=60,
        grace_period_seconds=60,
    )
    monkeypatch.setattr(heartbeat_service, "upsert_alert", _no_alert_group)

    heartbeat_service.mark_heartbeat_overdue(heartbeat, now=now)
    heartbeat = heartbeat.__class__.get_by_id(heartbeat.id)
    first_overdue_since = heartbeat.overdue_since
    first_last_overdue_at = heartbeat.last_overdue_at

    heartbeat_service.mark_heartbeat_overdue(
        heartbeat,
        now=now + timedelta(minutes=1),
    )
    heartbeat = heartbeat.__class__.get_by_id(heartbeat.id)

    events = list(
        HeartbeatPing.select().where(
            (HeartbeatPing.heartbeat == heartbeat.id)
            & (HeartbeatPing.event_type == "overdue")
        )
    )
    assert len(events) == 1
    assert events[0].status_before == "ok"
    assert events[0].status_after == "overdue"
    assert heartbeat.overdue_since == first_overdue_since
    assert heartbeat.last_overdue_at == first_last_overdue_at
    assert heartbeat.current_alert_group_id is None


def test_repeated_instance_overdue_without_alert_group_does_not_duplicate_event(db, monkeypatch):
    team, service, route = _fixture()
    now = utc_now().replace(microsecond=0)
    heartbeat = create_heartbeat(
        team,
        route,
        service=service,
        token_hash=hash_token("instance-overdue-no-group-token"),
        instance_tracking_enabled=True,
        instance_key="instance",
        expected_instances_mode="auto",
    )
    instance = HeartbeatInstance.create(
        heartbeat=heartbeat,
        instance_key="worker-1.example.com",
        status="ok",
        enabled=True,
        auto_discovered=True,
        last_seen_at=now - timedelta(minutes=10),
        next_expected_at=now - timedelta(minutes=5),
    )
    monkeypatch.setattr(heartbeat_service, "upsert_alert", _no_alert_group)

    heartbeat_service.mark_heartbeat_instance_overdue(instance, now=now)
    instance = HeartbeatInstance.get_by_id(instance.id)
    first_overdue_since = instance.overdue_since
    first_last_overdue_at = instance.last_overdue_at

    heartbeat_service.mark_heartbeat_instance_overdue(
        instance,
        now=now + timedelta(minutes=1),
    )
    instance = HeartbeatInstance.get_by_id(instance.id)

    events = list(
        HeartbeatPing.select().where(
            (HeartbeatPing.heartbeat == heartbeat.id)
            & (HeartbeatPing.event_type == "instance_overdue")
            & (HeartbeatPing.instance_key == instance.instance_key)
        )
    )
    assert len(events) == 1
    assert events[0].status_before == "ok"
    assert events[0].status_after == "overdue"
    assert instance.overdue_since == first_overdue_since
    assert instance.last_overdue_at == first_last_overdue_at
    assert instance.current_alert_group_id is None
