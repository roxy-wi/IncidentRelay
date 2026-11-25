from unittest.mock import patch

import pytest

from app.login import create_access_token
from app.modules.db import tokens_repo
from app.modules.token_hashing import hash_token
from app.views import teams_view
from tests.factories import add_user_to_team, create_group, create_team, create_user, unique


def test_add_team_user_respects_active_checkbox(client, admin_headers):
    group = create_group()
    team = create_team(group=group)
    user = create_user(group=group)

    response = client.post(
        f"/api/teams/{team.id}/users",
        json={
            "user_id": user.id,
            "role": "viewer",
            "active": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 201

    data = response.get_json()
    assert data["active"] is False

    members_response = client.get(
        f"/api/teams/{team.id}/users",
        headers=admin_headers,
    )

    assert members_response.status_code == 200

    members = members_response.get_json()
    membership = next(item for item in members if item["user_id"] == user.id)

    assert membership["active"] is False


def test_teams_directory_pages_filters_and_summary(client, admin_headers):
    group = create_group(slug="platform")
    other = create_group(slug="operations")
    first = create_team(group, name="Platform A")
    last = create_team(group, name="Platform B")
    archived = create_team(other, name="Archive")
    archived.active = archived.escalation_enabled = False
    archived.description = "Сеть_100%"
    archived.save()
    deleted = create_team(other)
    deleted.deleted = True
    deleted.save()

    def page(**filters):
        response = client.get("/api/teams", headers=admin_headers, query_string={
            "page_size": 1, "include_inactive": 1, **filters,
        })
        assert response.status_code == 200
        return response.get_json()

    with patch.object(teams_view, "get_team_health_summary",
                      wraps=teams_view.get_team_health_summary) as health:
        result = page(page=2, group=group.slug, status="active", search="PLATFORM", include_health=1)
        assert [row["id"] for row in result["items"]] == [last.id]
        assert result["items"][0]["health"]["status"] == "critical"
        assert [call.args[0].id for call in health.call_args_list] == [last.id]
        assert result["pagination"] == {
            "page": 2, "page_size": 1, "total_pages": 2, "total_items": 2,
            "from": 2, "to": 2, "has_prev": True, "has_next": False,
        }
        assert result["summary"] == {"total": 3, "active": 2, "escalation": 2, "groups": 2}
        assert result["group_slugs"] == ["operations", "platform"]

        result = page(page=99, status="inactive", search="СЕТЬ_100%")
        assert [row["id"] for row in result["items"]] == [archived.id]
        assert "health" not in result["items"][0]
        assert result["pagination"]["page"] == 1
        assert page(search="100%missing")["items"] == []
        assert page(include_inactive=0)["summary"]["total"] == 2
        scoped = page(team_id=last.id)
        assert scoped["summary"]["total"] == 1
        assert scoped["group_slugs"] == [group.slug]

        legacy = client.get("/api/teams?include_inactive=1", headers=admin_headers).get_json()
        assert [row["id"] for row in legacy] == [first.id, last.id, archived.id]
        assert all("health" not in row for row in legacy)
        assert health.call_count == 1


def test_paged_team_directory_separates_visibility_and_health_access(client, db):
    group = create_group()
    own, sibling = create_team(group), create_team(group)
    outside = create_team(create_group())
    viewer = create_user(group=group, group_role="viewer")
    add_user_to_team(own, viewer, role="viewer")
    headers = {"Authorization": f"Bearer {create_access_token(viewer)[0]}"}
    with patch.object(teams_view, "get_team_health_summary",
                      wraps=teams_view.get_team_health_summary) as health:
        result = client.get("/api/teams?page=1&include_health=1", headers=headers).get_json()
        rows = {row["id"]: row for row in result["items"]}
        assert set(rows) == {own.id, sibling.id}
        assert rows[own.id]["health"]["partial"] is True
        assert "health" not in rows[sibling.id]
        assert result["summary"]["total"] == 2
        assert result["group_slugs"] == [group.slug]
        assert [call.args[0].id for call in health.call_args_list] == [own.id]
        empty = client.get(f"/api/teams?page=1&team_id={outside.id}", headers=headers).get_json()
        assert empty["items"] == empty["group_slugs"] == []
        assert empty["summary"]["total"] == 0


@pytest.mark.parametrize("allow_health", [True, False])
def test_paged_team_health_respects_token_scope_and_team_bound(client, admin_user, allow_health):
    group = create_group()
    own = create_team(group)
    create_team(group)
    raw = unique("team-directory")
    scopes = ["teams:read", "rotations:read"] if allow_health else ["teams:read"]
    tokens_repo.create_api_token(
        "Directory", raw[:8], hash_token(raw), scopes, team_id=own.id, user_id=admin_user.id,
    )
    response = client.get("/api/teams?page=1&include_health=1", headers={"Authorization": f"Bearer {raw}"})
    assert response.status_code == 200
    result = response.get_json()
    assert [row["id"] for row in result["items"]] == [own.id]
    assert ("health" in result["items"][0]) is allow_health
    assert result["summary"]["total"] == 1
    assert result["group_slugs"] == [group.slug]
