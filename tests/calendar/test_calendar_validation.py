from tests.factories import create_group, create_team, create_user


def _auth_headers(client, user):
    response = client.post(
        "/api/auth/login",
        json={"username": user.username, "password": "password-123"},
    )
    assert response.status_code == 200
    token = response.get_json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_calendar_rejects_invalid_start_and_end(client):
    group = create_group()
    team = create_team(group)
    admin = create_user(is_admin=True)

    response = client.get(
        f"/api/calendar?team_id={team.id}&start=string&end=string",
        headers=_auth_headers(client, admin),
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"] == "validation_error"
    assert payload["message"] == "Request validation failed"
    assert {detail["field"] for detail in payload["details"]} == {"start", "end"}
    assert all(detail["type"] == "datetime_parsing" for detail in payload["details"])


def test_calendar_rejects_end_before_start(client):
    group = create_group()
    team = create_team(group)
    admin = create_user(is_admin=True)

    response = client.get(
        f"/api/calendar?team_id={team.id}&start=2026-05-02&end=2026-05-01",
        headers=_auth_headers(client, admin),
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"] == "validation_error"
    assert payload["details"][0]["field"] == "end"
    assert payload["details"][0]["message"] == "end must be after start"
