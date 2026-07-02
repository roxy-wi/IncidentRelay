from pydantic import Field, field_validator, model_validator

from app.api.schemas.base import ApiModel
from app.api.schemas.roles import (
    GROUP_VIEWER_ROLE,
    GROUP_EDITOR_ROLE,
    GROUP_USER_ADMIN_ROLE,
    SSO_GLOBAL_ADMIN_ROLE,
    TEAM_ROLE_VALUES,
    TEAM_VIEWER_ROLE,
)
from app.modules.sso.saml_security import SsoExtraConfig

SSO_MAPPING_ROLES = {
    GROUP_VIEWER_ROLE,
    GROUP_EDITOR_ROLE,
    GROUP_USER_ADMIN_ROLE,
    SSO_GLOBAL_ADMIN_ROLE,
}

SSO_PROTOCOL_PATTERN = r"^(oidc|saml)$"


class SsoProviderBaseSchema(ApiModel):
    """Base SSO provider payload."""

    slug: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    label: str = Field(min_length=2, max_length=128)
    protocol: str = Field(default="oidc", pattern=SSO_PROTOCOL_PATTERN)
    enabled: bool = True

    subject_claim: str = Field(default="sub", min_length=1, max_length=128)
    email_claim: str = Field(default="email", min_length=1, max_length=128)
    username_claim: str = Field(default="preferred_username", min_length=1, max_length=128)
    display_name_claim: str = Field(default="name", min_length=1, max_length=128)
    groups_claim: str = Field(default="groups", min_length=1, max_length=128)
    phone_claim: str = Field(default="mobile", min_length=1, max_length=20)

    allowed_domains: list[str] | None = None

    auto_create_users: bool = False
    auto_link_by_email: bool = True
    require_verified_email: bool = True

    sync_group_memberships: bool = True
    remove_missing_group_memberships: bool = False

    # OIDC
    client_id: str | None = Field(default=None, max_length=512)
    client_secret: str | None = Field(default=None, max_length=4096)
    oidc_metadata_url: str | None = Field(default=None, max_length=2048)
    oidc_issuer: str | None = Field(default=None, max_length=2048)
    oidc_authorization_endpoint: str | None = Field(default=None, max_length=2048)
    oidc_token_endpoint: str | None = Field(default=None, max_length=2048)
    oidc_userinfo_endpoint: str | None = Field(default=None, max_length=2048)
    oidc_jwks_uri: str | None = Field(default=None, max_length=2048)
    oidc_scope: str = Field(default="openid email profile", max_length=512)

    # SAML IdP
    saml_idp_entity_id: str | None = Field(default=None, max_length=2048)
    saml_idp_sso_url: str | None = Field(default=None, max_length=2048)
    saml_idp_slo_url: str | None = Field(default=None, max_length=2048)
    saml_idp_x509_cert: str | None = None
    saml_idp_metadata_url: str | None = Field(default=None, max_length=2048)

    # SAML SP
    saml_sp_entity_id: str | None = Field(default=None, max_length=2048)
    saml_sp_acs_url: str | None = Field(default=None, max_length=2048)
    saml_sp_sls_url: str | None = Field(default=None, max_length=2048)
    saml_sp_x509_cert: str | None = None
    saml_sp_private_key: str | None = None
    saml_name_id_format: str = Field(
        default="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        max_length=512,
    )

    extra_config: SsoExtraConfig | None = None

    @field_validator("allowed_domains")
    @classmethod
    def normalize_allowed_domains(cls, value):
        if value is None:
            return None

        result = []
        for item in value:
            domain = str(item).strip().lower()
            if domain:
                result.append(domain)

        return result or None


class SsoProviderCreateSchema(SsoProviderBaseSchema):
    """Create SSO provider."""


class SsoProviderUpdateSchema(ApiModel):
    """
    Partial SSO provider update.
    """

    slug: str | None = Field(default=None, min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    label: str | None = Field(default=None, min_length=2, max_length=128)
    protocol: str | None = Field(default=None, pattern=SSO_PROTOCOL_PATTERN)
    enabled: bool | None = None

    subject_claim: str | None = Field(default=None, min_length=1, max_length=128)
    email_claim: str | None = Field(default=None, min_length=1, max_length=128)
    username_claim: str | None = Field(default=None, min_length=1, max_length=128)
    display_name_claim: str | None = Field(default=None, min_length=1, max_length=128)
    groups_claim: str | None = Field(default=None, min_length=1, max_length=128)
    phone_claim: str | None = Field(default=None, min_length=1, max_length=20)

    allowed_domains: list[str] | None = None

    auto_create_users: bool | None = None
    auto_link_by_email: bool | None = None
    require_verified_email: bool | None = None
    sync_group_memberships: bool | None = None
    remove_missing_group_memberships: bool | None = None

    # OIDC
    client_id: str | None = Field(default=None, max_length=512)
    client_secret: str | None = Field(default=None, max_length=4096)
    oidc_metadata_url: str | None = Field(default=None, max_length=2048)
    oidc_issuer: str | None = Field(default=None, max_length=2048)
    oidc_authorization_endpoint: str | None = Field(default=None, max_length=2048)
    oidc_token_endpoint: str | None = Field(default=None, max_length=2048)
    oidc_userinfo_endpoint: str | None = Field(default=None, max_length=2048)
    oidc_jwks_uri: str | None = Field(default=None, max_length=2048)
    oidc_scope: str | None = Field(default=None, max_length=512)

    # SAML IdP
    saml_idp_entity_id: str | None = Field(default=None, max_length=2048)
    saml_idp_sso_url: str | None = Field(default=None, max_length=2048)
    saml_idp_slo_url: str | None = Field(default=None, max_length=2048)
    saml_idp_x509_cert: str | None = None
    saml_idp_metadata_url: str | None = Field(default=None, max_length=2048)

    # SAML SP
    saml_sp_entity_id: str | None = Field(default=None, max_length=2048)
    saml_sp_acs_url: str | None = Field(default=None, max_length=2048)
    saml_sp_sls_url: str | None = Field(default=None, max_length=2048)
    saml_sp_x509_cert: str | None = None
    saml_sp_private_key: str | None = None
    saml_name_id_format: str | None = Field(default=None, max_length=512)

    extra_config: SsoExtraConfig | None = None

    @field_validator("allowed_domains")
    @classmethod
    def normalize_allowed_domains(cls, value):
        if value is None:
            return None

        result = []
        for item in value:
            domain = str(item).strip().lower()
            if domain:
                result.append(domain)

        return result or None


class SsoGroupMappingCreateSchema(ApiModel):
    """Create SSO group mapping."""

    external_group: str = Field(min_length=1, max_length=100)
    group_id: int = Field(ge=1)
    group_role: str = Field(default=GROUP_VIEWER_ROLE, max_length=32)
    team_id: int | None = Field(default=None, ge=1)
    team_role: str | None = Field(default=TEAM_VIEWER_ROLE, max_length=32)
    active: bool = True
    priority: int = Field(default=100, ge=0, le=10000)

    @model_validator(mode="after")
    def validate_mapping(self):
        """
        Validate SSO group mapping.
        """
        if self.group_role not in SSO_MAPPING_ROLES:
            raise ValueError("group_role must be viewer, editor, user_admin or global_admin")

        if not self.group_id:
            raise ValueError("incidentrelay_group_id is required")

        if self.team_id and (self.team_role or TEAM_VIEWER_ROLE) not in TEAM_ROLE_VALUES:
            raise ValueError("team_role must be viewer, responder or manager")

        if not self.team_id:
            self.team_role = None
        elif not self.team_role:
            self.team_role = TEAM_VIEWER_ROLE

        return self


class SsoGroupMappingUpdateSchema(SsoGroupMappingCreateSchema):
    """Update SSO group mapping."""


class SsoSamlMetadataParseRequest(ApiModel):
    metadata_url: str = Field(min_length=1, max_length=2048)


class SsoSamlMetadataParseResponse(ApiModel):
    metadata_url: str
    saml_idp_entity_id: str | None = None
    saml_idp_sso_url: str | None = None
    saml_idp_slo_url: str | None = None
    saml_idp_x509_cert: str | None = None
