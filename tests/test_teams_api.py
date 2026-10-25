from tests.factories import create_group, create_team, create_user


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


def test_team_list_reports_current_user_membership(client, admin_user, admin_headers):
    from tests.factories import add_user_to_team

    group = create_group()
    member_team = create_team(group=group)
    other_team = create_team(group=group)
    add_user_to_team(member_team, admin_user, role="viewer")

    response = client.get("/api/teams", headers=admin_headers)

    assert response.status_code == 200

    teams = {item["id"]: item for item in response.get_json()}
    assert teams[member_team.id]["is_member"] is True
    assert teams[other_team.id]["is_member"] is False
