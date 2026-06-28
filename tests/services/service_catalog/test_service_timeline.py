from datetime import datetime, timedelta

from app.services.service_catalog.timeline import build_next_cursor, list_service_events, publish_service_event, serialize_service_event
from tests.factories import create_group, create_service, create_team


def test_publish_service_event_uses_service_scope_snapshot():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    event = publish_service_event(service, category="configuration", event_type="service.created", title="Service created")

    assert event.service_id == service.id
    assert event.group_id == group.id
    assert event.team_id == team.id


def test_publish_service_event_is_idempotent_with_dedup_key():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    first = publish_service_event(service, category="change", event_type="change.deployment_succeeded", title="Deployment completed", source="github_actions", dedup_key="run-123")
    second = publish_service_event(service, category="change", event_type="change.deployment_succeeded", title="Duplicate deployment", source="github_actions", dedup_key="run-123")

    assert first.id == second.id
    assert second.title == "Deployment completed"


def test_list_service_events_orders_newest_first():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    now = datetime.utcnow()

    older = publish_service_event(service, category="configuration", event_type="service.created", title="Older", occurred_at=now - timedelta(minutes=5))
    newer = publish_service_event(service, category="status", event_type="service.status_changed", title="Newer", occurred_at=now)

    events = list_service_events(service.id)

    assert [event.id for event in events] == [newer.id, older.id]


def test_list_service_events_filters_category():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    publish_service_event(service, category="configuration", event_type="service.created", title="Created")
    status_event = publish_service_event(service, category="status", event_type="service.status_changed", title="Status changed")

    events = list_service_events(service.id, category="status")

    assert [event.id for event in events] == [status_event.id]


def test_list_service_events_uses_stable_cursor():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    occurred_at = datetime.utcnow()

    first = publish_service_event(service, category="configuration", event_type="service.updated", title="First", occurred_at=occurred_at)
    second = publish_service_event(service, category="configuration", event_type="service.updated", title="Second", occurred_at=occurred_at)

    events = list_service_events(service.id, limit=1)
    next_events = list_service_events(service.id, limit=1, before=events[-1].occurred_at, before_id=events[-1].id)

    assert events[0].id == second.id
    assert next_events[0].id == first.id


def test_serialize_service_event_returns_public_contract():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    event = publish_service_event(service, category="status", event_type="service.status_changed", title="Status changed", status="degraded", payload={"old_status": "operational", "new_status": "degraded"})
    serialized = serialize_service_event(event)

    assert serialized["uid"] == str(event.uid)
    assert serialized["category"] == "status"
    assert serialized["status"] == "degraded"
    assert serialized["payload"]["old_status"] == "operational"


def test_build_next_cursor_returns_last_event_position():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    event = publish_service_event(service, category="configuration", event_type="service.created", title="Created")
    cursor = build_next_cursor([event], 1)

    assert cursor["before_id"] == event.id
    assert cursor["before"].endswith("Z")


def test_build_next_cursor_returns_none_for_last_page():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    event = publish_service_event(service, category="configuration", event_type="service.created", title="Created")

    assert build_next_cursor([event], 50) is None
