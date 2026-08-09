from app.api.openapi.common import json_body, path_param, response
from app.api.schemas.roles import GROUP_ROLE_VALUES, GROUP_VIEWER_ROLE, TEAM_ROLE_VALUES, TEAM_VIEWER_ROLE


def slug_param():
    """Build SSO provider slug path parameter."""
    return {
        "name": "slug",
        "in": "path",
        "required": True,
        "description": "SSO provider slug.",
        "schema": {
            "type": "string",
            "minLength": 2,
            "maxLength": 64,
            "pattern": "^[a-z0-9][a-z0-9_-]*$",
        },
    }


ERROR_SCHEMA = {
    "type": "object",
    "properties": {
        "error": {"type": "string", "example": "validation_error"},
        "message": {"type": "string", "nullable": True},
    },
}


PUBLIC_SSO_PROVIDER_SCHEMA = {
    "type": "object",
    "properties": {
        "slug": {"type": "string", "example": "keycloak"},
        "label": {"type": "string", "example": "Keycloak"},
        "protocol": {"type": "string", "enum": ["oidc", "saml"], "example": "oidc"},
        "enabled": {"type": "boolean", "example": True},
    },
}


SSO_PROVIDER_SCHEMA = {
    "type": "object",
    "required": ["slug", "label", "protocol"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "integer", "readOnly": True, "example": 1},
        "slug": {
            "type": "string",
            "minLength": 2,
            "maxLength": 64,
            "pattern": "^[a-z0-9][a-z0-9_-]*$",
            "example": "keycloak",
        },
        "label": {"type": "string", "minLength": 2, "maxLength": 128, "example": "Keycloak"},
        "protocol": {"type": "string", "enum": ["oidc", "saml"], "default": "oidc"},
        "enabled": {"type": "boolean", "default": True},

        "subject_claim": {"type": "string", "default": "sub", "example": "sub"},
        "email_claim": {"type": "string", "default": "email", "example": "email"},
        "username_claim": {"type": "string", "default": "preferred_username", "example": "preferred_username"},
        "display_name_claim": {"type": "string", "default": "name", "example": "name"},
        "groups_claim": {"type": "string", "default": "groups", "example": "groups"},

        "allowed_domains": {
            "type": "array",
            "nullable": True,
            "items": {"type": "string"},
            "example": ["example.com"],
        },

        "auto_create_users": {"type": "boolean", "default": False},
        "auto_link_by_email": {"type": "boolean", "default": True},
        "require_verified_email": {"type": "boolean", "default": True},
        "sync_group_memberships": {"type": "boolean", "default": True},
        "remove_missing_group_memberships": {"type": "boolean", "default": False},

        "client_id": {"type": "string", "nullable": True, "example": "incidentrelay"},
        "client_secret": {
            "type": "string",
            "nullable": True,
            "writeOnly": True,
            "description": "OIDC client secret. Leave null to keep existing secret on update.",
        },
        "has_client_secret": {"type": "boolean", "readOnly": True},

        "oidc_metadata_url": {
            "type": "string",
            "nullable": True,
            "example": "https://idp.example.com/.well-known/openid-configuration",
        },
        "oidc_issuer": {"type": "string", "nullable": True},
        "oidc_authorization_endpoint": {"type": "string", "nullable": True},
        "oidc_token_endpoint": {"type": "string", "nullable": True},
        "oidc_userinfo_endpoint": {"type": "string", "nullable": True},
        "oidc_jwks_uri": {"type": "string", "nullable": True},
        "oidc_scope": {"type": "string", "default": "openid email profile"},

        "saml_idp_entity_id": {"type": "string", "nullable": True},
        "saml_idp_sso_url": {"type": "string", "nullable": True},
        "saml_idp_slo_url": {"type": "string", "nullable": True},
        "saml_idp_x509_cert": {"type": "string", "nullable": True},

        "saml_sp_entity_id": {"type": "string", "nullable": True},
        "saml_sp_acs_url": {"type": "string", "nullable": True},
        "saml_sp_sls_url": {"type": "string", "nullable": True},
        "saml_sp_x509_cert": {"type": "string", "nullable": True},
        "saml_sp_private_key": {
            "type": "string",
            "nullable": True,
            "writeOnly": True,
            "description": "SAML SP private key. Leave null to keep existing private key on update.",
        },
        "has_saml_sp_private_key": {"type": "boolean", "readOnly": True},
        "saml_name_id_format": {
            "type": "string",
            "default": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        },

        "extra_config": {"type": "object", "nullable": True},

        "created_at": {"type": "string", "format": "date-time", "readOnly": True},
        "updated_at": {"type": "string", "format": "date-time", "readOnly": True},
    },
}


SSO_GROUP_MAPPING_SCHEMA = {
    "type": "object",
    "required": ["external_group", "group_id"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "integer", "readOnly": True, "example": 1},
        "provider_id": {"type": "integer", "readOnly": True, "example": 1},
        "external_group": {"type": "string", "minLength": 1, "maxLength": 512, "example": "infra"},
        "group_id": {"type": "integer", "minimum": 1, "example": 1},
        "group_slug": {"type": "string", "readOnly": True, "example": "infra"},
        "group_name": {"type": "string", "readOnly": True, "example": "Infrastructure"},
        "group_role": {
            "type": "string",
            "enum": list(GROUP_ROLE_VALUES),
            "default": GROUP_VIEWER_ROLE,
            "example": "viewer",
        },
        "team_id": {"type": "integer", "nullable": True, "minimum": 1, "example": 10},
        "team_slug": {"type": "string", "nullable": True, "readOnly": True, "example": "cloud-api"},
        "team_name": {"type": "string", "nullable": True, "readOnly": True, "example": "Cloud API"},
        "team_role": {
            "type": "string",
            "nullable": True,
            "enum": list(TEAM_ROLE_VALUES),
            "default": TEAM_VIEWER_ROLE,
            "example": "responder",
        },
        "active": {"type": "boolean", "default": True},
        "priority": {"type": "integer", "default": 100, "minimum": 0, "maximum": 100000},
        "created_at": {"type": "string", "format": "date-time", "readOnly": True},
        "updated_at": {"type": "string", "format": "date-time", "readOnly": True},
    },
}


SSO_DELETE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "deleted": {"type": "boolean", "example": True},
        "id": {"type": "integer", "example": 1},
    },
}


def tags():
    """Return OpenAPI tags."""
    return [
        {
            "name": "SSO",
            "description": "Public OIDC/SAML login endpoints.",
        },
        {
            "name": "Admin SSO",
            "description": "Administrative SSO provider and group mapping management.",
        },
    ]


def paths():
    """Return OpenAPI paths for SSO endpoints."""
    return {
        "/api/auth/sso/providers": {
            "get": {
                "tags": ["SSO"],
                "summary": "List public SSO providers",
                "description": "Returns enabled SSO providers that can be displayed on the login page.",
                "operationId": "listPublicSsoProviders",
                "responses": {
                    "200": response(
                        "Enabled SSO providers.",
                        {"type": "array", "items": PUBLIC_SSO_PROVIDER_SCHEMA},
                    ),
                },
            },
        },

        "/api/auth/sso/{slug}/login": {
            "get": {
                "tags": ["SSO"],
                "summary": "Start SSO login",
                "description": "Starts OIDC or SAML login flow for the selected provider.",
                "operationId": "startSsoLogin",
                "parameters": [slug_param()],
                "responses": {
                    "302": {"description": "Redirect to identity provider."},
                    "400": response("SSO provider is not configured correctly.", ERROR_SCHEMA),
                    "404": response("SSO provider not found or disabled.", ERROR_SCHEMA),
                },
            },
        },

        "/api/auth/sso/{slug}/callback": {
            "get": {
                "tags": ["SSO"],
                "summary": "Complete OIDC SSO login",
                "description": "OIDC callback endpoint. On success, creates IncidentRelay JWT cookie and redirects to UI.",
                "operationId": "completeOidcSsoLogin",
                "parameters": [slug_param()],
                "responses": {
                    "302": {"description": "SSO login completed and user redirected to UI."},
                    "400": response("SSO callback validation failed.", ERROR_SCHEMA),
                    "403": response("SSO login is denied by provider policy.", ERROR_SCHEMA),
                    "404": response("SSO provider not found or disabled.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["SSO"],
                "summary": "Complete SAML SSO login",
                "description": "SAML ACS endpoint. On success, creates IncidentRelay JWT cookie and redirects to UI.",
                "operationId": "completeSamlSsoLogin",
                "parameters": [slug_param()],
                "responses": {
                    "302": {"description": "SSO login completed and user redirected to UI."},
                    "400": response("SAML response validation failed.", ERROR_SCHEMA),
                    "401": response("SAML response was not authenticated.", ERROR_SCHEMA),
                    "403": response("SSO login is denied by provider policy.", ERROR_SCHEMA),
                    "404": response("SSO provider not found or disabled.", ERROR_SCHEMA),
                },
            },
        },

        "/api/auth/sso/{slug}/metadata": {
            "get": {
                "tags": ["SSO"],
                "summary": "Get SAML SP metadata",
                "description": "Returns SAML Service Provider metadata for the selected provider.",
                "operationId": "getSamlSpMetadata",
                "parameters": [slug_param()],
                "responses": {
                    "200": {
                        "description": "SAML SP metadata XML.",
                        "content": {
                            "application/xml": {
                                "schema": {"type": "string"},
                            },
                        },
                    },
                    "400": response("Provider is not a SAML provider.", ERROR_SCHEMA),
                    "404": response("SSO provider not found or disabled.", ERROR_SCHEMA),
                },
            },
        },

        "/api/admin/sso/providers": {
            "get": {
                "tags": ["Admin SSO"],
                "summary": "List SSO providers",
                "description": "Returns all non-deleted SSO providers. Admin permission is required.",
                "operationId": "listSsoProviders",
                "security": [{"bearerAuth": []}],
                "responses": {
                    "200": response(
                        "SSO providers.",
                        {"type": "array", "items": SSO_PROVIDER_SCHEMA},
                    ),
                    "403": response("Admin permission is required.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["Admin SSO"],
                "summary": "Create SSO provider",
                "description": "Creates OIDC or SAML provider. Admin permission is required.",
                "operationId": "createSsoProvider",
                "security": [{"bearerAuth": []}],
                "requestBody": json_body("SSO provider properties.", SSO_PROVIDER_SCHEMA),
                "responses": {
                    "201": response("SSO provider created.", SSO_PROVIDER_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Admin permission is required.", ERROR_SCHEMA),
                    "409": response("Provider already exists.", ERROR_SCHEMA),
                },
            },
        },

        "/api/admin/sso/providers/{provider_id}": {
            "put": {
                "tags": ["Admin SSO"],
                "summary": "Update SSO provider",
                "description": "Updates OIDC or SAML provider. Admin permission is required.",
                "operationId": "updateSsoProvider",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("provider_id", "SSO provider id.")],
                "requestBody": json_body("Updated SSO provider properties.", SSO_PROVIDER_SCHEMA),
                "responses": {
                    "200": response("SSO provider updated.", SSO_PROVIDER_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Admin permission is required.", ERROR_SCHEMA),
                    "404": response("SSO provider not found.", ERROR_SCHEMA),
                    "409": response("Provider already exists.", ERROR_SCHEMA),
                },
            },
            "delete": {
                "tags": ["Admin SSO"],
                "summary": "Delete SSO provider",
                "description": "Soft-deletes SSO provider and disables its mappings. Admin permission is required.",
                "operationId": "deleteSsoProvider",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("provider_id", "SSO provider id.")],
                "responses": {
                    "200": response("SSO provider deleted.", SSO_DELETE_RESPONSE_SCHEMA),
                    "403": response("Admin permission is required.", ERROR_SCHEMA),
                    "404": response("SSO provider not found.", ERROR_SCHEMA),
                },
            },
        },

        "/api/admin/sso/providers/{provider_id}/mappings": {
            "get": {
                "tags": ["Admin SSO"],
                "summary": "List SSO group mappings",
                "description": "Returns SSO group mappings for one provider. Admin permission is required.",
                "operationId": "listSsoGroupMappings",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("provider_id", "SSO provider id.")],
                "responses": {
                    "200": response(
                        "SSO group mappings.",
                        {"type": "array", "items": SSO_GROUP_MAPPING_SCHEMA},
                    ),
                    "403": response("Admin permission is required.", ERROR_SCHEMA),
                    "404": response("SSO provider not found.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["Admin SSO"],
                "summary": "Create SSO group mapping",
                "description": "Maps external SSO group value to IncidentRelay group role. Admin permission is required.",
                "operationId": "createSsoGroupMapping",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("provider_id", "SSO provider id.")],
                "requestBody": json_body("SSO group mapping properties.", SSO_GROUP_MAPPING_SCHEMA),
                "responses": {
                    "201": response("SSO group mapping created.", SSO_GROUP_MAPPING_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Admin permission is required.", ERROR_SCHEMA),
                    "409": response("Mapping already exists.", ERROR_SCHEMA),
                },
            },
        },

        "/api/admin/sso/mappings/{mapping_id}": {
            "put": {
                "tags": ["Admin SSO"],
                "summary": "Update SSO group mapping",
                "description": "Updates SSO group mapping. Admin permission is required.",
                "operationId": "updateSsoGroupMapping",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("mapping_id", "SSO group mapping id.")],
                "requestBody": json_body("Updated SSO group mapping properties.", SSO_GROUP_MAPPING_SCHEMA),
                "responses": {
                    "200": response("SSO group mapping updated.", SSO_GROUP_MAPPING_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Admin permission is required.", ERROR_SCHEMA),
                    "404": response("Mapping not found.", ERROR_SCHEMA),
                },
            },
            "delete": {
                "tags": ["Admin SSO"],
                "summary": "Delete SSO group mapping",
                "description": "Deletes SSO group mapping. Admin permission is required.",
                "operationId": "deleteSsoGroupMapping",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("mapping_id", "SSO group mapping id.")],
                "responses": {
                    "200": response("SSO group mapping deleted.", SSO_DELETE_RESPONSE_SCHEMA),
                    "403": response("Admin permission is required.", ERROR_SCHEMA),
                    "404": response("Mapping not found.", ERROR_SCHEMA),
                },
            },
        },
    }
