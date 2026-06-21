from app.login import create_access_token
from app.modules.db import tokens_repo
from app.modules.db.models import ApiToken
from app.services.integrations.auth import hash_token
from tests.factories import create_user, unique


def auth_headers_for_user(user):
    token, _ = create_access_token(user)

    return {
        "Authorization": f"Bearer {token}",
    }


def bearer_headers(raw_token):
    return {
        "Authorization": f"Bearer {raw_token}",
    }


def create_personal_api_token(user, *, scopes, raw_token=None):
    raw_token = raw_token or unique("api-token")

    token = tokens_repo.create_token(
        name=unique("token"),
        token_prefix=raw_token[:12],
        token_hash=hash_token(raw_token),
        scopes=scopes,
        user=user.id,
    )

    return raw_token, token


def test_profile_token_can_be_created_with_calendar_read_scope(client, admin_user, db):
    response = client.post(
        "/api/profile/tokens",
        json={
            "name": "caldav-calendar",
            "scopes": ["calendar:read"],
            "days": 0,
        },
        headers=auth_headers_for_user(admin_user),
    )

    assert response.status_code == 201

    payload = response.get_json()

    assert payload["name"] == "caldav-calendar"
    assert payload["scopes"] == ["calendar:read"]
    assert payload["token"]
    assert payload["token_prefix"] == payload["token"][:12]

    token = ApiToken.get_by_id(payload["id"])

    assert token.user.id == admin_user.id
    assert token.scopes == ["calendar:read"]
    assert token.token_hash
    assert token.token_hash != payload["token"]


def test_profile_token_rejects_unknown_scope(client, admin_user, db):
    response = client.post(
        "/api/profile/tokens",
        json={
            "name": "bad-token",
            "scopes": ["calendar:write"],
            "days": 0,
        },
        headers=auth_headers_for_user(admin_user),
    )

    assert response.status_code == 400

    payload = response.get_json()

    assert payload["error"] == "Unknown token scopes"
    assert payload["unknown_scopes"] == ["calendar:write"]


def test_profile_token_rejects_wildcard_scope_for_non_admin(client, db):
    user = create_user(unique("alice"), is_admin=False)

    response = client.post(
        "/api/profile/tokens",
        json={
            "name": "wildcard-token",
            "scopes": ["*"],
            "days": 0,
        },
        headers=auth_headers_for_user(user),
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "Wildcard scope is allowed for admin users only"


def test_profile_token_with_only_calendar_read_cannot_create_profile_token(client, db):
    user = create_user(unique("alice"), is_admin=False)
    raw_token, _ = create_personal_api_token(
        user,
        scopes=["calendar:read"],
        raw_token="calendar-source-token",
    )

    response = client.post(
        "/api/profile/tokens",
        json={
            "name": "another-calendar-token",
            "scopes": ["calendar:read"],
            "days": 0,
        },
        headers=bearer_headers(raw_token),
    )

    assert response.status_code == 403

    payload = response.get_json()

    assert payload["error"] == "Missing API token scope"
    assert payload["missing_scopes"] == ["profile:write"]


def test_profile_token_cannot_create_broader_scope_than_current_api_token(client, db):
    user = create_user(unique("alice"), is_admin=False)
    raw_token, _ = create_personal_api_token(
        user,
        scopes=["profile:write", "calendar:read"],
        raw_token="calendar-source-token",
    )

    response = client.post(
        "/api/profile/tokens",
        json={
            "name": "broader-token",
            "scopes": ["calendar:read", "alerts:read"],
            "days": 0,
        },
        headers=bearer_headers(raw_token),
    )

    assert response.status_code == 403

    payload = response.get_json()

    assert payload["error"] == "Cannot create a token with broader scopes than the current token"
    assert payload["allowed_scopes"] == ["calendar:read", "profile:write"]
    assert payload["requested_scopes"] == ["alerts:read", "calendar:read"]


def test_profile_write_api_token_can_create_calendar_read_token(client, db):
    user = create_user(unique("alice"), is_admin=False)
    raw_token, _ = create_personal_api_token(
        user,
        scopes=["profile:write", "calendar:read"],
        raw_token="profile-write-source-token",
    )

    response = client.post(
        "/api/profile/tokens",
        json={
            "name": "calendar-token",
            "scopes": ["calendar:read"],
            "days": 0,
        },
        headers=bearer_headers(raw_token),
    )

    assert response.status_code == 201

    payload = response.get_json()

    assert payload["name"] == "calendar-token"
    assert payload["scopes"] == ["calendar:read"]
    assert payload["token"]


def test_profile_token_with_wildcard_api_token_can_create_calendar_read_token(client, db):
    user = create_user(unique("admin-token-user"), is_admin=True)
    raw_token, _ = create_personal_api_token(
        user,
        scopes=["*"],
        raw_token="wildcard-source-token",
    )

    response = client.post(
        "/api/profile/tokens",
        json={
            "name": "calendar-token",
            "scopes": ["calendar:read"],
            "days": 0,
        },
        headers=bearer_headers(raw_token),
    )

    assert response.status_code == 201
    assert response.get_json()["scopes"] == ["calendar:read"]
