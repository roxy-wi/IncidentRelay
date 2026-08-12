import pytest

from app.login import create_access_token
from app.middleware import api_auth_required_for_path
from app.modules.db import tokens_repo
from app.services.api_token_scopes import (
    PROFILE_TOKEN_SCOPE_OPTIONS,
    required_scopes_for_path,
    token_can_grant_scopes,
    token_has_scopes,
)
from app.services.integrations.auth import hash_token
from tests.factories import create_user, unique


def _api_token_headers(user, scopes, raw_token=None):
    raw_token = raw_token or unique("api-token")
    tokens_repo.create_token(
        name=unique("token"),
        token_prefix=raw_token[:12],
        token_hash=hash_token(raw_token),
        scopes=scopes,
        user=user.id,
    )
    return {"Authorization": f"Bearer {raw_token}"}


def test_profile_token_can_combine_granular_read_scopes(client, admin_headers, db):
    response = client.post(
        "/api/profile/tokens",
        json={
            "name": "grafana-reporting",
            "scopes": [
                "alerts:read",
                "services:read",
                "incidents:read",
                "teams:read",
            ],
            "days": 30,
        },
        headers=admin_headers,
    )

    assert response.status_code == 201
    assert response.get_json()["scopes"] == [
        "alerts:read",
        "incidents:read",
        "services:read",
        "teams:read",
    ]


def test_profile_exposes_available_token_scopes(client, admin_headers, db):
    response = client.get("/api/profile", headers=admin_headers)

    assert response.status_code == 200
    scopes = response.get_json()["available_token_scopes"]

    assert scopes == list(PROFILE_TOKEN_SCOPE_OPTIONS)
    assert "services:read" in scopes
    assert "incidents:read" in scopes
    assert "teams:read" in scopes
    assert "calendar:write" in scopes
    assert "*" in scopes


def test_non_admin_profile_does_not_offer_wildcard_scope(client, db):
    user = create_user(unique("scope-user"), is_admin=False)
    token, _ = create_access_token(user)

    response = client.get(
        "/api/profile",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    scopes = response.get_json()["available_token_scopes"]
    assert "*" not in scopes
    assert "services:read" in scopes


def test_legacy_resources_read_implies_granular_resource_reads():
    assert token_has_scopes(
        ["resources:read"],
        ["services:read", "incidents:read", "teams:read", "calendar:read"],
    )
    assert not token_has_scopes(["resources:read"], ["alerts:read"])
    assert not token_has_scopes(["resources:read"], ["profile:read"])


def test_legacy_resources_write_implies_granular_resource_writes():
    assert token_has_scopes(
        ["resources:write"],
        ["services:write", "teams:write", "calendar:write"],
    )
    assert not token_has_scopes(["resources:write"], ["services:read"])


def test_legacy_aggregate_can_delegate_granular_scope_but_not_reverse():
    assert token_can_grant_scopes(
        ["profile:write", "resources:read"],
        ["services:read", "incidents:read"],
    )
    assert not token_can_grant_scopes(
        ["profile:write", "services:read", "incidents:read"],
        ["resources:read"],
    )


@pytest.mark.parametrize(
    ("path", "method", "expected"),
    [
        ("/api/alerts", "GET", ["alerts:read"]),
        ("/api/alerts/10", "POST", ["alerts:write"]),
        ("/api/incidents", "GET", ["incidents:read"]),
        ("/api/services", "GET", ["services:read"]),
        ("/api/business-services", "GET", ["services:read"]),
        ("/api/teams", "GET", ["teams:read"]),
        ("/api/groups", "POST", ["groups:write"]),
        ("/api/rotations/1", "PUT", ["rotations:write"]),
        ("/api/oncall-health", "GET", ["rotations:read"]),
        ("/api/calendar", "GET", ["calendar:read"]),
        ("/api/calendar/feeds", "POST", ["calendar:write"]),
        ("/api/routes", "GET", ["routes:read"]),
        ("/api/channels", "POST", ["channels:write"]),
        ("/api/maintenance-windows", "GET", ["maintenance:read"]),
        ("/api/silences", "POST", ["maintenance:write"]),
        ("/api/heartbeats", "GET", ["heartbeats:read"]),
        ("/api/notification-policies", "GET", ["policies:read"]),
        ("/api/matcher-presets", "POST", ["policies:write"]),
        ("/api/event-orchestrations", "GET", ["orchestrations:read"]),
        ("/api/admin/audit-logs", "GET", ["audit:read"]),
        ("/api/admin/sso", "POST", ["sso:write"]),
        ("/api/profile", "GET", ["profile:read"]),
        ("/api/openapi.json", "GET", ["profile:read"]),
    ],
)
def test_api_paths_map_to_granular_scopes(path, method, expected):
    assert required_scopes_for_path(path, method) == expected


def test_unmapped_api_path_is_fail_closed_in_scope_map():
    assert required_scopes_for_path("/api/future-resource", "GET") is None


@pytest.mark.parametrize(
    ("path", "method", "protected"),
    [
        ("/api/integrations/grafana", "POST", False),
        ("/api/heartbeats/ping/secret", "POST", False),
        ("/api/calendar/feeds/public-token.ics", "GET", False),
        ("/api/calendar/feeds", "GET", True),
        ("/api/calendar/feeds/1/token", "POST", True),
    ],
)
def test_public_and_management_api_paths_keep_auth_boundaries(path, method, protected):
    assert api_auth_required_for_path(path, method=method) is protected


def test_every_protected_flask_api_route_has_scope_mapping(app):
    missing = []

    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/"):
            continue

        for method in sorted(set(rule.methods or ()) - {"OPTIONS"}):
            if not api_auth_required_for_path(rule.rule, method=method):
                continue

            if required_scopes_for_path(rule.rule, method) is None:
                missing.append((method, rule.rule))

    assert missing == []


def test_unmapped_api_path_is_denied_even_for_wildcard_token(client, admin_user, db):
    headers = _api_token_headers(
        admin_user,
        ["*"],
        raw_token="unmapped-scope-wildcard-token",
    )

    response = client.get("/api/future-resource", headers=headers)

    assert response.status_code == 403
    assert response.get_json() == {
        "error": "API token access is not configured for this endpoint",
    }


def test_alert_only_token_cannot_read_services(client, admin_user, db):
    headers = _api_token_headers(
        admin_user,
        ["alerts:read"],
        raw_token="alerts-only-token",
    )

    response = client.get("/api/services", headers=headers)

    assert response.status_code == 403
    assert response.get_json() == {
        "error": "Missing API token scope",
        "missing_scopes": ["services:read"],
    }


def test_legacy_resources_read_token_can_read_services(client, admin_user, db):
    headers = _api_token_headers(
        admin_user,
        ["resources:read"],
        raw_token="legacy-resources-read-token",
    )

    response = client.get("/api/services", headers=headers)

    assert response.status_code == 200


def test_resources_read_token_can_mint_granular_reporting_token(client, db):
    user = create_user(unique("reporting-user"), is_admin=False)
    headers = _api_token_headers(
        user,
        ["profile:write", "resources:read"],
        raw_token="legacy-delegating-token",
    )

    response = client.post(
        "/api/profile/tokens",
        json={
            "name": "reporting-child",
            "scopes": ["services:read", "incidents:read", "teams:read"],
            "days": 0,
        },
        headers=headers,
    )

    assert response.status_code == 201
    assert response.get_json()["scopes"] == [
        "incidents:read",
        "services:read",
        "teams:read",
    ]
