import time

import pytest
from authlib.jose import JsonWebKey, JsonWebToken
from pydantic import ValidationError

from app.api.schemas.sso import (
    SsoGroupMappingCreateSchema,
    SsoProviderCreateSchema,
)
from app.modules.db.models import (
    SsoGroupMapping,
    SsoIdentity,
    SsoProvider,
    User,
    UserGroup,
)
from app.modules.sso.crypto import decrypt_secret
from app.modules.sso.sso_login import (
    SsoLoginError,
    complete_sso_login,
)
from app.views.sso_admin_view import (
    create_group_mapping,
    create_provider,
    delete_provider,
    list_group_mappings,
    list_providers,
    update_group_mapping,
    update_provider,
)
from app.views.sso_auth_view import (
    _load_json_url,
    _merge_oidc_claims,
    _validate_oidc_id_token,
    public_sso_providers,
)
from tests.factories import create_group, create_team, create_user, unique
from app.api.schemas.limits import normalize_phone


def make_admin():
    return create_user(username=unique("admin"), is_admin=True)


def make_oidc_provider(**overrides):
    data = {
        "slug": unique("oidc"),
        "label": "Test OIDC",
        "protocol": "oidc",
        "enabled": True,
        "client_id": "incidentrelay",
        "client_secret_encrypted": None,
        "oidc_metadata_url": "https://idp.example.com/.well-known/openid-configuration",
        "oidc_issuer": "https://idp.example.com",
        "oidc_jwks_uri": "https://idp.example.com/jwks",
        "oidc_scope": "openid email profile",
        "subject_claim": "sub",
        "email_claim": "email",
        "username_claim": "preferred_username",
        "display_name_claim": "name",
        "groups_claim": "groups",
        "auto_create_users": False,
        "auto_link_by_email": True,
        "require_verified_email": True,
        "sync_group_memberships": True,
        "remove_missing_group_memberships": False,
    }
    data.update(overrides)
    return SsoProvider.create(**data)


def make_saml_provider(**overrides):
    data = {
        "slug": unique("saml"),
        "label": "Test SAML",
        "protocol": "saml",
        "enabled": True,
        "subject_claim": "NameID",
        "email_claim": "email",
        "username_claim": "uid",
        "display_name_claim": "displayName",
        "groups_claim": "groups",
        "saml_idp_entity_id": "https://idp.example.com/metadata",
        "saml_idp_sso_url": "https://idp.example.com/sso",
        "saml_idp_x509_cert": "-----BEGIN CERTIFICATE-----test-----END CERTIFICATE-----",
    }
    data.update(overrides)
    return SsoProvider.create(**data)


def provider_payload(**overrides):
    data = {
        "slug": unique("keycloak"),
        "label": "Keycloak",
        "protocol": "oidc",
        "enabled": True,
        "subject_claim": "sub",
        "email_claim": "email",
        "username_claim": "preferred_username",
        "display_name_claim": "name",
        "groups_claim": "groups",
        "allowed_domains": ["example.com"],
        "auto_create_users": True,
        "auto_link_by_email": True,
        "require_verified_email": True,
        "sync_group_memberships": True,
        "remove_missing_group_memberships": False,
        "client_id": "incidentrelay",
        "client_secret": "secret-1",
        "oidc_metadata_url": "https://idp.example.com/.well-known/openid-configuration",
        "oidc_scope": "openid email profile",
        "saml_idp_entity_id": None,
        "saml_idp_sso_url": None,
        "saml_idp_slo_url": None,
        "saml_idp_x509_cert": None,
        "saml_sp_entity_id": None,
        "saml_sp_acs_url": None,
        "saml_sp_sls_url": None,
        "saml_sp_x509_cert": None,
        "saml_sp_private_key": None,
        "saml_name_id_format": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        "extra_config": None,
    }
    data.update(overrides)
    return data


def saml_provider_payload(**overrides):
    data = provider_payload(
        slug=unique("saml"),
        label="Corporate SAML",
        protocol="saml",
        subject_claim="NameID",
        email_claim="email",
        username_claim="uid",
        display_name_claim="displayName",
        client_id=None,
        client_secret=None,
        oidc_metadata_url=None,
        saml_idp_entity_id="https://idp.example.com/metadata",
        saml_idp_sso_url="https://idp.example.com/sso",
        saml_idp_x509_cert="-----BEGIN CERTIFICATE-----test-----END CERTIFICATE-----",
    )
    data.update(overrides)
    return data


def test_public_sso_providers_returns_enabled_only(app):
    enabled_provider = make_oidc_provider(slug="enabled-oidc", label="Enabled OIDC")
    make_oidc_provider(slug="disabled-oidc", label="Disabled OIDC", enabled=False)

    with app.test_request_context("/api/auth/sso/providers", method="GET"):
        response = public_sso_providers()

    data = response.get_json()

    assert data == [
        {
            "slug": enabled_provider.slug,
            "label": enabled_provider.label,
            "protocol": "oidc",
            "enabled": True,
        }
    ]


def test_load_json_url_rejects_non_http_scheme():
    with pytest.raises(SsoLoginError) as exc_info:
        _load_json_url(
            "file:///etc/passwd",
            "sso_oidc_metadata_error",
            "Could not load OIDC metadata",
        )

    assert exc_info.value.error == "sso_oidc_metadata_error"
    assert exc_info.value.message == "Could not load OIDC metadata"
    assert exc_info.value.status_code == 502


def test_admin_can_create_oidc_provider(app):
    admin = make_admin()

    with app.test_request_context(
        "/api/admin/sso/providers",
        method="POST",
        json=provider_payload(slug="keycloak"),
    ):
        from flask import request

        request.current_user = admin
        response, status = create_provider()

    data = response.get_json()
    provider = SsoProvider.get_by_id(data["id"])

    assert status == 201
    assert data["slug"] == "keycloak"
    assert data["protocol"] == "oidc"
    assert data["has_client_secret"] is True
    assert "client_secret" not in data
    assert decrypt_secret(provider.client_secret_encrypted) == "secret-1"


def test_admin_can_create_saml_provider(app):
    admin = make_admin()

    with app.test_request_context(
        "/api/admin/sso/providers",
        method="POST",
        json=saml_provider_payload(slug="corp-saml"),
    ):
        from flask import request

        request.current_user = admin
        response, status = create_provider()

    data = response.get_json()

    assert status == 201
    assert data["slug"] == "corp-saml"
    assert data["protocol"] == "saml"
    assert data["subject_claim"] == "NameID"
    assert data["saml_idp_sso_url"] == "https://idp.example.com/sso"


def test_admin_can_update_sso_provider_without_overwriting_empty_secret(app):
    admin = make_admin()

    with app.test_request_context(
        "/api/admin/sso/providers",
        method="POST",
        json=provider_payload(slug="secret-test", client_secret="first-secret"),
    ):
        from flask import request

        request.current_user = admin
        response, status = create_provider()

    assert status == 201
    provider_id = response.get_json()["id"]

    update_payload = provider_payload(
        slug="secret-test",
        label="Updated Provider",
        client_secret=None,
    )

    with app.test_request_context(
        f"/api/admin/sso/providers/{provider_id}",
        method="PUT",
        json=update_payload,
    ):
        from flask import request

        request.current_user = admin
        response = update_provider(provider_id)

    data = response.get_json()
    provider = SsoProvider.get_by_id(provider_id)

    assert data["label"] == "Updated Provider"
    assert data["has_client_secret"] is True
    assert decrypt_secret(provider.client_secret_encrypted) == "first-secret"


def test_admin_can_create_sso_group_mapping(app):
    admin = make_admin()
    provider = make_oidc_provider(slug="mapping-provider")
    group = create_group(slug="infra", name="Infrastructure")

    with app.test_request_context(
        f"/api/admin/sso/providers/{provider.id}/mappings",
        method="POST",
        json={
            "external_group": "infra-sso",
            "group_id": group.id,
            "group_role": "editor",
            "active": True,
            "priority": 10,
        },
    ):
        from flask import request

        request.current_user = admin
        response, status = create_group_mapping(provider.id)

    data = response.get_json()
    mapping = SsoGroupMapping.get_by_id(data["id"])

    assert status == 201
    assert data["external_group"] == "infra-sso"
    assert data["group_slug"] == "infra"
    assert data["group_role"] == "editor"
    assert mapping.incidentrelay_group.id == group.id


def test_admin_can_list_sso_group_mappings(app):
    admin = make_admin()
    provider = make_oidc_provider(slug="list-mappings-provider")
    group = create_group(slug="noc", name="NOC")

    SsoGroupMapping.create(
        provider=provider,
        external_group="noc-sso",
        incidentrelay_group=group,
        group_role="viewer",
        active=True,
        priority=100,
    )

    with app.test_request_context(
        f"/api/admin/sso/providers/{provider.id}/mappings",
        method="GET",
    ):
        from flask import request

        request.current_user = admin
        response = list_group_mappings(provider.id)

    data = response.get_json()

    assert len(data) == 1
    assert data[0]["external_group"] == "noc-sso"
    assert data[0]["group_role"] == "viewer"


def test_admin_can_update_sso_group_mapping(app):
    admin = make_admin()
    provider = make_oidc_provider(slug="update-mapping-provider")
    group = create_group(slug="sre", name="SRE")
    team = create_team(group, slug="sre-oncall", name="SRE On-call")

    mapping = SsoGroupMapping.create(
        provider=provider,
        external_group="sre-sso",
        incidentrelay_group=group,
        group_role="viewer",
        active=True,
        priority=100,
    )

    with app.test_request_context(
        f"/api/admin/sso/mappings/{mapping.id}",
        method="PUT",
        json={
            "external_group": "sre-sso-renamed",
            "group_id": group.id,
            "group_role": "editor",
            "team_id": team.id,
            "team_role": "manager",
            "active": False,
            "priority": 5,
        },
    ):
        from flask import request

        request.current_user = admin
        response = update_group_mapping(mapping.id)

    data = response.get_json()
    mapping = SsoGroupMapping.get_by_id(mapping.id)

    assert data["external_group"] == "sre-sso-renamed"
    assert data["group_role"] == "editor"
    assert data["team_id"] == team.id
    assert data["team_role"] == "manager"
    assert data["active"] is False
    assert data["priority"] == 5
    assert mapping.external_group == "sre-sso-renamed"
    assert mapping.incidentrelay_team.id == team.id
    assert mapping.active is False


def test_admin_can_detach_team_from_sso_group_mapping(app):
    admin = make_admin()
    provider = make_oidc_provider(slug="detach-team-mapping-provider")
    group = create_group(slug="net", name="Network")
    team = create_team(group, slug="net-core", name="Core Network")

    mapping = SsoGroupMapping.create(
        provider=provider,
        external_group="net-sso",
        incidentrelay_group=group,
        group_role="editor",
        incidentrelay_team=team,
        team_role="responder",
        active=True,
        priority=20,
    )

    with app.test_request_context(
        f"/api/admin/sso/mappings/{mapping.id}",
        method="PUT",
        json={
            "external_group": "net-sso",
            "group_id": group.id,
            "group_role": "editor",
            "team_id": None,
            "active": True,
            "priority": 20,
        },
    ):
        from flask import request

        request.current_user = admin
        response = update_group_mapping(mapping.id)

    data = response.get_json()
    mapping = SsoGroupMapping.get_by_id(mapping.id)

    assert data["team_id"] is None
    assert data["team_role"] is None
    assert mapping.incidentrelay_team_id is None
    assert mapping.team_role is None


def test_admin_cannot_map_team_from_another_group(app):
    admin = make_admin()
    provider = make_oidc_provider(slug="foreign-team-mapping-provider")
    group = create_group(slug="dba", name="DBA")
    other_group = create_group(slug="qa", name="QA")
    other_team = create_team(other_group, slug="qa-web", name="QA Web")

    mapping = SsoGroupMapping.create(
        provider=provider,
        external_group="dba-sso",
        incidentrelay_group=group,
        group_role="viewer",
        active=True,
        priority=100,
    )

    with app.test_request_context(
        f"/api/admin/sso/mappings/{mapping.id}",
        method="PUT",
        json={
            "external_group": "dba-sso",
            "group_id": group.id,
            "group_role": "viewer",
            "team_id": other_team.id,
            "team_role": "manager",
            "active": True,
            "priority": 100,
        },
    ):
        from flask import request

        request.current_user = admin
        response, status = update_group_mapping(mapping.id)

    mapping = SsoGroupMapping.get_by_id(mapping.id)

    assert status == 400
    assert response.get_json()["error"] == "validation_error"
    assert mapping.incidentrelay_team_id is None


def test_non_admin_cannot_manage_sso(app):
    user = create_user(is_admin=False)

    with app.test_request_context("/api/admin/sso/providers", method="GET"):
        from flask import request

        request.current_user = user
        response, status = list_providers()

    assert status == 403
    assert response.get_json()["error"] in {
        "admin_required",
        "forbidden",
        "permission_denied",
    }


def test_admin_can_soft_delete_sso_provider_and_disable_mappings(app):
    admin = make_admin()
    provider = make_oidc_provider(slug="delete-provider")
    group = create_group()

    mapping = SsoGroupMapping.create(
        provider=provider,
        external_group="delete-sso",
        incidentrelay_group=group,
        group_role="viewer",
        active=True,
        priority=100,
    )

    with app.test_request_context(
        f"/api/admin/sso/providers/{provider.id}",
        method="DELETE",
    ):
        from flask import request

        request.current_user = admin
        response = delete_provider(provider.id)

    data = response.get_json()

    provider = SsoProvider.get_by_id(provider.id)
    mapping = SsoGroupMapping.get_by_id(mapping.id)

    assert data["deleted"] is True
    assert provider.deleted is True
    assert provider.enabled is False
    assert mapping.active is False


def test_sso_group_mapping_schema_accepts_only_new_group_roles():
    for role in ("viewer", "editor", "user_admin"):
        payload = SsoGroupMappingCreateSchema.model_validate(
            {
                "external_group": f"group-{role}",
                "group_id": 1,
                "group_role": role,
            }
        )
        assert payload.group_role == role

    for old_role in ("read_only", "rw"):
        with pytest.raises(ValidationError):
            SsoGroupMappingCreateSchema.model_validate(
                {
                    "external_group": f"group-{old_role}",
                    "group_id": 1,
                    "group_role": old_role,
                }
            )


def test_sso_provider_schema_rejects_unknown_protocol():
    with pytest.raises(ValidationError):
        SsoProviderCreateSchema.model_validate(
            provider_payload(
                slug="bad-protocol",
                protocol="ldap",
            )
        )


def test_complete_sso_login_auto_creates_user_and_links_identity():
    provider = make_oidc_provider(
        slug="auto-create",
        auto_create_users=True,
        auto_link_by_email=True,
        allowed_domains=["example.com"],
    )

    user = complete_sso_login(
        provider,
        {
            "sub": "sso-user-1",
            "email": "sso-user@example.com",
            "email_verified": True,
            "preferred_username": "sso-user",
            "name": "SSO User",
            "groups": [],
        },
    )

    identity = SsoIdentity.get(
        (SsoIdentity.provider == provider.id)
        & (SsoIdentity.subject == "sso-user-1")
    )

    assert user.username == "sso-user"
    assert user.email == "sso-user@example.com"
    assert user.is_admin is False
    assert user.active is True
    assert identity.user.id == user.id


def test_complete_sso_login_auto_links_existing_user_by_email():
    provider = make_oidc_provider(
        slug="auto-link",
        auto_create_users=False,
        auto_link_by_email=True,
        allowed_domains=["example.com"],
    )
    existing_user = create_user(username="local-user", email="local@example.com")

    user = complete_sso_login(
        provider,
        {
            "sub": "external-subject",
            "email": "local@example.com",
            "email_verified": True,
            "preferred_username": "remote-user",
            "name": "Remote User",
            "groups": [],
        },
    )

    identity = SsoIdentity.get(
        (SsoIdentity.provider == provider.id)
        & (SsoIdentity.subject == "external-subject")
    )

    assert user.id == existing_user.id
    assert identity.user.id == existing_user.id


def test_complete_sso_login_denies_unallowed_email_domain():
    provider = make_oidc_provider(
        slug="domain-check",
        auto_create_users=True,
        allowed_domains=["example.com"],
    )

    with pytest.raises(SsoLoginError) as exc:
        complete_sso_login(
            provider,
            {
                "sub": "bad-domain",
                "email": "user@evil.example",
                "email_verified": True,
                "preferred_username": "bad-domain",
                "name": "Bad Domain",
                "groups": [],
            },
        )

    assert exc.value.error == "sso_domain_denied"


def test_complete_sso_login_syncs_group_mappings():
    provider = make_oidc_provider(
        slug="group-sync",
        auto_create_users=True,
        sync_group_memberships=True,
    )
    infra_group = create_group(slug="infra", name="Infra")
    noc_group = create_group(slug="noc", name="NOC")

    SsoGroupMapping.create(
        provider=provider,
        external_group="infra-sso",
        incidentrelay_group=infra_group,
        group_role="editor",
        active=True,
        priority=10,
    )
    SsoGroupMapping.create(
        provider=provider,
        external_group="noc-sso",
        incidentrelay_group=noc_group,
        group_role="viewer",
        active=True,
        priority=20,
    )

    user = complete_sso_login(
        provider,
        {
            "sub": "group-user",
            "email": "group-user@example.com",
            "email_verified": True,
            "preferred_username": "group-user",
            "name": "Group User",
            "groups": ["infra-sso"],
        },
    )

    memberships = {
        membership.group.id: membership
        for membership in UserGroup.select().where(UserGroup.user == user.id)
    }

    assert infra_group.id in memberships
    assert memberships[infra_group.id].role == "editor"
    assert memberships[infra_group.id].active is True
    assert noc_group.id not in memberships


def test_complete_sso_login_remove_missing_group_memberships_disables_missing_mapping():
    provider = make_oidc_provider(
        slug="strict-group-sync",
        auto_create_users=False,
        auto_link_by_email=True,
        sync_group_memberships=True,
        remove_missing_group_memberships=True,
    )
    infra_group = create_group(slug="infra", name="Infra")
    noc_group = create_group(slug="noc", name="NOC")
    user = create_user(username="strict-user", email="strict@example.com", group=infra_group)

    UserGroup.create(
        user=user,
        group=noc_group,
        role="editor",
        active=True,
    )

    SsoGroupMapping.create(
        provider=provider,
        external_group="infra-sso",
        incidentrelay_group=infra_group,
        group_role="viewer",
        active=True,
        priority=10,
    )
    SsoGroupMapping.create(
        provider=provider,
        external_group="noc-sso",
        incidentrelay_group=noc_group,
        group_role="editor",
        active=True,
        priority=20,
    )

    complete_sso_login(
        provider,
        {
            "sub": "strict-user-sub",
            "email": "strict@example.com",
            "email_verified": True,
            "preferred_username": "strict-user",
            "name": "Strict User",
            "groups": ["infra-sso"],
        },
    )

    infra_membership = UserGroup.get(
        (UserGroup.user == user.id)
        & (UserGroup.group == infra_group.id)
    )
    noc_membership = UserGroup.get(
        (UserGroup.user == user.id)
        & (UserGroup.group == noc_group.id)
    )

    assert infra_membership.active is True
    assert infra_membership.role == "viewer"
    assert noc_membership.active is False


def test_oidc_userinfo_subject_must_match_id_token_subject():
    with pytest.raises(SsoLoginError) as exc:
        _merge_oidc_claims(
            id_token_claims={
                "sub": "subject-from-id-token",
                "email": "user@example.com",
            },
            userinfo_claims={
                "sub": "subject-from-userinfo",
                "name": "User",
            },
        )

    assert exc.value.error == "sso_oidc_subject_mismatch"


def test_validate_oidc_id_token_accepts_signed_token(monkeypatch):
    provider = make_oidc_provider(
        slug="signed-token",
        client_id="incidentrelay",
        oidc_issuer="https://idp.example.com",
        oidc_jwks_uri="https://idp.example.com/jwks",
    )

    key = JsonWebKey.generate_key(
        "RSA",
        2048,
        is_private=True,
        options={"kid": "test-key"},
    )

    public_jwks = {"keys": [key.as_dict(is_private=False)]}

    monkeypatch.setattr(
        "app.views.sso_auth_view._load_oidc_jwks",
        lambda _provider, _metadata: public_jwks,
    )

    now = int(time.time())
    jwt_client = JsonWebToken(["RS256"])
    id_token = jwt_client.encode(
        {"alg": "RS256", "kid": "test-key"},
        {
            "iss": "https://idp.example.com",
            "sub": "oidc-subject",
            "aud": "incidentrelay",
            "exp": now + 300,
            "iat": now,
            "nonce": "expected-nonce",
            "email": "oidc@example.com",
            "email_verified": True,
        },
        key,
    )

    if isinstance(id_token, bytes):
        id_token = id_token.decode("utf-8")

    claims = _validate_oidc_id_token(
        provider=provider,
        metadata={
            "issuer": "https://idp.example.com",
            "jwks_uri": "https://idp.example.com/jwks",
            "id_token_signing_alg_values_supported": ["RS256"],
        },
        token={
            "id_token": id_token,
            "access_token": "access-token",
        },
        expected_nonce="expected-nonce",
    )

    assert claims["sub"] == "oidc-subject"
    assert claims["email"] == "oidc@example.com"


def test_validate_oidc_id_token_rejects_wrong_nonce(monkeypatch):
    provider = make_oidc_provider(
        slug="wrong-nonce",
        client_id="incidentrelay",
        oidc_issuer="https://idp.example.com",
        oidc_jwks_uri="https://idp.example.com/jwks",
    )

    key = JsonWebKey.generate_key(
        "RSA",
        2048,
        is_private=True,
        options={"kid": "test-key"},
    )

    public_jwks = {"keys": [key.as_dict(is_private=False)]}

    monkeypatch.setattr(
        "app.views.sso_auth_view._load_oidc_jwks",
        lambda _provider, _metadata: public_jwks,
    )

    now = int(time.time())
    jwt_client = JsonWebToken(["RS256"])
    id_token = jwt_client.encode(
        {"alg": "RS256", "kid": "test-key"},
        {
            "iss": "https://idp.example.com",
            "sub": "oidc-subject",
            "aud": "incidentrelay",
            "exp": now + 300,
            "iat": now,
            "nonce": "actual-nonce",
        },
        key,
    )

    if isinstance(id_token, bytes):
        id_token = id_token.decode("utf-8")

    with pytest.raises(SsoLoginError) as exc:
        _validate_oidc_id_token(
            provider=provider,
            metadata={
                "issuer": "https://idp.example.com",
                "jwks_uri": "https://idp.example.com/jwks",
                "id_token_signing_alg_values_supported": ["RS256"],
            },
            token={"id_token": id_token},
            expected_nonce="expected-nonce",
        )

    assert exc.value.error == "sso_oidc_id_token_invalid"


def test_validate_phone_accepts_common_formatting():
    assert normalize_phone("+7 (111) 111-11-11") == "+71111111111"
    assert normalize_phone("+7-111-111-11-11") == "+71111111111"
    assert normalize_phone("+7 111 111 11 11") == "+71111111111"
    assert normalize_phone("71111111111") == "71111111111"


def test_validate_phone_rejects_invalid_plus_position():
    try:
        normalize_phone("7+111111111")
    except ValueError as exc:
        assert "phone +" in str(exc)
    else:
        raise AssertionError("ValueError was not raised")


def test_validate_phone_rejects_letters():
    try:
        normalize_phone("+7 phone 111")
    except ValueError as exc:
        assert "phone may contain" in str(exc)
    else:
        raise AssertionError("ValueError was not raised")


def test_complete_sso_login_syncs_group_mapping_case_insensitive_and_sets_active_group():
    provider = make_oidc_provider(
        slug="group-sync-normalized",
        auto_create_users=True,
        sync_group_memberships=True,
    )

    infra_group = create_group(slug="infra-normalized", name="Infra Normalized")

    SsoGroupMapping.create(
        provider=provider,
        external_group="infra-sso",
        incidentrelay_group=infra_group,
        group_role="editor",
        active=True,
        priority=10,
    )

    user = complete_sso_login(
        provider,
        {
            "sub": "group-user-normalized",
            "email": "group-user-normalized@example.com",
            "email_verified": True,
            "preferred_username": "group-user-normalized",
            "name": "Group User Normalized",
            "groups": ["  INFRA-SSO  "],
        },
    )

    membership = UserGroup.get(
        (UserGroup.user == user.id)
        & (UserGroup.group == infra_group.id)
    )

    user = User.get_by_id(user.id)

    assert membership.active is True
    assert membership.role == "editor"
    assert user.active_group_id == infra_group.id


def test_complete_sso_login_denies_user_without_matching_group_mapping():
    provider = make_oidc_provider(
        slug="group-sync-required",
        auto_create_users=True,
        sync_group_memberships=True,
        remove_missing_group_memberships=False,
    )

    infra_group = create_group(slug="infra-required", name="Infra Required")

    SsoGroupMapping.create(
        provider=provider,
        external_group="infra-sso",
        incidentrelay_group=infra_group,
        group_role="viewer",
        active=True,
        priority=10,
    )

    with pytest.raises(SsoLoginError) as exc:
        complete_sso_login(
            provider,
            {
                "sub": "orphan-sso-user",
                "email": "orphan-sso-user@example.com",
                "email_verified": True,
                "preferred_username": "orphan-sso-user",
                "name": "Orphan SSO User",
                "groups": ["unknown-sso-group"],
            },
        )

    assert exc.value.error == "sso_group_mapping_not_matched"

    assert not User.select().where(
        User.username == "orphan-sso-user"
    ).exists()

    assert not SsoIdentity.select().where(
        (SsoIdentity.provider == provider.id)
        & (SsoIdentity.subject == "orphan-sso-user")
    ).exists()


def test_sso_json_loader_does_not_expose_network_exception(monkeypatch):
    from app.services.outbound_http import OutboundHttpError

    import app.views.sso_auth_view as sso_auth_view

    def fail_safe_request(*_args, **_kwargs):
        raise OutboundHttpError("internal-idp-secret-detail")

    monkeypatch.setattr(sso_auth_view, "safe_request", fail_safe_request)

    with pytest.raises(SsoLoginError) as exc_info:
        sso_auth_view._load_json_url(
            "https://idp.example.com/metadata",
            "sso_oidc_metadata_error",
            "Could not load OIDC metadata",
        )

    error = exc_info.value

    assert error.error == "sso_oidc_metadata_error"
    assert error.message == "Could not load OIDC metadata"
    assert error.status_code == 502
    assert "internal-idp-secret-detail" not in str(error)
