"""Expose actual team memberships without expanding administrative visibility."""

import pytest

from app.api.openapi.spec import build_openapi_spec
from app.login import create_access_token
from app.modules.db import teams_repo
from app.modules.db.models import Team, TeamUser, UserGroup
from app.services.serializers.users import serialize_user_team
from tests.factories import add_user_to_team, create_group, create_team, create_user
from tests.integrations.test_admin_api_tokens import personal_token


def headers(user):
    """Authenticate a specific user through the normal request middleware."""
    return {"Authorization": "Bearer " + create_access_token(user)[0]}


@pytest.fixture
def memberships():
    first = create_group(name="Operations")
    second = create_group(name="Development")
    user = create_user(group=first, group_role="viewer")
    UserGroup.create(user=user, group=second, role="viewer")
    alpha = create_team(first, name="Alpha")
    beta = create_team(second, name="Beta")
    add_user_to_team(alpha, user, "responder")
    add_user_to_team(beta, user, "viewer")
    return user, alpha, beta


@pytest.mark.parametrize("is_admin", [False, True])
def test_profile_shows_actual_memberships_across_groups(client, memberships, is_admin):
    user, alpha, beta = memberships
    user.is_admin = is_admin
    user.save()
    create_team(alpha.group, name="Accessible but not a membership")
    other = create_user(group=alpha.group)
    add_user_to_team(create_team(alpha.group), other)
    response = client.get("/api/profile", headers=headers(user))
    assert response.status_code == 200
    assert response.json["teams"] == [
        {"team_id": alpha.id, "team_slug": alpha.slug, "team_name": "Alpha",
         "group_id": alpha.group_id, "group_name": "Operations", "role": "responder", "active": True},
        {"team_id": beta.id, "team_slug": beta.slug, "team_name": "Beta",
         "group_id": beta.group_id, "group_name": "Development", "role": "viewer", "active": True},
    ]
    saved = client.put("/api/profile", headers=headers(user), json={"display_name": "Updated name"})
    assert saved.status_code == 200
    assert saved.json["teams"] == response.json["teams"]


def test_memberships_exclude_removed_data_and_mark_disabled_teams(client, memberships):
    user, alpha, beta = memberships
    alpha.active = False
    alpha.save()
    beta.group.active = False
    beta.group.save()
    for kind in ("deleted_team", "inactive_membership", "deleted_group"):
        team = create_team(create_group())
        membership = add_user_to_team(team, user)
        if kind == "deleted_team":
            team.deleted = True
            team.save()
        elif kind == "inactive_membership":
            membership.active = False
            membership.save()
        else:
            team.group.deleted = True
            team.group.save()
    response = client.get("/api/profile", headers=headers(user))
    assert response.status_code == 200
    assert [(item["team_id"], item["active"]) for item in response.json["teams"]] == [
        (alpha.id, False), (beta.id, False),
    ]


def test_profile_with_no_memberships_does_not_list_accessible_teams(client, admin_user, admin_headers):
    create_team(create_group())
    assert client.get("/api/profile", headers=admin_headers).json["teams"] == []


def test_profile_memberships_are_fresh_after_membership_changes(client, memberships):
    user, alpha, beta = memberships
    auth = headers(user)
    assert len(client.get("/api/profile", headers=auth).json["teams"]) == 2
    TeamUser.update(active=False).where(TeamUser.user == user.id, TeamUser.team == alpha.id).execute()
    TeamUser.update(role="manager").where(TeamUser.user == user.id, TeamUser.team == beta.id).execute()
    teams = client.get("/api/profile", headers=auth).json["teams"]
    assert [(item["team_id"], item["role"]) for item in teams] == [(beta.id, "manager")]


@pytest.mark.parametrize("paginated", [False, True])
def test_admin_list_and_detail_show_target_memberships(client, admin_headers, memberships, paginated):
    user, alpha, beta = memberships
    response = client.get("/api/admin/users", headers=admin_headers,
                          query_string={"page": 1, "page_size": 100} if paginated else {})
    assert response.status_code == 200
    items = response.json["items"] if paginated else response.json
    target = next(item for item in items if item["id"] == user.id)
    assert [item["team_id"] for item in target["teams"]] == [alpha.id, beta.id]
    detail = client.get(f"/api/admin/users/{user.id}", headers=admin_headers)
    assert detail.status_code == 200
    assert detail.json["teams"] == target["teams"]


@pytest.mark.parametrize("paginated", [False, True])
def test_group_admin_sees_memberships_only_in_managed_scope(client, memberships, paginated):
    user, alpha, beta = memberships
    manager = create_user(group=alpha.group, group_role="user_admin")
    UserGroup.create(user=manager, group=beta.group, role="viewer")
    response = client.get("/api/admin/users", headers=headers(manager),
                          query_string={"page": 1} if paginated else {})
    assert response.status_code == 200
    items = response.json["items"] if paginated else response.json
    target = next(item for item in items if item["id"] == user.id)
    assert [item["team_id"] for item in target["teams"]] == [alpha.id]
    assert client.get(f"/api/admin/users/{user.id}", headers=headers(manager)).status_code == 403


@pytest.mark.parametrize("endpoint", ["/api/profile", "/api/admin/users"])
@pytest.mark.parametrize("bound", ["group", "team"])
def test_team_memberships_respect_personal_token_bounds(client, memberships, endpoint, bound):
    user, alpha, beta = memberships
    user.is_admin = True
    user.save()
    sibling = create_team(alpha.group, name="Sibling")
    add_user_to_team(sibling, user)
    bounds = {"group_id": alpha.group_id}
    if bound == "team":
        bounds["team_id"] = alpha.id
    scope = "profile:read" if endpoint == "/api/profile" else "users:read"
    _, auth = personal_token(user, [scope], **bounds)
    response = client.get(endpoint, headers=auth)
    assert response.status_code == 200, response.json
    target = response.json if endpoint == "/api/profile" else next(
        item for item in response.json if item["id"] == user.id
    )
    assert [item["team_id"] for item in target["teams"]] == (
        [alpha.id] if bound == "team" else [alpha.id, sibling.id]
    )


def test_team_list_loading_does_not_query_names_per_membership(db, memberships, monkeypatch):
    user, alpha, beta = memberships
    other = create_user(group=alpha.group)
    add_user_to_team(alpha, other)
    statements = []
    execute = db.execute_sql

    def record(sql, *args, **kwargs):
        statements.append(sql)
        return execute(sql, *args, **kwargs)

    monkeypatch.setattr(db, "execute_sql", record)
    rows = teams_repo.list_user_team_memberships([user.id, other.id])
    serialized = [serialize_user_team(row) for row in rows]
    assert len(serialized) == 3
    assert len(statements) == 1


def test_team_without_group_is_serialized(client, admin_user, admin_headers):
    team = Team.create(name="Legacy team", slug="legacy-no-group")
    add_user_to_team(team, admin_user)
    data = client.get("/api/profile", headers=admin_headers).json["teams"]
    assert len(data) == 1
    assert data[0]["group_name"] is None and data[0]["group_id"] is None


def test_membership_display_does_not_add_write_access(client, memberships):
    user, alpha, _ = memberships
    response = client.put("/api/profile", headers=headers(user),
                          json={"teams": [{"team_id": alpha.id, "role": "manager"}]})
    assert response.status_code == 400
    assert TeamUser.get(TeamUser.user == user.id, TeamUser.team == alpha.id).role == "responder"
    assert client.get("/api/admin/users", headers=headers(user)).status_code == 403


def test_team_membership_responses_are_documented():
    spec = build_openapi_spec()
    for path in ("/api/profile", "/api/admin/users/{user_id}"):
        schema = spec["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        teams = schema["properties"]["teams"]
        assert teams["readOnly"] is True
        assert set(teams["items"]["properties"]["role"]["enum"]) == {"viewer", "responder", "manager"}
