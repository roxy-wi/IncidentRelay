"""Administrative API tokens retain scopes, role checks and Group boundaries."""

from datetime import timedelta

import pytest

from app.api.openapi.spec import build_openapi_spec
from app.modules.common import utc_now
from app.modules.db import tokens_repo
from app.modules.db.models import (
    ApiToken,
    AuditLog,
    ChangeIntegration,
    ChangeJob,
    UserGroup,
)
from app.services import system_settings
from app.services.api_token_scopes import (
    PROFILE_TOKEN_SCOPE_OPTIONS,
    required_scopes_for_path,
)
from app.services.change_intelligence import administration as admin
from app.services.integrations.auth import hash_token
from app.settings import Config
from tests.factories import create_group, create_team, create_user, unique


INTEGRATIONS = "/api/admin/change-integrations"
SETTINGS = "/api/admin/system-settings"
DOMAINS = [(INTEGRATIONS, "change-integrations"), (SETTINGS, "system-settings")]


def personal_token(user, scopes, **bounds):
    """Return the stored token and Bearer header, without a JWT cookie."""
    raw = unique("personal")
    token = tokens_repo.create_api_token(
        "admin-client",
        raw[:8],
        hash_token(raw),
        scopes,
        user_id=user.id if user else None,
        **bounds,
    )
    return token, {"Authorization": f"Bearer {raw}"}


@pytest.mark.parametrize("path,domain", DOMAINS)
def test_administrative_scopes_are_available_and_documented(
    client, admin_headers, path, domain
):
    read, write = f"{domain}:read", f"{domain}:write"
    assert {read, write} <= set(PROFILE_TOKEN_SCOPE_OPTIONS)
    assert required_scopes_for_path(path, "HEAD") == [read]
    assert required_scopes_for_path(path, "PATCH") == [write]
    created = client.post(
        "/api/profile/tokens",
        headers=admin_headers,
        json={"name": "admin automation", "scopes": [read, write], "days": 1},
    )
    assert created.status_code == 201
    auth = {"Authorization": "Bearer " + created.json["token"]}
    assert client.get(path, headers=auth).status_code == 200
    spec = build_openapi_spec()["paths"][path]
    assert read in spec["get"]["description"]
    assert write in spec["patch" if path == SETTINGS else "post"]["description"]


@pytest.mark.parametrize("auth_required", [False, True])
@pytest.mark.parametrize("path,domain", DOMAINS)
@pytest.mark.parametrize(
    "scopes", [[], ["changes:write"], ["resources:read", "resources:write"]]
)
def test_unrelated_scopes_do_not_grant_admin_access(
    client,
    admin_user,
    monkeypatch,
    auth_required,
    path,
    domain,
    scopes,
):
    monkeypatch.setattr(Config, "API_AUTH_REQUIRED", auth_required)
    _, auth = personal_token(admin_user, scopes)
    response = client.get(path, headers=auth)
    assert response.status_code == 403
    assert response.json["missing_scopes"] == [f"{domain}:read"]


@pytest.mark.parametrize("path,domain", DOMAINS)
@pytest.mark.parametrize(
    "state",
    ["expired", "revoked", "deleted", "inactive_user", "deleted_user", "no_user"],
)
def test_invalid_admin_credentials_cannot_use_cookie_fallback(
    client,
    admin_user,
    admin_headers,
    path,
    domain,
    state,
    monkeypatch,
):
    monkeypatch.setattr(Config, "API_AUTH_REQUIRED", False)
    token, auth = personal_token(admin_user if state != "no_user" else None, ["*"])
    if state == "expired":
        token.expires_at = utc_now() - timedelta(seconds=1)
    elif state == "revoked":
        token.active = False
    elif state == "deleted":
        token.deleted = True
    elif state == "inactive_user":
        admin_user.active = False
        admin_user.save()
    elif state == "deleted_user":
        admin_user.deleted = True
        admin_user.save()
    token.save()
    client.set_cookie(
        Config.JWT_COOKIE_NAME, admin_headers["Authorization"].split(" ", 1)[1]
    )
    assert client.get(path, headers=auth).status_code == 401


@pytest.mark.parametrize("path,domain", DOMAINS)
def test_scopes_do_not_replace_administrator_role(client, path, domain):
    user = create_user(group=create_group(), group_role="editor")
    _, auth = personal_token(user, ["*"])
    assert client.get(path, headers=auth).status_code == 403


@pytest.mark.parametrize("scope", ["system-settings:write", "*"])
def test_settings_write_token_audits_actor_and_token_idempotently(
    client, admin_user, scope
):
    token, auth = personal_token(admin_user, [scope])
    assert client.get(SETTINGS, headers=auth).status_code == (
        200 if scope == "*" else 403
    )
    for _ in range(2):
        response = client.patch(
            SETTINGS, headers=auth, json={"change_intake_enabled": True}
        )
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
    logs = list(AuditLog.select().where(AuditLog.action == "system_settings.updated"))
    assert len(logs) == 1
    assert logs[0].user_id == admin_user.id
    assert logs[0].api_token_id == token.id


@pytest.mark.parametrize("bound", ["group_id", "team_id"])
def test_bound_global_admin_tokens_cannot_change_system_settings(
    client, admin_user, bound
):
    group = create_group()
    team = create_team(group)
    _, auth = personal_token(
        admin_user, ["*"], **{bound: group.id if bound == "group_id" else team.id}
    )
    assert client.get(SETTINGS, headers=auth).status_code == 403
    assert (
        client.patch(
            SETTINGS, headers=auth, json={"change_intake_enabled": True}
        ).status_code
        == 403
    )
    assert system_settings.get_settings().change_intake_enabled is False


def test_read_only_admin_tokens_cannot_mutate(client, admin_user):
    _, auth = personal_token(
        admin_user, ["system-settings:read", "change-integrations:read"]
    )
    assert client.get(SETTINGS, headers=auth).status_code == 200
    assert client.get(INTEGRATIONS, headers=auth).status_code == 200
    assert (
        client.patch(
            SETTINGS, headers=auth, json={"change_intake_enabled": True}
        ).status_code
        == 403
    )
    assert client.post(INTEGRATIONS, headers=auth, json={}).status_code == 403


def test_write_only_token_can_create_and_return_integration(client, admin_user):
    team = create_team(create_group())
    token, auth = personal_token(admin_user, ["change-integrations:write"])
    response = client.post(
        INTEGRATIONS, headers=auth, json={"name": "pipeline", "owner_team_id": team.id}
    )
    assert response.status_code == 201
    assert response.json["sources"][0]["owner_team_id"] == team.id
    assert (
        client.get(f"{INTEGRATIONS}/{response.json['id']}", headers=auth).status_code
        == 403
    )
    assert (
        AuditLog.get(AuditLog.action == "change_integration.created").api_token_id
        == token.id
    )


@pytest.mark.parametrize("global_admin", [False, True])
def test_group_bound_tokens_cannot_escape_owned_integrations(
    client, admin_user, global_admin
):
    group, foreign = create_group(), create_group()
    team, other_team = create_team(group), create_team(foreign)
    user = create_user(group=group, group_role="user_admin", is_admin=global_admin)
    UserGroup.create(user=user, group=foreign, role="user_admin", active=True)
    owned = admin.create_integration(
        "owned", actor_id=admin_user.id, owner_group_id=group.id
    )
    other = admin.create_integration(
        "foreign", actor_id=admin_user.id, owner_group_id=foreign.id
    )
    central = admin.create_integration("central", actor_id=admin_user.id)
    _, auth = personal_token(user, ["*"], group_id=group.id)
    assert [
        item["id"] for item in client.get(INTEGRATIONS, headers=auth).json["items"]
    ] == [owned.id]
    assert client.get(f"{INTEGRATIONS}/{owned.id}", headers=auth).status_code == 200
    choices = client.get(INTEGRATIONS + "/targets", headers=auth).json
    assert choices["groups"] == [{"id": group.id, "name": group.name}]
    assert [item["id"] for item in choices["teams"]] == [team.id]
    assert choices["can_create_central"] is False
    assert client.get(INTEGRATIONS + "/jobs", headers=auth).status_code == 403
    assert (
        client.post(
            INTEGRATIONS + "/jobs/999/retry",
            headers=auth,
            json={"expected_generation": 1},
        ).status_code
        == 403
    )
    for target in (other, central):
        base = f"{INTEGRATIONS}/{target.id}"
        assert client.get(base, headers=auth).status_code == 404
        assert client.get(base + "/jobs", headers=auth).status_code == 404
        assert (
            client.get(
                INTEGRATIONS + f"/targets?integration_id={target.id}", headers=auth
            ).status_code
            == 404
        )
        for suffix, method, body in [
            ("", "PATCH", {"expected_revision": 1, "active": False}),
            ("/tokens", "POST", {"expected_revision": 1, "name": "escape"}),
            (
                "/sources",
                "POST",
                {
                    "expected_revision": 1,
                    "owner_team_id": other_team.id,
                    "source": "escape",
                },
            ),
        ]:
            assert (
                client.open(
                    base + suffix, method=method, headers=auth, json=body
                ).status_code
                == 404
            )
    for owner in (None, foreign.id):
        assert (
            client.post(
                INTEGRATIONS,
                headers=auth,
                json={
                    "name": "escape",
                    "owner_team_id": other_team.id,
                    "owner_group_id": owner,
                },
            ).status_code
            == 403
        )
    _, team_auth = personal_token(user, ["*"], team_id=team.id)
    assert client.get(INTEGRATIONS, headers=team_auth).status_code == 403
    assert client.post(INTEGRATIONS, headers=team_auth, json={}).status_code == 403


def test_personal_token_manages_sources_grants_credentials_and_jobs(client, admin_user):
    group = create_group()
    team = create_team(group)
    user = create_user(group=group, group_role="user_admin")
    token, auth = personal_token(
        user,
        ["change-integrations:read", "change-integrations:write"],
        group_id=group.id,
    )
    created = client.post(
        INTEGRATIONS,
        headers=auth,
        json={
            "name": "pipeline",
            "owner_group_id": group.id,
            "owner_team_id": team.id,
        },
    )
    assert created.status_code == 201
    integration_id = created.json["id"]
    base = f"{INTEGRATIONS}/{integration_id}"

    def mutate(suffix, body, method="POST", status=201):
        current = client.get(base, headers=auth)
        assert current.status_code == 200, current.json
        revision = current.json["auth_revision"]
        response = client.open(
            base + suffix,
            method=method,
            headers=auth,
            json={"expected_revision": revision, **body},
        )
        assert response.status_code == status, response.json
        return response.json

    source = mutate("/sources", {"source": "second", "owner_team_id": team.id})[
        "sources"
    ][-1]
    mutate(f"/sources/{source['id']}", {"ordering_mode": "sequence"}, "PATCH", 200)
    grants = mutate(
        f"/sources/{source['id']}/grants",
        {"capability": "changed", "target_team_id": team.id},
    )
    grant = grants["sources"][-1]["grants"][0]
    mutate(
        f"/sources/{source['id']}/grants/{grant['id']}", {"active": False}, "PATCH", 200
    )
    issued = mutate("/tokens", {"name": "machine"})
    rotated = mutate(
        f"/tokens/{issued['credential']['id']}/rotate", {"name": "replacement"}
    )
    assert not ApiToken.get_by_id(issued["credential"]["id"]).active
    mutate(f"/tokens/{rotated['credential']['id']}/revoke", {}, status=200)
    assert not ApiToken.get_by_id(rotated["credential"]["id"]).active
    job = client.get(base + "/jobs", headers=auth).json["items"][0]
    retried = client.post(
        base + f"/jobs/{job['id']}/retry",
        headers=auth,
        json={"expected_generation": job["requested_generation"]},
    )
    assert retried.status_code == 200
    assert (
        ChangeJob.get_by_id(job["id"]).requested_generation
        > job["requested_generation"]
    )
    logs = list(
        AuditLog.select().where(AuditLog.action.startswith("change_integration."))
    )
    assert logs and all(
        log.api_token_id == token.id and log.user_id == user.id for log in logs
    )
    assert issued["token"] not in str([log.data for log in logs])


def test_automation_token_reads_updates_and_rejects_stale_integration_edits(
    client, admin_headers
):
    team = create_team(create_group())
    issued = client.post(
        "/api/profile/tokens",
        headers=admin_headers,
        json={
            "name": "terraform",
            "scopes": [
                "change-integrations:read",
                "change-integrations:write",
                "system-settings:read",
                "system-settings:write",
            ],
            "days": 1,
        },
    )
    assert issued.status_code == 201
    auth = {"Authorization": "Bearer " + issued.json["token"]}
    assert client.get(SETTINGS, headers=auth).json["change_intake_enabled"] is False
    updated = client.patch(
        SETTINGS, headers=auth, json={"change_intake_enabled": True}
    )
    assert updated.status_code == 200
    assert client.get(SETTINGS, headers=auth).json["change_intake_enabled"] is True

    created = client.post(
        INTEGRATIONS,
        headers=auth,
        json={"name": "terraform", "owner_team_id": team.id},
    )
    assert created.status_code == 201
    path = f"{INTEGRATIONS}/{created.json['id']}"
    current = client.get(path, headers=auth)
    assert current.status_code == 200
    revision = current.json["auth_revision"]
    updated = client.patch(
        path, headers=auth,
        json={"name": "managed", "expected_revision": revision},
    )
    assert updated.status_code == 200
    refreshed = client.get(path, headers=auth)
    assert refreshed.status_code == 200
    assert refreshed.json["name"] == "managed"
    assert refreshed.json["auth_revision"] > revision
    stale = client.patch(
        path, headers=auth,
        json={"name": "stale overwrite", "expected_revision": revision},
    )
    assert stale.status_code == 409
    assert client.get(path, headers=auth).json == refreshed.json
    assert AuditLog.select().where(
        AuditLog.action == "change_integration.updated"
    ).count() == 1


@pytest.mark.parametrize("operation", ["settings", "integration"])
@pytest.mark.parametrize("revoke", [True, False])
def test_admin_token_authority_is_rechecked_before_commit(
    client, admin_user, monkeypatch, operation, revoke
):
    token, auth = personal_token(admin_user, ["*"])
    integration = admin.create_integration("unchanged", actor_id=admin_user.id)
    module, name = (
        (system_settings, "update_settings")
        if operation == "settings"
        else (admin, "update_integration")
    )
    original = getattr(module, name)

    def change_authority(*args, **kwargs):
        ApiToken.update(
            active=False if revoke else True, scopes=[] if not revoke else ["*"]
        ).where(ApiToken.id == token.id).execute()
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, change_authority)
    path = SETTINGS if operation == "settings" else f"{INTEGRATIONS}/{integration.id}"
    body = (
        {"change_intake_enabled": True}
        if operation == "settings"
        else {"expected_revision": 1, "name": "denied"}
    )
    result = client.patch(path, headers=auth, json=body)
    assert result.status_code == (403 if operation == "settings" else 404)
    assert system_settings.get_settings().change_intake_enabled is False
    assert ChangeIntegration.get_by_id(integration.id).name == "unchanged"


def test_group_bound_admin_token_redacts_catalog_moved_outside_group(client, admin_user):
    group = create_group()
    team = create_team(group, name="Moved private team")
    integration = admin.create_integration(
        "owned", actor_id=admin_user.id, owner_group_id=group.id,
        owner_team_id=team.id,
    )
    team.group = create_group()
    team.save()
    _, auth = personal_token(admin_user, ["change-integrations:read"], group_id=group.id)
    response = client.get(f"{INTEGRATIONS}/{integration.id}", headers=auth)
    assert response.status_code == 200
    assert response.json["sources"][0]["owner_team_name"] is None
    assert team.name not in str(response.json)
