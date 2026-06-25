import pytest
from pydantic import ValidationError

from app.api.schemas.routes import RouteCreateSchema
from app.modules.db import routes_repo
from app.services.serializers import serialize_route
from tests.factories import create_group, create_route, create_team


def _route_payload(team, **overrides):
    payload = {
        "team_id": team.id,
        "name": "Test route",
        "source": "webhook",
        "rotation_id": None,
        "channel_ids": [],
        "notification_channel_mode": "route_only",
        "matchers": {},
        "group_by": [],
        "enabled": True,
        "escalation_mode": "rotation",
        "escalation_policy_id": None,
        "service_id": None,
        "integration_config": {},
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "mode",
    [
        "route_only",
        "service_policy",
        "service_policy_plus_route",
    ],
)
def test_route_schema_accepts_notification_channel_mode(mode):
    group = create_group()
    team = create_team(group)

    payload = RouteCreateSchema(
        **_route_payload(team, notification_channel_mode=mode)
    )

    assert payload.notification_channel_mode == mode


def test_route_schema_defaults_to_route_only():
    group = create_group()
    team = create_team(group)
    payload = _route_payload(team)
    payload.pop("notification_channel_mode")

    validated = RouteCreateSchema(**payload)

    assert validated.notification_channel_mode == "route_only"


def test_route_schema_rejects_unknown_notification_channel_mode():
    group = create_group()
    team = create_team(group)

    with pytest.raises(ValidationError):
        RouteCreateSchema(
            **_route_payload(
                team,
                notification_channel_mode="service_only",
            )
        )


def test_route_repository_updates_notification_channel_mode():
    group = create_group()
    team = create_team(group)
    route = create_route(team)

    updated = routes_repo.update_route(
        route.id,
        {"notification_channel_mode": "service_policy"},
    )

    assert updated.notification_channel_mode == "service_policy"


def test_serialize_route_includes_notification_channel_mode():
    group = create_group()
    team = create_team(group)
    route = create_route(
        team,
        notification_channel_mode="service_policy_plus_route",
    )

    result = serialize_route(route)

    assert result["notification_channel_mode"] == (
        "service_policy_plus_route"
    )
