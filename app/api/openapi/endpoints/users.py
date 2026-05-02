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


def query_param(name, description, schema=None, required=False):
    """
    Build a query parameter.
    """
    return {
        "name": name,
        "in": "query",
        "required": required,
        "description": description,
        "schema": schema or {"type": "string"},
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


USER_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {
            "type": "integer",
            "readOnly": True,
            "description": "User id.",
            "example": 2,
        },
        "username": {
            "type": "string",
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
            "description": "Whether the user account is active.",
            "example": True,
        },
        "is_admin": {
            "type": "boolean",
            "description": "Whether the user has global admin permissions.",
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
    },
}


USER_WRITE_SCHEMA = {
    "type": "object",
    "required": ["username"],
    "properties": {
        "username": {
            "type": "string",
            "minLength": 2,
            "maxLength": 80,
            "pattern": "^[a-zA-Z0-9._-]+$",
            "description": "Login username.",
            "example": "ivan",
        },
        "display_name": {
            "type": "string",
            "nullable": True,
            "maxLength": 120,
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
            "maxLength": 64,
            "description": "Phone number for voice or SMS integrations.",
            "example": "+77001234567",
        },
        "telegram_chat_id": {
            "type": "string",
            "nullable": True,
            "maxLength": 128,
            "description": "Telegram chat id used for direct notifications.",
            "example": "123456789",
        },
        "slack_user_id": {
            "type": "string",
            "nullable": True,
            "maxLength": 128,
            "description": "Slack user id used for direct notifications.",
            "example": "U012ABCDEF",
        },
        "mattermost_user_id": {
            "type": "string",
            "nullable": True,
            "maxLength": 128,
            "description": (
                "Mattermost user id. Used to map Mattermost interactive "
                "button clicks to an IncidentRelay user."
            ),
            "example": "9x8y7z6abc",
        },
        "active": {
            "type": "boolean",
            "description": "Whether the user account is active.",
            "default": True,
        },
        "is_admin": {
            "type": "boolean",
            "description": "Whether the user has global admin permissions.",
            "default": False,
        },
        "password": {
            "type": "string",
            "nullable": True,
            "minLength": 8,
            "maxLength": 256,
            "writeOnly": True,
            "description": (
                "Optional password. On update, leave null or omit to keep "
                "the current password hash unchanged."
            ),
            "example": "strong-password",
        },
    },
}


USER_DELETE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {
            "type": "integer",
            "example": 2,
        },
        "username": {
            "type": "string",
            "example": "ivan",
        },
        "active": {
            "type": "boolean",
            "example": False,
        },
    },
}


def tags():
    """
    Return OpenAPI tags for user endpoints.
    """
    return [
        {
            "name": "users",
            "description": (
                "Users visible to the current principal and admin-only user "
                "management. Regular /api/users endpoints are read-only; "
                "user creation and modification is available only through "
                "/api/admin/users."
            ),
        }
    ]


def paths():
    """
    Return OpenAPI path definitions for user endpoints.
    """
    return {
        "/api/users": {
            "get": {
                "tags": ["users"],
                "summary": "List visible users",
                "description": (
                    "Returns users visible to the current principal. "
                    "Regular users receive users from groups they can access. "
                    "Admin users can pass all=1 to request all active users. "
                    "This endpoint is read-only and is intended for UI selectors "
                    "such as team members and rotation members."
                ),
                "operationId": "listUsers",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    query_param(
                        "all",
                        (
                            "Set to 1 to request all active users. "
                            "Only admin users should receive all active users."
                        ),
                        {
                            "type": "string",
                            "enum": ["1"],
                        },
                    ),
                ],
                "responses": {
                    "200": response(
                        "List of visible users.",
                        {
                            "type": "array",
                            "items": USER_RESPONSE_SCHEMA,
                        },
                    ),
                    "401": response("Valid JWT or API token is required.", ERROR_SCHEMA),
                },
            },
        },
        "/api/admin/users": {
            "get": {
                "tags": ["users"],
                "summary": "List users for admin workspace",
                "description": (
                    "Returns all non-deleted users for the admin users page. "
                    "Admin permission is required."
                ),
                "operationId": "listAdminUsers",
                "security": [{"bearerAuth": []}],
                "responses": {
                    "200": response(
                        "List of users.",
                        {
                            "type": "array",
                            "items": USER_RESPONSE_SCHEMA,
                        },
                    ),
                    "401": response("Valid JWT or API token is required.", ERROR_SCHEMA),
                    "403": response("Admin role is required.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["users"],
                "summary": "Create user",
                "description": (
                    "Creates a local user account from the admin namespace. "
                    "Admin permission is required. The regular /api/users "
                    "namespace does not allow creating users."
                ),
                "operationId": "createAdminUser",
                "security": [{"bearerAuth": []}],
                "requestBody": json_body(
                    "User properties.",
                    USER_WRITE_SCHEMA,
                ),
                "responses": {
                    "201": response("User created.", USER_RESPONSE_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "401": response("Valid JWT or API token is required.", ERROR_SCHEMA),
                    "403": response("Admin role is required.", ERROR_SCHEMA),
                },
            },
        },
        "/api/admin/users/{user_id}": {
            "get": {
                "tags": ["users"],
                "summary": "Get user for admin workspace",
                "description": (
                    "Returns one user from the admin namespace. "
                    "Admin permission is required."
                ),
                "operationId": "getAdminUser",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("user_id", "User id."),
                ],
                "responses": {
                    "200": response("User details.", USER_RESPONSE_SCHEMA),
                    "401": response("Valid JWT or API token is required.", ERROR_SCHEMA),
                    "403": response("Admin role is required.", ERROR_SCHEMA),
                    "404": response("User not found.", ERROR_SCHEMA),
                },
            },
            "put": {
                "tags": ["users"],
                "summary": "Update user",
                "description": (
                    "Updates user account, contact fields, messenger identifiers, "
                    "admin flag and active flag from the admin namespace. "
                    "Admin permission is required. Leave password null or omit it "
                    "to keep the current password hash unchanged."
                ),
                "operationId": "updateAdminUser",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("user_id", "User id."),
                ],
                "requestBody": json_body(
                    "Updated user properties.",
                    USER_WRITE_SCHEMA,
                ),
                "responses": {
                    "200": response("User updated.", USER_RESPONSE_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "401": response("Valid JWT or API token is required.", ERROR_SCHEMA),
                    "403": response("Admin role is required.", ERROR_SCHEMA),
                    "404": response("User not found.", ERROR_SCHEMA),
                },
            },
            "delete": {
                "tags": ["users"],
                "summary": "Remove user",
                "description": (
                    "Soft-deletes a user from the admin namespace. "
                    "The user is removed from groups, teams, rotations and overrides. "
                    "Personal API tokens are revoked. Historical alerts are preserved. "
                    "The current admin cannot remove their own account, and the last active "
                    "admin user cannot be removed."
                ),
                "operationId": "removeAdminUser",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("user_id", "User id."),
                ],
                "responses": {
                    "200": response(
                        "User removed.",
                        {
                            "type": "object",
                            "properties": {
                                "deleted": {
                                    "type": "boolean",
                                    "example": True,
                                },
                                "id": {
                                    "type": "integer",
                                    "example": 2,
                                },
                                "username": {
                                    "type": "string",
                                    "example": "ivan",
                                },
                            },
                        },
                    ),
                    "400": response("Cannot remove own user account.", ERROR_SCHEMA),
                    "401": response("Valid JWT or API token is required.", ERROR_SCHEMA),
                    "403": response("Admin role is required.", ERROR_SCHEMA),
                    "404": response("User not found.", ERROR_SCHEMA),
                    "409": response("Cannot remove the last active admin user.", ERROR_SCHEMA),
                },
            },
        },
    }
