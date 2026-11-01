"""Colors remain stable, editable only through the caller's own profile."""

import re
from datetime import datetime, timedelta
from importlib import import_module
from urllib.parse import urlsplit

import pytest
from peewee import SqliteDatabase

from app.modules.db import users_repo
from app.login import create_access_token
from app.modules.db.models import Incident, User
from app.services.calendar_service import build_rotation_calendar
from app.services.serializers.users import serialize_user, serialize_user_short
from app.modules.user_colors import default_user_color, user_color
from tests.factories import (
    add_user_to_team,
    create_group,
    create_rotation,
    create_team,
    create_user,
)


def test_authenticated_shell_loads_user_appearance_before_consumers(
    client, auth_headers
):
    """A fresh page must include the shared helper and serve it as JavaScript."""
    response = client.get("/profile", headers=auth_headers)
    assert response.status_code == 200
    sources = re.findall(
        r'<script\b[^>]*\bsrc="([^"]+)"', response.get_data(as_text=True)
    )
    paths = [urlsplit(source).path for source in sources]
    appearance = "/static/js/core/user_appearance.js"
    assert paths.count(appearance) == 1
    for consumer in ("core/selects.js", "core/router.js", "pages/profile.js"):
        assert paths.index(appearance) < paths.index(f"/static/js/{consumer}")
    asset = client.get(sources[paths.index(appearance)])
    assert asset.status_code == 200
    assert asset.mimetype in {"text/javascript", "application/javascript"}
    assert "const UserAppearance =" in asset.get_data(as_text=True)


def test_automatic_colors_are_distinct_and_stable(db):
    users = [User.create(username=f"color-{index}") for index in range(64)]
    colors = [user_color(user) for user in users]
    assert len(set(colors)) == len(users)
    first = users[0]
    users_repo.update_user(first.id, {"username": "renamed", "display_name": "Changed"})
    assert user_color(User.get_by_id(first.id)) == colors[0]
    assert all(len(color) == 7 and color.startswith("#") for color in colors)
    assert len({default_user_color(index) for index in range(100_000)}) == 100_000


def test_profile_color_is_persisted_and_reset(client, auth_headers, admin_user):
    original = client.get("/api/profile", headers=auth_headers).json["color"]
    response = client.put(
        "/api/profile", json={"color": " \t#AAbB12\n"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json["color"] == "#aabb12"
    user = User.get_by_id(admin_user.id)
    assert user.color == "#aabb12"
    assert (
        serialize_user(user)["color"]
        == serialize_user_short(user)["color"]
        == user.color
    )
    assert client.get("/api/auth/me", headers=auth_headers).json["color"] == user.color
    client.put("/api/profile", json={"display_name": "Renamed"}, headers=auth_headers)
    assert User.get_by_id(user.id).color == "#aabb12"
    response = client.put("/api/profile", json={"color": None}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json["color"] == original
    assert User.get_by_id(user.id).color is None


@pytest.mark.parametrize(
    "color", ["", "red", "#123", "#12345678", "#gg0000", "#123456;", 123, [], "url(x)"]
)
def test_profile_rejects_invalid_colors_atomically(
    client, auth_headers, admin_user, color
):
    response = client.put(
        "/api/profile",
        json={"color": color, "display_name": "Must not save"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    stored = User.get_by_id(admin_user.id)
    assert stored.color is None
    assert stored.display_name == admin_user.display_name


def test_manual_colors_can_match_and_do_not_edit_other_users(
    client, auth_headers, admin_user
):
    other = create_user()
    other.color = "#ffffff"
    other.save()
    response = client.put(
        "/api/profile", json={"color": "#ffffff"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert User.get_by_id(other.id).color == "#ffffff"
    assert User.get_by_id(admin_user.id).color == "#ffffff"
    assert client.put("/api/profile", json={"color": "#000000"}).status_code == 401


def test_regular_user_can_edit_own_color_without_admin_access(client):
    group = create_group()
    user = create_user(group=group, group_role="viewer")
    other = create_user(group=group)
    token, _ = create_access_token(user)
    headers = {"Authorization": f"Bearer {token}"}
    response = client.put("/api/profile", json={"color": "#234567"}, headers=headers)
    assert response.status_code == 200
    assert User.get_by_id(user.id).color == "#234567"
    response = client.put(
        f"/api/admin/users/{other.id}",
        json={"color": "#234567"},
        headers=headers,
    )
    assert response.status_code == 403
    assert User.get_by_id(other.id).color is None


def test_restoring_an_account_keeps_its_color(db):
    user = create_user()
    user.color = "#abcdef"
    user.save()
    users_repo.soft_delete_user(user.id)
    restored = users_repo.create_user(username=user.username)
    assert restored.id == user.id
    assert user_color(restored) == "#abcdef"


def test_calendar_and_incident_identities_use_current_profile_color(
    client, admin_headers, admin_user, monkeypatch
):
    monkeypatch.setattr(
        "app.services.incidents.stakeholders.notify_stakeholders", lambda *a, **k: None
    )
    group = create_group()
    team = create_team(group)
    user = create_user(group=group)
    add_user_to_team(team, user)
    start = datetime(2026, 10, 1, 9)
    rotation = create_rotation(team, users=[user], start_at=start)
    incident = Incident.create(team=team, title="Colors", assignee=user)
    url = f"/api/incidents/{incident.id}"
    for suffix, role in (
        ("participants", "commander"),
        ("stakeholders", "stakeholder"),
    ):
        response = client.post(
            f"{url}/{suffix}",
            json={"user_id": user.id, "role": role},
            headers=admin_headers,
        )
        assert response.status_code == 201, response.json
    for color in ("#ffffff", "#000000"):
        users_repo.update_user(user.id, {"color": color})
        events = build_rotation_calendar(rotation, start, start + timedelta(days=1))
        assert events and {event["color"] for event in events} == {color}
        for suffix in ("participants", "stakeholders"):
            assert (
                client.get(f"{url}/{suffix}", headers=admin_headers).json[0]["user"][
                    "color"
                ]
                == color
            )
        assert client.get(url, headers=admin_headers).json["assignee"]["color"] == color
    client.put("/api/profile", json={"color": "#123456"}, headers=admin_headers)
    response = client.post(
        f"{url}/comments", json={"body": "Color test"}, headers=admin_headers
    )
    assert response.status_code == 201
    assert response.json["author"]["color"] == "#123456"
    activity = client.get(f"{url}/activity", headers=admin_headers).json
    assert any(
        item["actor"]["color"] == "#123456" for item in activity if item["actor"]
    )


def test_color_migration_preserves_legacy_users(tmp_path, monkeypatch):
    migration = import_module("app.migrations.20261031010000_user_color")
    legacy = SqliteDatabase(tmp_path / "legacy.db", pragmas={"foreign_keys": 1})
    monkeypatch.setattr(migration, "init_database", lambda: legacy)
    table = User._meta.table_name
    try:
        legacy.execute_sql(
            f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, username TEXT)'
        )
        legacy.execute_sql(f'INSERT INTO "{table}" VALUES (1, ?)', ("old-user",))
        migration.upgrade()
        migration.upgrade()
        assert legacy.execute_sql(
            f'SELECT username, color FROM "{table}"'
        ).fetchall() == [("old-user", None)]
        migration.downgrade()
        migration.downgrade()
        assert legacy.execute_sql(f'SELECT username FROM "{table}"').fetchall() == [
            ("old-user",)
        ]
    finally:
        legacy.close()


def test_color_migration_on_configured_database_preserves_membership(db):
    """Upgrade and rollback work on the real SQLite/PostgreSQL schema."""
    from app.modules.db.models import UserGroup

    migration = import_module("app.migrations.20261031010000_user_color")
    group = create_group()
    user = create_user(group=group)
    membership = UserGroup.get(UserGroup.user == user.id)
    try:
        migration.downgrade()
        migration.upgrade()
        migration.upgrade()
        stored = User.get_by_id(user.id)
        assert stored.username == user.username
        assert stored.color is None
        assert user_color(stored) == default_user_color(user.id)
        assert UserGroup.get_by_id(membership.id).user_id == user.id
        users_repo.update_user(user.id, {"color": "#345678"})
        migration.upgrade()
        assert User.get_by_id(user.id).color == "#345678"
    finally:
        migration.upgrade()
