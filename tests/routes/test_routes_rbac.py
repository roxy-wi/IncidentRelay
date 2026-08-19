from app.login import create_access_token
from tests.factories import (
    create_group,
    create_team,
    create_route,
    create_user,
    unique,
)
from app.api.schemas.roles import GROUP_USER_ADMIN_ROLE


def make_headers(user):
    token, _ = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def test_group_admin_can_update_route(client, db):
    group = create_group(slug=unique("group"))
    team = create_team(group=group, slug=unique("team"), name="Network Team")
    route = create_route(team=team)

    user = create_user(
        username=unique("group-admin"),
        group=group,
        group_role=GROUP_USER_ADMIN_ROLE,
    )

    response = client.put(
        f"/api/routes/{route.id}",
        json={
            "team_id": team.id,
            "name": "Updated route",
            "source": route.source,
            "rotation_id": route.rotation_id,
            "escalation_policy_id": route.escalation_policy_id,
            "channel_ids": [
                link.channel_id
                for link in route.route_channels
            ],
            "matchers": route.matchers or {},
            "group_by": route.group_by or [],
            "enabled": True,
            "service_id": route.service_id,
        },
        headers=make_headers(user),
    )

    assert response.status_code == 200
    assert response.get_json()["name"] == "Updated route"


def test_route_response_contains_team_name_and_permissions(client, db):
    group = create_group(slug=unique("group"))
    team = create_team(group=group, slug=unique("team"), name="Network Team")
    create_route(team=team)

    user = create_user(
        username=unique("group-admin"),
        group=group,
        group_role=GROUP_USER_ADMIN_ROLE,
    )

    response = client.get(
        f"/api/routes?team_id={team.id}",
        headers=make_headers(user),
    )

    assert response.status_code == 200

    payload = response.get_json()
    assert payload

    item = payload[0]
    assert item["team_name"] == "Network Team"
    assert item["team_slug"] == team.slug
    assert item["permissions"]["can_write"] is True


def test_group_editor_can_create_route_for_group_team(client, db):
    group = create_group()
    team = create_team(group)
    user = create_user(group=group, group_role="editor")

    response = client.post(
        "/api/routes",
        json={
            "team_id": team.id,
            "name": "Group editor route",
            "source": "alertmanager",
            "rotation_id": None,
            "escalation_policy_id": None,
            "matcher_preset_id": None,
            "matchers": {},
            "group_by": ["alertname", "instance"],
            "channel_ids": [],
            "service_id": None,
            "enabled": True,
            "notification_channel_mode": "route_only",
            "integration_config": {},
        },
        headers=make_headers(user),
    )

    assert response.status_code == 201


def test_group_viewer_cannot_create_route(client, db):
    group = create_group()
    team = create_team(group)
    user = create_user(group=group, group_role="viewer")

    response = client.post(
        "/api/routes",
        json={
            "team_id": team.id,
            "name": "Viewer route",
            "source": "alertmanager",
            "rotation_id": None,
            "escalation_policy_id": None,
            "matcher_preset_id": None,
            "matchers": {},
            "group_by": ["alertname", "instance"],
            "channel_ids": [],
            "service_id": None,
            "enabled": True,
            "notification_channel_mode": "route_only",
            "integration_config": {},
        },
        headers=make_headers(user),
    )

    assert response.status_code == 403


def test_group_editor_cannot_create_route_for_foreign_group_team(client, db):
    group = create_group()
    foreign_group = create_group()
    foreign_team = create_team(foreign_group)
    user = create_user(group=group, group_role="editor")

    response = client.post(
        "/api/routes",
        json={
            "team_id": foreign_team.id,
            "name": "Foreign route",
            "source": "alertmanager",
            "rotation_id": None,
            "escalation_policy_id": None,
            "matcher_preset_id": None,
            "matchers": {},
            "group_by": ["alertname", "instance"],
            "channel_ids": [],
            "service_id": None,
            "enabled": True,
            "notification_channel_mode": "route_only",
            "integration_config": {},
        },
        headers=make_headers(user),
    )

    assert response.status_code == 403
