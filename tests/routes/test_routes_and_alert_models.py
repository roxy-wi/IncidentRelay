from app.modules.db import rotations_repo
from app.modules.db.models import Alert, AlertRoute, AlertRouteChannel
from tests.factories import (
    add_user_to_team,
    attach_channel,
    create_alert,
    create_channel,
    create_group,
    create_route,
    create_rotation,
    create_team,
    create_user,
    unique
)


def test_rotation_layer_members_are_ordered_by_position(db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    first = create_user("alice", group)
    second = create_user("bob", group)

    add_user_to_team(team, first)
    add_user_to_team(team, second)
    rotation = create_rotation(team, users=[first, second])
    layer = rotations_repo.get_or_create_default_layer(rotation.id)

    members = rotations_repo.list_rotation_layer_members(layer.id)

    assert [member.user.username for member in members] == ["alice", "bob"]


def test_route_can_have_notification_channel(db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    channel = create_channel(group, team)
    route = create_route(team)

    attach_channel(route, channel)

    assert AlertRouteChannel.select().where(AlertRouteChannel.route == route).count() == 1


def test_alert_is_persisted_with_labels_and_payload(db):
    group = create_group(slug="infra")
    team = create_team(group, slug="sre")
    route = create_route(team)

    alert = create_alert(route)

    fetched = Alert.get_by_id(alert.id)

    assert fetched.status == "firing"
    assert fetched.severity == "critical"
    assert fetched.labels["alertname"] == "DiskFull"
    assert fetched.payload["source"] == "test"
    assert fetched.team == team
    assert fetched.route == route


def test_update_route_rejects_unknown_rotation_id(client, admin_headers, db):
    group = create_group(slug=unique("group"))
    team = create_team(group=group, slug=unique("team"))
    route = create_route(team=team)

    response = client.put(
        f"/api/routes/{route.id}",
        json={
            "team_id": team.id,
            "name": route.name,
            "source": route.source,
            "rotation_id": 999999,
            "escalation_policy_id": None,
            "channel_ids": [],
            "matchers": {},
            "group_by": [],
            "enabled": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "rotation_not_found"


def test_update_route_rejects_rotation_from_another_team(client, admin_headers, db):
    group = create_group(slug=unique("group"))
    team = create_team(group=group, slug=unique("team"))
    other_team = create_team(group=group, slug=unique("other-team"))

    route = create_route(team=team)
    rotation = create_rotation(team=other_team)

    response = client.put(
        f"/api/routes/{route.id}",
        json={
            "team_id": team.id,
            "name": route.name,
            "source": route.source,
            "rotation_id": rotation.id,
            "escalation_policy_id": None,
            "channel_ids": [],
            "matchers": {},
            "group_by": [],
            "enabled": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "rotation_team_mismatch"


def test_create_route_with_duplicate_name_returns_conflict(client, admin_headers, db):
    group = create_group(slug=unique("group"))
    team = create_team(group=group, slug=unique("team"))

    create_route(team=team, name="Primary route")

    response = client.post(
        "/api/routes",
        json={
            "team_id": team.id,
            "name": "Primary route",
            "source": "alertmanager",
            "rotation_id": None,
            "escalation_policy_id": None,
            "channel_ids": [],
            "matchers": {},
            "group_by": [],
            "enabled": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 409
    assert response.get_json()["error"] == "conflict"


def sentry_route_payload(team, name="Sentry route", integration_config=None):
    return {
        "team_id": team.id,
        "name": name,
        "source": "sentry",
        "rotation_id": None,
        "escalation_policy_id": None,
        "channel_ids": [],
        "matchers": {},
        "group_by": ["project_slug", "issue_id"],
        "integration_config": integration_config or {},
        "enabled": True,
    }


def test_create_sentry_route_returns_webhook_path_without_secret(
    client,
    admin_headers,
    db,
):
    group = create_group(slug=unique("group"))
    team = create_team(group=group, slug=unique("team"))

    response = client.post(
        "/api/routes",
        json=sentry_route_payload(team),
        headers=admin_headers,
    )

    assert response.status_code == 201

    payload = response.get_json()

    assert payload["source"] == "sentry"
    assert payload["intake_token"]
    assert payload["integration_config"]["sentry"]["has_webhook_secret"] is False
    assert (
        payload["integration_config"]["sentry"]["webhook_path"]
        == f"/api/integrations/sentry/{payload['id']}"
    )

    route = AlertRoute.get_by_id(payload["id"])
    assert route.integration_config == {"sentry": {}}


def test_create_sentry_route_stores_secret_but_does_not_serialize_it(
    client,
    admin_headers,
    db,
):
    group = create_group(slug=unique("group"))
    team = create_team(group=group, slug=unique("team"))

    response = client.post(
        "/api/routes",
        json=sentry_route_payload(
            team,
            integration_config={
                "sentry": {
                    "webhook_secret": "sentry-secret",
                },
            },
        ),
        headers=admin_headers,
    )

    assert response.status_code == 201

    payload = response.get_json()

    assert payload["integration_config"]["sentry"]["has_webhook_secret"] is True
    assert "webhook_secret" not in payload["integration_config"]["sentry"]

    route = AlertRoute.get_by_id(payload["id"])
    assert route.integration_config["sentry"]["webhook_secret"] == "sentry-secret"


def test_update_sentry_route_empty_secret_preserves_existing_secret(
    client,
    admin_headers,
    db,
):
    group = create_group(slug=unique("group"))
    team = create_team(group=group, slug=unique("team"))

    route = create_route(
        team=team,
        source="sentry",
        integration_config={
            "sentry": {
                "webhook_secret": "old-secret",
            },
        },
    )

    response = client.put(
        f"/api/routes/{route.id}",
        json=sentry_route_payload(
            team,
            name=route.name,
            integration_config={
                "sentry": {},
            },
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()

    assert payload["integration_config"]["sentry"]["has_webhook_secret"] is True
    assert "webhook_secret" not in payload["integration_config"]["sentry"]

    route = AlertRoute.get_by_id(route.id)
    assert route.integration_config["sentry"]["webhook_secret"] == "old-secret"


def test_update_sentry_route_replaces_secret_when_new_secret_is_provided(
    client,
    admin_headers,
    db,
):
    group = create_group(slug=unique("group"))
    team = create_team(group=group, slug=unique("team"))

    route = create_route(
        team=team,
        source="sentry",
        integration_config={
            "sentry": {
                "webhook_secret": "old-secret",
            },
        },
    )

    response = client.put(
        f"/api/routes/{route.id}",
        json=sentry_route_payload(
            team,
            name=route.name,
            integration_config={
                "sentry": {
                    "webhook_secret": "new-secret",
                },
            },
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200

    route = AlertRoute.get_by_id(route.id)
    assert route.integration_config["sentry"]["webhook_secret"] == "new-secret"


def test_update_non_sentry_route_clears_integration_config(
    client,
    admin_headers,
    db,
):
    group = create_group(slug=unique("group"))
    team = create_team(group=group, slug=unique("team"))

    route = create_route(
        team=team,
        source="sentry",
        integration_config={
            "sentry": {
                "webhook_secret": "sentry-secret",
            },
        },
    )

    response = client.put(
        f"/api/routes/{route.id}",
        json={
            "team_id": team.id,
            "name": route.name,
            "source": "webhook",
            "rotation_id": None,
            "escalation_policy_id": None,
            "channel_ids": [],
            "matchers": {},
            "group_by": [],
            "integration_config": {
                "sentry": {
                    "webhook_secret": "must-not-survive",
                },
            },
            "enabled": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()
    assert payload["source"] == "webhook"
    assert payload["integration_config"] == {}

    route = AlertRoute.get_by_id(route.id)
    assert route.integration_config == {}
