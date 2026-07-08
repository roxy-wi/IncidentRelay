from app.login import create_access_token
from app.version import get_service_version
from tests.factories import create_user


def test_service_version_is_set():
    assert isinstance(get_service_version(), str)
    assert get_service_version()


def test_version_api_is_public(client):
    response = client.get("/api/version", follow_redirects=True)

    assert response.status_code == 200
    payload = response.get_json()

    assert payload["service_version"] == get_service_version()
    assert "migrations" in payload


def test_login_page_renders(client):
    response = client.get("/login")

    assert response.status_code == 200


def test_protected_api_requires_auth(client):
    response = client.get("/api/groups", follow_redirects=True)

    assert response.status_code == 401
    assert response.is_json
    assert response.get_json()["error"] == "JWT or API token authentication is required"


def test_protected_page_redirects_to_login_with_return_url(client):
    response = client.get("/services?tab=impact")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login?next=%2Fservices%3Ftab%3Dimpact")


def test_authenticated_login_redirects_to_return_url(client, db):
    user = create_user(username="return-user")
    token, _ = create_access_token(user)

    response = client.get(
        "/login?next=/services?tab=impact",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/services?tab=impact")


def test_authenticated_login_rejects_external_return_url(client, db):
    user = create_user(username="safe-return-user")
    token, _ = create_access_token(user)

    response = client.get(
        "/login?next=https://evil.example/services",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
