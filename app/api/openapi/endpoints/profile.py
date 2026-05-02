def path_param(name, description):
    """
    Build an integer path parameter.
    """
    return {
        "name": name,
        "in": "path",
        "required": True,
        "description": description,
        "schema": {"type": "integer", "minimum": 1},
    }


def json_body(description, schema, required=True):
    """
    Build a JSON request body.
    """
    return {
        "required": required,
        "description": description,
        "content": {
            "application/json": {
                "schema": schema,
            }
        },
    }


def response(description, schema=None):
    """
    Build a JSON response object.
    """
    item = {"description": description}

    if schema:
        item["content"] = {
            "application/json": {
                "schema": schema,
            }
        }

    return item


ERROR_SCHEMA = {
    "type": "object",
    "properties": {
        "error": {
            "type": "string",
            "example": "Validation error",
        },
    },
}


GROUP_MEMBERSHIP_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {
            "type": "integer",
            "readOnly": True,
            "description": "Group membership id.",
            "example": 12,
        },
        "group_id": {
            "type": "integer",
            "description": "Group id.",
            "example": 1,
        },
        "group_slug": {
            "type": "string",
            "description": "Group slug.",
            "example": "production",
        },
        "group_name": {
            "type": "string",
            "description": "Group display name.",
            "example": "Production",
        },
        "role": {
            "type": "string",
            "description": "User role inside the group.",
            "enum": ["read_only", "rw"],
            "example": "rw",
        },
        "active": {
            "type": "boolean",
            "description": "Whether this group membership is active.",
            "example": True,
        },
    },
}


PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {
            "type": "integer",
            "readOnly": True,
            "description": "Current user id.",
            "example": 2,
        },
        "username": {
            "type": "string",
            "readOnly": True,
            "description": "Login username.",
            "example": "ivan",
        },
        "display_name": {
            "type": "string",
            "nullable": True,
            "description": "Human-readable display name.",
            "example": "Ivan",
        },
        "email": {
            "type": "string",
            "format": "email",
            "nullable": True,
            "description": "User email address.",
            "example": "ivan@example.com",
        },
        "phone": {
            "type": "string",
            "nullable": True,
            "description": "Phone number for voice or SMS integrations.",
            "example": "+77001234567",
        },
        "telegram_chat_id": {
            "type": "string",
            "nullable": True,
            "description": "Telegram chat id used for direct notifications.",
            "example": "123456789",
        },
        "slack_user_id": {
            "type": "string",
            "nullable": True,
            "description": "Slack user id used for direct notifications.",
            "example": "U012ABCDEF",
        },
        "mattermost_user_id": {
            "type": "string",
            "nullable": True,
            "description": (
                "Mattermost user id. Used to map Mattermost interactive "
                "button clicks to an IncidentRelay user."
            ),
            "example": "9x8y7z6abc",
        },
        "active": {
            "type": "boolean",
            "readOnly": True,
            "description": "Whether the current user account is active.",
            "example": True,
        },
        "is_admin": {
            "type": "boolean",
            "readOnly": True,
            "description": "Whether the current user has global admin permissions.",
            "example": False,
        },
        "active_group_id": {
            "type": "integer",
            "nullable": True,
            "description": "Currently selected group scope.",
            "example": 1,
        },
        "active_group_slug": {
            "type": "string",
            "nullable": True,
            "description": "Slug of the currently selected group scope.",
            "example": "production",
        },
        "groups": {
            "type": "array",
            "description": "Groups available to the current user.",
            "items": GROUP_MEMBERSHIP_SCHEMA,
        },
    },
}


PROFILE_UPDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "display_name": {
            "type": "string",
            "nullable": True,
            "example": "Ivan",
        },
        "email": {
            "type": "string",
            "format": "email",
            "nullable": True,
            "example": "ivan@example.com",
        },
        "phone": {
            "type": "string",
            "nullable": True,
            "example": "+77001234567",
        },
        "telegram_chat_id": {
            "type": "string",
            "nullable": True,
            "example": "123456789",
        },
        "slack_user_id": {
            "type": "string",
            "nullable": True,
            "example": "U012ABCDEF",
        },
        "mattermost_user_id": {
            "type": "string",
            "nullable": True,
            "example": "9x8y7z6abc",
        },
    },
}


CHANGE_PASSWORD_SCHEMA = {
    "type": "object",
    "required": ["old_password", "new_password"],
    "properties": {
        "old_password": {
            "type": "string",
            "minLength": 1,
            "maxLength": 256,
            "writeOnly": True,
            "description": "Current password.",
            "example": "old-password",
        },
        "new_password": {
            "type": "string",
            "minLength": 8,
            "maxLength": 256,
            "writeOnly": True,
            "description": "New password. Minimum length is 8 characters.",
            "example": "new-secure-password",
        },
    },
}


ACTIVE_GROUP_SCHEMA = {
    "type": "object",
    "properties": {
        "group_id": {
            "type": "integer",
            "nullable": True,
            "description": (
                "Group id to use as current UI/API scope. "
                "Use null to clear active group and show all accessible groups."
            ),
            "example": 1,
        },
    },
}


PROFILE_TOKEN_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {
            "type": "integer",
            "readOnly": True,
            "description": "Personal API token id.",
            "example": 10,
        },
        "name": {
            "type": "string",
            "description": "Token display name.",
            "example": "terraform-token",
        },
        "token_prefix": {
            "type": "string",
            "description": (
                "Safe token prefix used for identification. "
                "The full token is returned only once during creation."
            ),
            "example": "ir_abc12345",
        },
        "scopes": {
            "type": "array",
            "description": "Token scopes.",
            "items": {"type": "string"},
            "example": ["alerts:read", "resources:read"],
        },
        "group_id": {
            "type": "integer",
            "nullable": True,
            "description": "Optional group limit.",
            "example": 1,
        },
        "group_slug": {
            "type": "string",
            "nullable": True,
            "description": "Optional group slug.",
            "example": "production",
        },
        "group_name": {
            "type": "string",
            "nullable": True,
            "description": "Optional group display name.",
            "example": "Production",
        },
        "team_id": {
            "type": "integer",
            "nullable": True,
            "description": "Optional team limit.",
            "example": None,
        },
        "team_slug": {
            "type": "string",
            "nullable": True,
            "description": "Optional team slug.",
            "example": None,
        },
        "active": {
            "type": "boolean",
            "description": "Whether the token is active.",
            "example": True,
        },
        "expired": {
            "type": "boolean",
            "description": "Whether the token is expired.",
            "example": False,
        },
        "created_at": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
            "description": "Token creation timestamp.",
            "example": "2026-05-01T10:00:00",
        },
        "expires_at": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
            "description": "Token expiration timestamp. Null means no expiration.",
            "example": "2026-06-01T10:00:00",
        },
        "last_used_at": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
            "description": "Last successful token usage timestamp.",
            "example": "2026-05-01T11:30:00",
        },
    },
}


PROFILE_TOKEN_CREATE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 255,
            "default": "personal-api-token",
            "description": "Token display name.",
            "example": "terraform-token",
        },
        "group_id": {
            "type": "integer",
            "nullable": True,
            "description": (
                "Optional group limit. The current user must have access "
                "to this group."
            ),
            "example": 1,
        },
        "scopes": {
            "type": "array",
            "description": "Token scopes.",
            "items": {"type": "string"},
            "default": ["alerts:read"],
            "example": ["alerts:read", "resources:read"],
        },
        "days": {
            "type": "integer",
            "minimum": 0,
            "default": 0,
            "description": "Token lifetime in days. 0 means no expiration.",
            "example": 30,
        },
    },
}


PROFILE_TOKEN_CREATE_RESPONSE_SCHEMA = {
    "allOf": [
        PROFILE_TOKEN_SCHEMA,
        {
            "type": "object",
            "properties": {
                "token": {
                    "type": "string",
                    "description": (
                        "Full token value. Returned only once during creation. "
                        "It is not available through the token list endpoint."
                    ),
                    "example": "ir_full_raw_token_value",
                },
            },
        },
    ],
}


def tags():
    """
    Return OpenAPI tags for profile endpoints.
    """
    return [
        {
            "name": "profile",
            "description": (
                "Current user profile, active group, password management "
                "and personal API tokens."
            ),
        }
    ]


def paths():
    """
    Return OpenAPI path definitions for profile endpoints.
    """
    return {
        "/api/profile": {
            "get": {
                "tags": ["profile"],
                "summary": "Get current user profile",
                "description": (
                    "Returns current user profile with contact fields, messenger ids, "
                    "active group and group memberships."
                ),
                "operationId": "getProfile",
                "security": [{"bearerAuth": []}],
                "responses": {
                    "200": response("Current user profile.", PROFILE_SCHEMA),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                },
            },
            "put": {
                "tags": ["profile"],
                "summary": "Update current user profile",
                "description": (
                    "Updates editable profile fields for the current user. "
                    "Username, active state and admin flag cannot be changed here."
                ),
                "operationId": "updateProfile",
                "security": [{"bearerAuth": []}],
                "requestBody": json_body(
                    "Editable profile fields.",
                    PROFILE_UPDATE_SCHEMA,
                ),
                "responses": {
                    "200": response("Updated current user profile.", PROFILE_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                },
            },
        },
        "/api/profile/change-password": {
            "post": {
                "tags": ["profile"],
                "summary": "Change current user password",
                "description": (
                    "Changes the current user's local password. "
                    "The old password must be valid."
                ),
                "operationId": "changeProfilePassword",
                "security": [{"bearerAuth": []}],
                "requestBody": json_body(
                    "Old and new password.",
                    CHANGE_PASSWORD_SCHEMA,
                ),
                "responses": {
                    "200": response(
                        "Password changed.",
                        {
                            "type": "object",
                            "properties": {
                                "status": {
                                    "type": "string",
                                    "example": "password_changed",
                                },
                            },
                        },
                    ),
                    "400": response(
                        "Validation error or invalid old password.",
                        ERROR_SCHEMA,
                    ),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                },
            },
        },
        "/api/profile/active-group": {
            "post": {
                "tags": ["profile"],
                "summary": "Set active group",
                "description": (
                    "Sets the current user's active group scope. "
                    "Use group_id=null to clear the active group and show all "
                    "groups available to the user."
                ),
                "operationId": "setProfileActiveGroup",
                "security": [{"bearerAuth": []}],
                "requestBody": json_body(
                    "Active group selection.",
                    ACTIVE_GROUP_SCHEMA,
                ),
                "responses": {
                    "200": response("Updated current user profile.", PROFILE_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Selected group is not accessible.", ERROR_SCHEMA),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                },
            },
        },
        "/api/profile/tokens": {
            "get": {
                "tags": ["profile"],
                "summary": "List personal API tokens",
                "description": (
                    "Returns metadata for personal API tokens owned by the current user. "
                    "Token hashes and full raw token values are never returned."
                ),
                "operationId": "listProfileTokens",
                "security": [{"bearerAuth": []}],
                "responses": {
                    "200": response(
                        "Personal API token metadata.",
                        {
                            "type": "array",
                            "items": PROFILE_TOKEN_SCHEMA,
                        },
                    ),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["profile"],
                "summary": "Create personal API token",
                "description": (
                    "Creates a personal API token for the current user. "
                    "The full token value is returned only once in this response."
                ),
                "operationId": "createProfileToken",
                "security": [{"bearerAuth": []}],
                "requestBody": json_body(
                    "Token creation properties.",
                    PROFILE_TOKEN_CREATE_SCHEMA,
                ),
                "responses": {
                    "201": response(
                        "Personal API token created.",
                        PROFILE_TOKEN_CREATE_RESPONSE_SCHEMA,
                    ),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Selected group is not accessible.", ERROR_SCHEMA),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                },
            },
        },
        "/api/profile/tokens/{token_id}": {
            "delete": {
                "tags": ["profile"],
                "summary": "Revoke personal API token",
                "description": (
                    "Revokes a personal API token owned by the current user. "
                    "The token becomes inactive and is soft-deleted."
                ),
                "operationId": "revokeProfileToken",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("token_id", "Personal API token id."),
                ],
                "responses": {
                    "200": response(
                        "Personal API token revoked.",
                        {
                            "type": "object",
                            "properties": {
                                "revoked": {
                                    "type": "boolean",
                                    "example": True,
                                },
                                "id": {
                                    "type": "integer",
                                    "example": 10,
                                },
                            },
                        },
                    ),
                    "404": response("Token not found.", ERROR_SCHEMA),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                },
            },
        },
    }
