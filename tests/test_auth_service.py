from types import SimpleNamespace

from app.login import (
    create_access_token,
    decode_access_token,
    hash_password,
    normalize_auth_redirect_target,
    verify_password,
)
from app.services.integrations.auth import create_raw_token, get_bearer_token, hash_token, token_has_scope


def test_password_hash_is_not_plaintext_and_can_be_verified():
    password_hash = hash_password("password-123")

    assert password_hash != "password-123"
    assert verify_password("password-123", password_hash)
    assert not verify_password("wrong-password", password_hash)
    assert not verify_password("password-123", None)


def test_jwt_access_token_round_trip():
    user = SimpleNamespace(id=42, username="alice", is_admin=True)

    token, expires_at = create_access_token(user)
    payload = decode_access_token(token)

    assert payload["sub"] == "42"
    assert payload["username"] == "alice"
    assert payload["is_admin"] is True
    assert expires_at is not None


def test_api_token_hash_is_stable_and_not_plaintext():
    raw = create_raw_token()

    assert isinstance(raw, str)
    assert len(raw) > 40
    assert hash_token(raw) == hash_token(raw)
    assert hash_token(raw) != raw


def test_token_scope_matching():
    token = SimpleNamespace(scopes=["alerts:write", "routes:read"])

    assert token_has_scope(token, [])
    assert token_has_scope(token, ["alerts:write"])
    assert token_has_scope(token, ["alerts:write", "routes:read"])
    assert not token_has_scope(token, ["admin"])


def test_token_scope_wildcard_matches_everything():
    token = SimpleNamespace(scopes=["*"])

    assert token_has_scope(token, ["admin", "alerts:write"])


def test_get_bearer_token_extracts_authorization_header(app):
    with app.test_request_context("/", headers={"Authorization": "Bearer test-token"}):
        assert get_bearer_token() == "test-token"


def test_get_bearer_token_rejects_non_bearer_header(app):
    with app.test_request_context("/", headers={"Authorization": "Basic abc"}):
        assert get_bearer_token() is None


def test_normalize_auth_redirect_target_accepts_local_path_with_query_and_fragment():
    assert normalize_auth_redirect_target("/services?tab=impact#graph") == "/services?tab=impact#graph"


def test_normalize_auth_redirect_target_rejects_external_and_auth_urls():
    assert normalize_auth_redirect_target("https://evil.example/services") == "/"
    assert normalize_auth_redirect_target("//evil.example/services") == "/"
    assert normalize_auth_redirect_target("/login") == "/"
    assert normalize_auth_redirect_target("/api/auth/login") == "/"
