from datetime import datetime

from app.modules.db.models import Group, SsoGroupMapping, SsoIdentity, SsoProvider, Team
from app.modules.sso.crypto import encrypt_secret
from app.modules.sso.saml_security import normalize_sso_extra_config
from app.modules.common import utc_now


PROVIDER_FIELDS = [
    "slug",
    "label",
    "protocol",
    "enabled",
    "subject_claim",
    "email_claim",
    "username_claim",
    "display_name_claim",
    "groups_claim",
    "phone_claim",
    "allowed_domains",
    "auto_create_users",
    "auto_link_by_email",
    "require_verified_email",
    "sync_group_memberships",
    "remove_missing_group_memberships",
    "client_id",
    "oidc_metadata_url",
    "oidc_issuer",
    "oidc_authorization_endpoint",
    "oidc_token_endpoint",
    "oidc_userinfo_endpoint",
    "oidc_jwks_uri",
    "oidc_scope",
    "saml_idp_entity_id",
    "saml_idp_sso_url",
    "saml_idp_slo_url",
    "saml_idp_x509_cert",
    "saml_idp_metadata_url",
    "saml_sp_entity_id",
    "saml_sp_acs_url",
    "saml_sp_sls_url",
    "saml_sp_x509_cert",
    "saml_name_id_format",
    "extra_config",
]


def list_providers(include_disabled=True, include_deleted=False):
    """Return SSO providers ordered by id."""
    query = SsoProvider.select().order_by(SsoProvider.id.asc())

    if not include_deleted:
        query = query.where(SsoProvider.deleted == False)

    if not include_disabled:
        query = query.where(SsoProvider.enabled == True)

    return list(query)


def get_provider(provider_id, include_deleted=False):
    """Return one SSO provider by id."""
    query = SsoProvider.select().where(SsoProvider.id == provider_id)

    if not include_deleted:
        query = query.where(SsoProvider.deleted == False)

    return query.get()


def get_provider_by_slug(slug, enabled_only=False):
    """Return one SSO provider by slug."""
    query = SsoProvider.select().where(
        (SsoProvider.slug == slug)
        & (SsoProvider.deleted == False)
    )

    if enabled_only:
        query = query.where(SsoProvider.enabled == True)

    return query.get_or_none()


def _apply_provider_data(provider, data, update_secret=True):
    """Apply safe provider fields and encrypt secrets."""
    data = dict(data)

    if "extra_config" in data:
        data["extra_config"] = normalize_sso_extra_config(data.get("extra_config"))

    for field in PROVIDER_FIELDS:
        if field in data:
            setattr(provider, field, data[field])

    if update_secret and "client_secret" in data:
        secret = data.get("client_secret")
        if secret is not None:
            provider.client_secret_encrypted = encrypt_secret(secret)

    if update_secret and "saml_sp_private_key" in data:
        private_key = data.get("saml_sp_private_key")
        if private_key is not None:
            provider.saml_sp_private_key_encrypted = encrypt_secret(private_key)

    provider.updated_at = utc_now()
    return provider


def _find_provider_by_slug(slug: str, exclude_id: int | None = None) -> SsoProvider | None:
    """
    Find active SSO provider by slug.

    exclude_id is used during updates so the provider does not conflict with itself.
    """
    query = SsoProvider.select().where(
        (SsoProvider.slug == slug)
        & (SsoProvider.deleted == False)
    )

    if exclude_id is not None:
        query = query.where(SsoProvider.id != exclude_id)

    return query.first()


def create_provider(data):
    """Create an SSO provider."""
    existing_provider = _find_provider_by_slug(data["slug"])

    if existing_provider:
        raise ValueError("SSO provider with this slug already exists")

    provider = SsoProvider()
    _apply_provider_data(provider, data, update_secret=True)
    provider.save(force_insert=True)
    return provider


def update_provider(provider_id: int, data: dict) -> SsoProvider:
    """
    Update SSO provider.
    """
    provider = get_provider(provider_id)

    if not provider:
        raise ValueError("SSO provider was not found")

    if "slug" in data:
        existing_provider = _find_provider_by_slug(
            data["slug"],
            exclude_id=provider.id,
        )

        if existing_provider:
            raise ValueError("SSO provider with this slug already exists")

    _apply_provider_data(provider, data)
    provider.save()

    return provider


def soft_delete_provider(provider_id):
    """Soft-delete SSO provider and disable it."""
    provider = get_provider(provider_id)
    now = utc_now()

    database = SsoProvider._meta.database
    with database.atomic():
        provider.enabled = False
        provider.deleted = True
        provider.deleted_at = now
        provider.updated_at = now
        provider.save()

        SsoGroupMapping.update(active=False).where(
            SsoGroupMapping.provider == provider.id
        ).execute()

    return provider


def list_group_mappings(provider_id):
    """Return group mappings for one provider."""
    return list(
        SsoGroupMapping
        .select(SsoGroupMapping, SsoProvider, Group)
        .join(SsoProvider)
        .switch(SsoGroupMapping)
        .join(Group)
        .where(SsoGroupMapping.provider == provider_id)
        .order_by(SsoGroupMapping.priority.asc(), SsoGroupMapping.id.asc())
    )


def get_group_mapping(mapping_id):
    """Return one group mapping."""
    return SsoGroupMapping.get_by_id(mapping_id)


def _validate_group_mapping_team(data):
    """Validate that optional SSO team mapping belongs to the selected group."""
    team_id = data.get("team_id")

    if not team_id:
        return None

    team = Team.get_by_id(team_id)

    if int(team.group_id) != int(data["group_id"]):
        raise ValueError("team_id must belong to the selected IncidentRelay group")

    return team


def create_group_mapping(provider_id, data):
    """Create SSO group mapping."""
    team = _validate_group_mapping_team(data)

    return SsoGroupMapping.create(
        provider=provider_id,
        external_group=data["external_group"],
        incidentrelay_group=data["group_id"],
        group_role=data["group_role"],
        incidentrelay_team=team.id if team else None,
        team_role=data.get("team_role") if team else None,
        active=data.get("active", True),
        priority=data.get("priority", 100),
    )


def update_group_mapping(mapping_id, data):
    """Update SSO group mapping."""
    mapping = get_group_mapping(mapping_id)
    team = _validate_group_mapping_team(data)

    mapping.external_group = data["external_group"]
    mapping.incidentrelay_group = data["group_id"]
    mapping.group_role = data["group_role"]
    mapping.incidentrelay_team = team.id if team else None
    mapping.team_role = data.get("team_role") if team else None
    mapping.active = data.get("active", True)
    mapping.priority = data.get("priority", 100)
    mapping.updated_at = utc_now()
    mapping.save()

    return mapping


def delete_group_mapping(mapping_id):
    """Delete SSO group mapping."""
    mapping = get_group_mapping(mapping_id)
    mapping.delete_instance()
    return mapping


def find_identity(provider_id, subject):
    """Find linked SSO identity."""
    return SsoIdentity.get_or_none(
        (SsoIdentity.provider == provider_id)
        & (SsoIdentity.subject == subject)
    )


def find_identity_by_email(provider_id, email):
    """Find linked SSO identity by provider and email."""
    if not email:
        return None

    return SsoIdentity.get_or_none(
        (SsoIdentity.provider == provider_id)
        & (SsoIdentity.email == email)
    )


def create_identity(provider_id, user_id, subject, email=None, username=None, raw_claims=None):
    """Link external SSO identity to local user."""
    return SsoIdentity.create(
        provider=provider_id,
        user=user_id,
        subject=subject,
        email=email,
        username=username,
        raw_claims=raw_claims,
        last_login_at=utc_now(),
    )


def touch_identity(identity, email=None, username=None, raw_claims=None):
    """Update identity metadata after successful login."""
    identity.email = email
    identity.username = username
    identity.raw_claims = raw_claims
    identity.last_login_at = utc_now()
    identity.save()
    return identity
