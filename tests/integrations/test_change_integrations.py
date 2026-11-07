"""Administration, machine boundaries and live grant regression coverage."""

from datetime import timedelta

import pytest

from app.api.schemas.change_integrations import (
    GrantCreate,
    GrantUpdate,
    IntegrationUpdate,
    MachineTokenCreate,
    RevisionInput,
    SourceCreate,
    SourceUpdate,
)
from app.login import create_access_token
from app.modules.common import utc_now
from app.modules.db import groups_repo, services_repo, teams_repo, tokens_repo
from app.modules.db.models import (
    ApiToken,
    AuditLog,
    Change,
    ChangeEvent,
    ChangeGrant,
    ChangeIntegration,
    ChangeJob,
    ChangeSource,
    Service,
)
from app.services.api_token_scopes import required_scopes_for_path, token_has_scopes
from app.services.change_intelligence import administration as admin
from app.services.change_intelligence.authorization import (
    ChangeAccessDenied,
    authorize_reference,
    authorized_source,
)
from app.services.integrations.auth import hash_token
from app.settings import Config
from tests.factories import create_group, create_service, create_team, create_user


BASE = "/api/admin/change-integrations"


@pytest.fixture
def setup_identity(admin_user):
    team = create_team(create_group())
    service = create_service(team)
    integration = admin.create_integration("CI/CD", actor_id=admin_user.id)
    source = admin.create_source(
        integration.id,
        SourceCreate(
            expected_revision=1,
            owner_team_id=team.id,
            source="deploy",
        ),
        actor_id=admin_user.id,
    )
    return integration, source, service, admin_user


def revision(integration):
    return ChangeIntegration.get_by_id(integration.id).auth_revision


def credential(identity):
    integration, _, _, actor = identity
    return admin.issue_token(
        integration.id,
        MachineTokenCreate(
            expected_revision=revision(integration),
            name="CI",
            days=30,
        ),
        actor_id=actor.id,
    )


def grant(identity, *, capability="changed", team=None, service=None):
    integration, source, own_service, actor = identity
    return admin.create_grant(
        integration.id,
        source.id,
        GrantCreate(
            expected_revision=revision(integration),
            capability=capability,
            target_team_id=team or own_service.team_id,
            target_service_id=service,
        ),
        actor_id=actor.id,
    )


@pytest.mark.parametrize("auth_required", [True, False])
def test_admin_namespace_requires_admin_jwt(
    client, admin_headers, setup_identity, monkeypatch, auth_required
):
    monkeypatch.setattr(Config, "API_AUTH_REQUIRED", auth_required)
    integration, _, _, _ = setup_identity
    user = create_user()
    jwt, _ = create_access_token(user)
    _, raw = credential(setup_identity)
    tokens_repo.create_api_token(
        "personal", "personal", hash_token("personal"), ["*"], user_id=user.id
    )
    for header, expected in [(None, 401), (jwt, 403), (raw, 403), ("personal", 401)]:
        headers = {"Authorization": f"Bearer {header}"} if header else {}
        assert client.get(BASE, headers=headers).status_code == expected
        assert (
            client.patch(
                f"{BASE}/{integration.id}",
                json={"expected_revision": 2, "active": False},
                headers=headers,
            ).status_code
            == expected
        )
    assert client.get(BASE, headers=admin_headers).status_code == 200


@pytest.mark.parametrize("auth_required", [True, False])
@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/services", "GET"),
        ("/api/profile/tokens", "POST"),
        ("/api/integrations/alertmanager", "POST"),
        ("/api/change-events", "GET"),
        ("/api/version", "GET"),
        ("/api/change-events/anything", "POST"),
        (BASE, "POST"),
    ],
)
def test_machine_token_cannot_access_other_routes(
    client, setup_identity, monkeypatch, auth_required, path, method
):
    monkeypatch.setattr(Config, "API_AUTH_REQUIRED", auth_required)
    _, raw = credential(setup_identity)
    response = client.open(
        path, method=method, json={}, headers={"Authorization": f"Bearer {raw}"}
    )
    assert response.status_code == 403


def test_intake_route_remains_disabled_by_default(
    app, client, setup_identity, admin_headers, monkeypatch
):
    monkeypatch.setattr(Config, "API_AUTH_REQUIRED", False)
    assert any(rule.rule == "/api/change-events" for rule in app.url_map.iter_rules())
    assert (
        client.post("/api/change-events", json={}, headers=admin_headers).status_code
        == 401
    )
    assert client.post("/api/change-events", json={}).status_code == 401
    _, raw = credential(setup_identity)
    assert (
        client.post(
            "/api/change-events", json={}, headers={"Authorization": f"Bearer {raw}"}
        ).status_code
        == 404
    )


def test_profile_cannot_issue_machine_identity(client, admin_headers, setup_identity):
    integration, _, _, actor = setup_identity
    tokens_repo.create_api_token(
        "wild", "wild", hash_token("wild"), ["*"], user_id=actor.id
    )
    response = client.post(
        "/api/change-events", json={}, headers={"Authorization": "Bearer wild"}
    )
    assert response.status_code == 401
    for extra in [
        {"scopes": ["changes:ingest"]},
        {"change_integration_id": integration.id},
    ]:
        result = client.post(
            "/api/profile/tokens", json={"name": "test", **extra}, headers=admin_headers
        )
        assert result.status_code in {400, 422}
    assert not token_has_scopes(["*"], ["changes:ingest"])
    assert not token_has_scopes(["resources:write"], ["changes:ingest"])
    assert required_scopes_for_path("/api/change-events", "POST") == ["changes:ingest"]
    assert required_scopes_for_path("/api/change-events/1", "POST") is None


def test_credential_hash_only_rotation_and_accepted_authority(
    setup_identity, client, admin_headers
):
    integration, source, service, actor = setup_identity
    grant(setup_identity)
    old, raw = credential(setup_identity)
    version = revision(integration)
    assert old.token_hash == hash_token(raw) and old.token_hash != raw
    assert old.user_id is None and old.group_id is None and old.team_id is None
    fresh, secret = admin.issue_token(
        integration.id,
        MachineTokenCreate(
            expected_revision=version,
            name="rotated",
        ),
        actor_id=actor.id,
        rotate_token_id=old.id,
    )
    assert revision(integration) == version
    assert fresh.change_integration_id == old.change_integration_id
    for candidate, allowed in [(raw, False), (secret, True)]:
        if allowed:
            with authorized_source(
                integration.id, source.owner_team_id, source.source, raw_token=candidate
            ) as (current, _):
                assert (
                    authorize_reference(
                        current,
                        "changed",
                        team_id=service.team_id,
                        service_id=service.id,
                    ).id
                    == service.id
                )
        else:
            with pytest.raises(ChangeAccessDenied):
                with authorized_source(
                    integration.id,
                    source.owner_team_id,
                    source.source,
                    raw_token=candidate,
                ):
                    pytest.fail("Revoked token accepted")
    admin.revoke_token(
        integration.id,
        fresh.id,
        RevisionInput(expected_revision=version),
        actor_id=actor.id,
    )
    with authorized_source(integration.id, source.owner_team_id, source.source) as (
        current,
        seen,
    ):
        assert seen == version and current.id == source.id
    payload = client.get(f"{BASE}/{integration.id}", headers=admin_headers).get_data(
        as_text=True
    )
    audit_text = str([row.data for row in AuditLog.select()])
    for value in (raw, secret, old.token_hash, fresh.token_hash):
        assert value not in payload and value not in audit_text
    assert Change.select().count() == 0 and ChangeEvent.select().count() == 0


@pytest.mark.parametrize("mutation", ["expired", "disabled", "scope", "revoked"])
def test_invalid_machine_credentials_fail_closed(client, setup_identity, mutation):
    token, raw = credential(setup_identity)
    if mutation == "expired":
        token.expires_at = utc_now() - timedelta(seconds=1)
    elif mutation == "disabled":
        ChangeIntegration.update(active=False).where(
            ChangeIntegration.id == token.change_integration_id
        ).execute()
    elif mutation == "scope":
        token.scopes = ["*"]
    else:
        token.active = False
    token.save()
    assert (
        client.post(
            "/api/change-events", headers={"Authorization": f"Bearer {raw}"}
        ).status_code
        == 401
    )


def test_source_namespace_cannot_be_impersonated_or_reassigned(setup_identity):
    integration, source, service, actor = setup_identity
    other = admin.create_integration("Other", actor_id=actor.id)
    for principal, owner, name in [
        (other.id, source.owner_team_id, source.source),
        (integration.id, 999999, source.source),
        (integration.id, source.owner_team_id, "foreign"),
    ]:
        with pytest.raises(ChangeAccessDenied):
            with authorized_source(principal, owner, name):
                pytest.fail("Source impersonation")
    admin.update_source(
        integration.id,
        source.id,
        SourceUpdate(
            expected_revision=revision(integration),
            active=False,
            ordering_mode="sequence",
        ),
        actor_id=actor.id,
    )
    with pytest.raises(admin.ChangeConflict):
        admin.create_source(
            other.id,
            SourceCreate(
                expected_revision=1,
                owner_team_id=source.owner_team_id,
                source=source.source,
            ),
            actor_id=actor.id,
        )
    with pytest.raises(ChangeAccessDenied):
        with authorized_source(integration.id, source.owner_team_id, source.source):
            pytest.fail("Disabled source accepted")


@pytest.mark.parametrize("capability", ["reference", "changed", "reported_affected"])
@pytest.mark.parametrize("service_only", [False, True])
def test_grant_lookup_and_pending_boundaries(setup_identity, capability, service_only):
    integration, source, service, _ = setup_identity
    other = create_service(service.team)
    grant(
        setup_identity,
        capability=capability,
        service=service.id if service_only else None,
    )
    with authorized_source(integration.id, source.owner_team_id, source.source) as (
        current,
        _,
    ):
        assert (
            authorize_reference(
                current, "reference", team_id=service.team_id, service_id=service.id
            ).id
            == service.id
        )
        assert (
            authorize_reference(
                current, "reference", team_id=service.team_id, service_slug=service.slug
            ).id
            == service.id
        )
        if service_only:
            for identity in [
                {"service_id": other.id},
                {"service_slug": "future"},
                {"service_id": 999999},
            ]:
                with pytest.raises(ChangeAccessDenied, match="Change access denied"):
                    authorize_reference(
                        current, "reference", team_id=service.team_id, **identity
                    )
        else:
            assert (
                authorize_reference(
                    current, "reference", team_id=service.team_id, service_slug="future"
                )
                is None
            )
        for claim in ["changed", "reported_affected"]:
            if claim != capability:
                with pytest.raises(ChangeAccessDenied):
                    authorize_reference(
                        current, claim, team_id=service.team_id, service_id=service.id
                    )


def test_ungranted_deleted_and_unknown_ids_have_identical_denial(setup_identity):
    integration, source, own_service, _ = setup_identity
    foreign = create_service(create_team(create_group()))
    deleted = create_service(foreign.team)
    deleted.deleted = True
    deleted.save()
    with authorized_source(integration.id, source.owner_team_id, source.source) as (
        current,
        _,
    ):
        messages = []
        for value in [own_service.id, foreign.id, deleted.id, 999999]:
            with pytest.raises(ChangeAccessDenied) as error:
                authorize_reference(
                    current, "reference", team_id=foreign.team_id, service_id=value
                )
            messages.append(str(error.value))
        assert len(set(messages)) == 1


@pytest.mark.parametrize(
    "operation",
    [
        "move",
        "disable_service",
        "delete_service",
        "disable_team",
        "delete_team",
        "disable_group",
        "delete_group",
    ],
)
def test_catalog_changes_invalidate_authority_atomically(setup_identity, operation):
    integration, source, service, actor = setup_identity
    grant(setup_identity, service=service.id)
    before = revision(integration)
    if operation == "move":
        services_repo.update_service(
            service.id, {"team": create_team(create_group()).id}
        )
    elif operation == "disable_service":
        services_repo.update_service(service.id, {"enabled": False})
    elif operation == "delete_service":
        services_repo.soft_delete_service(service.id)
    elif operation == "disable_team":
        teams_repo.update_team(service.team_id, {"active": False})
    elif operation == "delete_team":
        teams_repo.soft_delete_team(service.team_id)
    elif operation == "disable_group":
        groups_repo.update_group(service.group_id, {"active": False})
    else:
        groups_repo.soft_delete_group(service.group_id)
    assert revision(integration) > before
    job = ChangeJob.get(
        ChangeJob.job_type == "discover_auth", ChangeJob.entity_id == integration.id
    )
    assert job.target_revision == revision(integration)
    with pytest.raises(ChangeAccessDenied):
        with authorized_source(integration.id, source.owner_team_id, source.source) as (
            current,
            _,
        ):
            authorize_reference(
                current, "changed", team_id=service.team_id, service_id=service.id
            )


@pytest.mark.parametrize("failure", ["audit", "job"])
def test_failed_permission_edit_rolls_back_revision_and_grant(
    setup_identity, monkeypatch, failure
):
    integration, _, _, _ = setup_identity
    before = revision(integration)

    def fail(*args, **kwargs):
        raise RuntimeError("injected")

    monkeypatch.setattr(
        admin if failure == "audit" else admin.changes_repo,
        "record_audit" if failure == "audit" else "request_job",
        fail,
    )
    with pytest.raises(RuntimeError, match="injected"):
        grant(setup_identity)
    assert ChangeGrant.select().count() == 0
    assert revision(integration) == before


def test_failed_catalog_invalidation_rolls_back_service(setup_identity, monkeypatch):
    integration, _, service, _ = setup_identity
    grant(setup_identity)
    before = revision(integration)

    def fail(*args, **kwargs):
        raise RuntimeError("injected")

    monkeypatch.setattr(admin.changes_repo, "request_job", fail)
    with pytest.raises(RuntimeError, match="injected"):
        services_repo.update_service(service.id, {"enabled": False})
    assert Service.get_by_id(service.id).enabled
    assert revision(integration) == before


def test_rotation_failure_retains_old_credential(setup_identity, monkeypatch):
    integration, _, _, actor = setup_identity
    token, _ = credential(setup_identity)

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(admin, "record_audit", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        admin.issue_token(
            integration.id,
            MachineTokenCreate(expected_revision=revision(integration), name="new"),
            actor_id=actor.id,
            rotate_token_id=token.id,
        )
    assert ApiToken.select().count() == 1
    assert ApiToken.get_by_id(token.id).active


def test_token_usage_does_not_resurrect_revoked_token(setup_identity):
    token, _ = credential(setup_identity)
    tokens_repo.soft_delete_token(token.id)
    tokens_repo.mark_token_used(token)
    stored = ApiToken.get_by_id(token.id)
    assert stored.deleted and not stored.active


def test_admin_api_validates_ownership_and_stale_edits(
    client, admin_headers, setup_identity
):
    integration, source, service, _ = setup_identity
    url = f"{BASE}/{integration.id}"
    for field in [
        {"user_id": 1},
        {"scopes": ["*"]},
        {"change_integration_id": integration.id},
    ]:
        response = client.post(
            url + "/tokens",
            json={"expected_revision": revision(integration), "name": "test", **field},
            headers=admin_headers,
        )
        assert response.status_code == 400
    response = client.patch(
        url, json={"expected_revision": 1, "active": False}, headers=admin_headers
    )
    assert response.status_code == 409
    assert ChangeIntegration.get_by_id(integration.id).active
    response = client.patch(
        url + f"/sources/{source.id}",
        json={
            "expected_revision": 2,
            "integration_id": integration.id,
            "active": True,
            "ordering_mode": "timestamp",
        },
        headers=admin_headers,
    )
    assert response.status_code == 400
    response = client.post(
        url + "/tokens",
        json={"expected_revision": 2, "name": "new"},
        headers=admin_headers,
    )
    assert (
        response.status_code == 201 and response.headers["Cache-Control"] == "no-store"
    )
    assert "token_hash" not in str(response.get_json())


def test_admin_api_provisions_and_revokes_complete_configuration(
    client, admin_headers, db
):
    team = create_team(create_group())
    service = create_service(team)
    result = client.post(
        BASE,
        headers=admin_headers,
        json={"name": "Deployment CI", "owner_team_id": team.id},
    )
    assert result.status_code == 201
    integration = result.json
    url = f"{BASE}/{integration['id']}"
    assert len(integration["sources"]) == 1
    source_id = integration["sources"][0]["id"]
    result = client.patch(
        url + f"/sources/{source_id}",
        headers=admin_headers,
        json={
            "expected_revision": 1,
            "owner_team_id": team.id,
            "source": "deployment",
            "ordering_mode": "sequence",
        },
    )
    assert result.status_code == 200
    source = result.json["sources"][0]
    grant_url = url + f"/sources/{source['id']}/grants"
    result = client.post(
        grant_url,
        headers=admin_headers,
        json={
            "expected_revision": 2,
            "capability": "changed",
            "target_team_id": team.id,
            "target_service_id": service.id,
        },
    )
    assert result.status_code == 201
    permission = result.json["sources"][0]["grants"][0]
    result = client.patch(
        grant_url + f"/{permission['id']}",
        headers=admin_headers,
        json={"expected_revision": 3, "active": False},
    )
    assert result.status_code == 200 and result.json["auth_revision"] == 4
    result = client.get(BASE + f"/targets?team_id={team.id}", headers=admin_headers)
    assert result.status_code == 200 and result.json["services"][0]["id"] == service.id
    assert (
        client.get("/admin/change-integrations", headers=admin_headers).status_code
        == 200
    )
    assert (
        AuditLog.select()
        .where(AuditLog.action.startswith("change_integration."))
        .count()
        == 5
    )


@pytest.mark.parametrize("days", [0, -1, 3651, True, 1.5, "30", None])
def test_machine_token_lifetime_is_strict(client, admin_headers, setup_identity, days):
    integration, _, _, _ = setup_identity
    response = client.post(
        f"{BASE}/{integration.id}/tokens",
        headers=admin_headers,
        json={"name": "bad", "expected_revision": revision(integration), "days": days},
    )
    assert response.status_code == 400
    assert ApiToken.select().count() == 0


def test_reference_authority_is_rechecked_after_grant_revocation(setup_identity):
    integration, source, service, actor = setup_identity
    permission = grant(setup_identity)
    admin.update_grant(
        integration.id,
        source.id,
        permission.id,
        GrantUpdate(
            expected_revision=revision(integration),
            active=False,
        ),
        actor_id=actor.id,
    )
    with authorized_source(integration.id, source.owner_team_id, source.source) as (
        current,
        _,
    ):
        with pytest.raises(ChangeAccessDenied):
            authorize_reference(
                current, "changed", team_id=service.team_id, service_slug=service.slug
            )


def test_machine_secret_cannot_fall_back_to_admin_cookie(client, setup_identity):
    integration, _, _, actor = setup_identity
    jwt, _ = create_access_token(actor)
    client.set_cookie(Config.JWT_COOKIE_NAME, jwt)
    token, raw = credential(setup_identity)
    for revoked in [False, True]:
        if revoked:
            tokens_repo.soft_delete_token(token.id)
        response = client.get(BASE, headers={"Authorization": f"Bearer {raw}"})
        assert response.status_code == 403


def test_team_rename_keeps_pinned_namespace_and_service_restore_invalidates(
    setup_identity,
):
    integration, source, service, actor = setup_identity
    grant(setup_identity)
    teams_repo.update_team(service.team_id, {"slug": "renamed-owner"})
    with authorized_source(integration.id, source.owner_team_id, source.source) as (
        current,
        _,
    ):
        assert (
            authorize_reference(
                current, "reference", team_id=service.team_id, service_slug="future"
            )
            is None
        )
    services_repo.soft_delete_service(service.id)
    before = revision(integration)
    services_repo.restore_service(service.id, {"enabled": True})
    assert revision(integration) > before
    with authorized_source(integration.id, source.owner_team_id, source.source) as (
        current,
        _,
    ):
        assert (
            authorize_reference(
                current, "changed", team_id=service.team_id, service_id=service.id
            ).id
            == service.id
        )


def test_openapi_covers_administration_and_marks_intake_experimental(app):
    from app.api.openapi.spec import build_openapi_spec

    spec = build_openapi_spec()
    assert "disabled by default" in (
        spec["paths"]["/api/change-events"]["post"]["description"].lower()
    )
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith(BASE):
            continue
        path = rule.rule
        for key in ["integration_id", "source_id", "grant_id", "token_id", "job_id"]:
            path = path.replace(f"<int:{key}>", "{" + key + "}")
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            assert method.lower() in spec["paths"][path]


def test_rotation_preserves_previously_accepted_event_identity(setup_identity):
    integration, source, service, actor = setup_identity
    old, _ = credential(setup_identity)
    change = Change.create(
        source=source,
        integration=integration,
        owner_team=source.owner_team_id,
        external_change_id="accepted",
        kind="deployment",
        title="Already accepted",
    )
    event = ChangeEvent.create(
        change=change,
        source=source,
        integration=integration,
        external_event_id="accepted-start",
        event_type="change.started",
        occurred_at=utc_now(),
        request_digest="a" * 64,
        ingest_token=old,
    )
    before = dict(ChangeEvent.get_by_id(event.id).__data__)
    admin.issue_token(
        integration.id,
        MachineTokenCreate(expected_revision=revision(integration), name="replacement"),
        actor_id=actor.id,
        rotate_token_id=old.id,
    )
    assert ChangeEvent.get_by_id(event.id).__data__ == before
    assert Change.get_by_id(change.id).integration_id == integration.id
    with authorized_source(integration.id, source.owner_team_id, source.source):
        assert ChangeEvent.get_by_id(event.id).ingest_token_id == old.id
