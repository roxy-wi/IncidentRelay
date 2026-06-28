from app.modules.db.models import ServiceEvent
from app.services.service_catalog.timeline import (
    build_next_cursor,
    list_service_events,
    serialize_service_event,
)
from tests.factories import create_group, create_service, create_team, create_user


def test_serialize_service_event_includes_actor_display_name():
    group = create_group()
    team = create_team(group)
    user = create_user()
    user.username = "alice"
    user.display_name = "Alice Doe"
    user.email = "alice@example.com"
    user.save()
    service = create_service(team)

    event = ServiceEvent.create(
        service=service,
        group=group,
        team=team,
        category="configuration",
        event_type="service.updated",
        title="Service updated",
        actor_type="user",
        actor_user=user,
        payload={"field": "name"},
    )

    payload = serialize_service_event(event)

    assert payload["actor"] == {
        "type": "user",
        "user_id": user.id,
        "display_name": "Alice Doe",
        "email": "alice@example.com",
        "label": None,
    }


def test_list_service_events_filters_category_event_type_and_cursor():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    first = ServiceEvent.create(
        service=service,
        group=group,
        team=team,
        category="configuration",
        event_type="service.created",
        title="Service created",
    )
    second = ServiceEvent.create(
        service=service,
        group=group,
        team=team,
        category="configuration",
        event_type="service.updated",
        title="Service updated",
    )
    ServiceEvent.create(
        service=service,
        group=group,
        team=team,
        category="status",
        event_type="service.status_changed",
        title="Service status changed",
    )

    configuration_events = list_service_events(service.id, category="configuration")
    assert [event.id for event in configuration_events] == [second.id, first.id]

    updated_events = list_service_events(service.id, event_type="service.updated")
    assert [event.id for event in updated_events] == [second.id]

    cursor_events = list_service_events(
        service.id,
        limit=10,
        before=second.occurred_at,
        before_id=second.id,
    )
    assert [event.id for event in cursor_events] == [first.id]


def test_build_next_cursor_returns_last_event_position_only_when_page_is_full():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    first = ServiceEvent.create(
        service=service,
        group=group,
        team=team,
        category="configuration",
        event_type="service.created",
        title="Service created",
    )
    second = ServiceEvent.create(
        service=service,
        group=group,
        team=team,
        category="configuration",
        event_type="service.updated",
        title="Service updated",
    )

    assert build_next_cursor([second, first], 3) is None

    cursor = build_next_cursor([second, first], 2)
    assert cursor["before_id"] == first.id
    assert cursor["before"].endswith("Z")
