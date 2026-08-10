from app.modules.sso.saml_security import get_saml_security
from app.services.serializers.common import serialize_utc_datetime


def serialize_sso_provider(provider):
    """Serialize SSO provider without secrets."""
    return {
        "id": provider.id,
        "slug": provider.slug,
        "label": provider.label,
        "protocol": provider.protocol,
        "enabled": provider.enabled,

        "subject_claim": provider.subject_claim,
        "email_claim": provider.email_claim,
        "username_claim": provider.username_claim,
        "display_name_claim": provider.display_name_claim,
        "groups_claim": provider.groups_claim,
        "phone_claim": provider.phone_claim,

        "allowed_domains": provider.allowed_domains or [],

        "auto_create_users": provider.auto_create_users,
        "auto_link_by_email": provider.auto_link_by_email,
        "require_verified_email": provider.require_verified_email,

        "sync_group_memberships": provider.sync_group_memberships,
        "remove_missing_group_memberships": provider.remove_missing_group_memberships,

        "client_id": provider.client_id,
        "has_client_secret": bool(provider.client_secret_encrypted),

        "oidc_metadata_url": provider.oidc_metadata_url,
        "oidc_issuer": provider.oidc_issuer,
        "oidc_authorization_endpoint": provider.oidc_authorization_endpoint,
        "oidc_token_endpoint": provider.oidc_token_endpoint,
        "oidc_userinfo_endpoint": provider.oidc_userinfo_endpoint,
        "oidc_jwks_uri": provider.oidc_jwks_uri,
        "oidc_scope": provider.oidc_scope,

        "saml_idp_entity_id": provider.saml_idp_entity_id,
        "saml_idp_sso_url": provider.saml_idp_sso_url,
        "saml_idp_slo_url": provider.saml_idp_slo_url,
        "saml_idp_x509_cert": provider.saml_idp_x509_cert,
        "saml_idp_metadata_url": provider.saml_idp_metadata_url,

        "saml_sp_entity_id": provider.saml_sp_entity_id,
        "saml_sp_acs_url": provider.saml_sp_acs_url,
        "saml_sp_sls_url": provider.saml_sp_sls_url,
        "saml_sp_x509_cert": provider.saml_sp_x509_cert,
        "has_saml_sp_private_key": bool(provider.saml_sp_private_key_encrypted),
        "saml_name_id_format": provider.saml_name_id_format,

        "extra_config": provider.extra_config or {},
        "saml_security": get_saml_security(provider.extra_config),

        "created_at": serialize_utc_datetime(provider.created_at),
        "updated_at": serialize_utc_datetime(provider.updated_at),
    }


def serialize_sso_group_mapping(mapping):
    """Serialize SSO group mapping."""
    group = mapping.incidentrelay_group
    team = mapping.incidentrelay_team if mapping.incidentrelay_team_id else None

    return {
        "id": mapping.id,
        "provider_id": mapping.provider.id,
        "external_group": mapping.external_group,
        "group_id": group.id,
        "group_slug": group.slug,
        "group_name": group.name,
        "group_role": mapping.group_role,
        "team_id": team.id if team else None,
        "team_slug": team.slug if team else None,
        "team_name": team.name if team else None,
        "team_role": mapping.team_role if team else None,
        "active": mapping.active,
        "priority": mapping.priority,
        "created_at": serialize_utc_datetime(mapping.created_at),
        "updated_at": serialize_utc_datetime(mapping.updated_at),
    }
