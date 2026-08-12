from app.api.openapi.common import ERROR_SCHEMA, json_body, path_param, query_param, response
from app.api.schemas.limits import (
    CONTACT_ID_MAX_LENGTH,
    DISPLAY_NAME_MAX_LENGTH,
    PHONE_MAX_LENGTH,
    ROLE_MAX_LENGTH,
    USERNAME_MAX_LENGTH,
    USERNAME_MIN_LENGTH,
)
from app.api.schemas.roles import GROUP_ROLE_VALUES, GROUP_VIEWER_ROLE

USER_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "readOnly": True, "description": "User id.", "example": 2},
        "username": {"type": "string", "description": "Login username.", "example": "ivan"},
        "display_name": {"type": "string", "nullable": True, "description": "Human-readable display name.", "example": "Ivan"},
        "email": {"type": "string", "format": "email", "nullable": True, "description": "User email address.", "example": "ivan@example.com"},
        "phone": {"type": "string", "nullable": True, "description": "Phone number for voice integrations.", "example": "+77001234567"},
        "telegram_user_id": {"type": "string", "nullable": True, "description": "Telegram user ID used for direct notifications.", "example": "123456789"},
        "slack_user_id": {"type": "string", "nullable": True, "description": "Slack user ID used to attribute interactive Slack ACK/Resolve actions to an IncidentRelay user.", "example": "U012ABCDEF"},
        "mattermost_user_id": {
            "type": "string",
            "nullable": True,
            "description": "Mattermost user id used to map interactive button clicks to an IncidentRelay user.",
            "example": "9x8y7z6abc",
        },
        "active": {"type": "boolean", "description": "Whether the user account is active.", "example": True},
        "is_admin": {"type": "boolean", "description": "Whether the user has global admin permissions.", "example": False},
        "active_group_id": {"type": "integer", "nullable": True, "description": "Currently selected group scope.", "example": 1},
        "active_group_slug": {"type": "string", "nullable": True, "description": "Slug of the currently selected group scope.", "example": "production"},
        "active_group_role": {"type": "string", "nullable": True, "enum": list(GROUP_ROLE_VALUES), "description": "Role in the active group.", "example": GROUP_VIEWER_ROLE},
        "is_current_user": {"type": "boolean", "description": "True when this record is the authenticated user.", "example": False},
    },
}

USER_BASE_PROPERTIES = {
    "username": {
        "type": "string",
        "minLength": USERNAME_MIN_LENGTH,
        "maxLength": USERNAME_MAX_LENGTH,
        "pattern": "^[a-zA-Z0-9._-]+$",
        "description": "Login username.",
        "example": "ivan",
    },
    "display_name": {
        "type": "string",
        "nullable": True,
        "maxLength": DISPLAY_NAME_MAX_LENGTH,
        "description": "Human-readable display name.",
        "example": "Ivan",
    },
    "email": {"type": "string", "format": "email", "nullable": True, "description": "User email address.", "example": "ivan@example.com"},
    "phone": {"type": "string", "nullable": True, "maxLength": PHONE_MAX_LENGTH, "description": "Phone number for voice integrations.", "example": "+77001234567"},
    "telegram_user_id": {"type": "string", "nullable": True, "maxLength": CONTACT_ID_MAX_LENGTH, "description": "Telegram user ID used for direct notifications.", "example": "123456789"},
    "slack_user_id": {"type": "string", "nullable": True, "maxLength": CONTACT_ID_MAX_LENGTH, "description": "Slack user ID used to attribute interactive Slack ACK/Resolve actions to an IncidentRelay user.", "example": "U012ABCDEF"},
    "mattermost_user_id": {
        "type": "string",
        "nullable": True,
        "maxLength": CONTACT_ID_MAX_LENGTH,
        "description": "Mattermost user id used to map interactive button clicks to an IncidentRelay user.",
        "example": "9x8y7z6abc",
    },
    "active": {"type": "boolean", "description": "Whether the user account is active.", "default": True},
    "is_admin": {"type": "boolean", "description": "Whether the user has global admin permissions.", "default": False},
    "password": {
        "type": "string",
        "nullable": True,
        "minLength": 8,
        "maxLength": 256,
        "writeOnly": True,
        "description": "Optional password. On update, leave null or omit to keep the current password hash unchanged.",
        "example": "strong-password",
    },
}

GROUP_MEMBERSHIP_WRITE_PROPERTIES = {
    "group_id": {
        "type": "integer",
        "nullable": True,
        "minimum": 1,
        "description": (
            "Optional group id. On create, the user is added to this group. "
            "On update, this updates the user's active group membership from the Users page. "
            "Pass null to clear active_group_id without removing memberships."
        ),
        "example": 1,
    },
    "group_role": {
        "type": "string",
        "enum": list(GROUP_ROLE_VALUES),
        "default": GROUP_VIEWER_ROLE,
        "maxLength": ROLE_MAX_LENGTH,
        "description": (
            "Role assigned to the selected group membership. Used when group_id is provided. "
            "Global admins may assign any group role."
        ),
        "example": GROUP_VIEWER_ROLE,
    },
}

USER_CREATE_SCHEMA = {
    "type": "object",
    "required": ["username"],
    "additionalProperties": False,
    "properties": {**USER_BASE_PROPERTIES, **GROUP_MEMBERSHIP_WRITE_PROPERTIES},
}

USER_UPDATE_SCHEMA = {
    "type": "object",
    "required": ["username"],
    "additionalProperties": False,
    "properties": {**USER_BASE_PROPERTIES, **GROUP_MEMBERSHIP_WRITE_PROPERTIES},
}

USER_DELETE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "deleted": {"type": "boolean", "example": True},
        "id": {"type": "integer", "example": 2},
        "username": {"type": "string", "example": "ivan"},
    },
}


def tags():
    """Return OpenAPI tags for user endpoints."""
    return [
        {
            "name": "users",
            "description": (
                "Users visible to the current principal and admin-only user management. "
                "Regular /api/users endpoints are read-only. User creation and modification "
                "is available through /api/admin/users and group-scoped creation through "
                "/api/groups/{group_id}/users/create."
            ),
        }
    ]


def paths():
    """Return OpenAPI path definitions for user endpoints."""
    return {
        "/api/users": {
            "get": {
                "tags": ["users"],
                "summary": "List visible users",
                "description": "Returns users visible to the current principal. Regular users receive users from groups they can access.",
                "operationId": "listUsers",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    query_param(
                        "all",
                        "Set to 1 to request all active users. Only admin users should receive all active users.",
                        {"type": "string", "enum": ["1"]},
                    )
                ],
                "responses": {
                    "200": response("List of visible users.", {"type": "array", "items": USER_RESPONSE_SCHEMA}),
                    "401": response("Valid JWT or API token is required.", ERROR_SCHEMA),
                },
            }
        },
        "/api/admin/users": {
            "get": {
                "tags": ["users"],
                "summary": "List users for admin workspace",
                "description": "Returns all non-deleted users for the admin users page. Admin permission is required.",
                "operationId": "listAdminUsers",
                "security": [{"bearerAuth": []}],
                "responses": {
                    "200": response("List of users.", {"type": "array", "items": USER_RESPONSE_SCHEMA}),
                    "401": response("Valid JWT or API token is required.", ERROR_SCHEMA),
                    "403": response("Admin role is required.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["users"],
                "summary": "Create user",
                "description": "Creates a local user account from the admin namespace. Admin permission is required. If group_id is provided, the user is added to that group immediately.",
                "operationId": "createAdminUser",
                "security": [{"bearerAuth": []}],
                "requestBody": json_body("User properties. Optionally include group_id and group_role to add the user to a group immediately.", USER_CREATE_SCHEMA),
                "responses": {
                    "201": response("User created.", USER_RESPONSE_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "401": response("Valid JWT or API token is required.", ERROR_SCHEMA),
                    "403": response("Admin role is required.", ERROR_SCHEMA),
                    "404": response("Selected group was not found.", ERROR_SCHEMA),
                    "409": response("User already exists.", ERROR_SCHEMA),
                },
            },
        },
        "/api/admin/users/{user_id}": {
            "get": {
                "tags": ["users"],
                "summary": "Get user for admin workspace",
                "description": "Returns one user from the admin namespace. Admin permission is required.",
                "operationId": "getAdminUser",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("user_id", "User id.")],
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
                    "Updates user account, contact fields, messenger identifiers, admin flag, "
                    "active flag and the active group membership from the admin namespace. "
                    "If group_id is provided, the user is added to that group with group_role "
                    "and active_group_id is updated. If group_id is null, active_group_id is cleared. "
                    "Existing memberships are not removed by this endpoint."
                ),
                "operationId": "updateAdminUser",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("user_id", "User id.")],
                "requestBody": json_body("Updated user properties. Include group_id and group_role to update the active group membership from the Users page.", USER_UPDATE_SCHEMA),
                "responses": {
                    "200": response("User updated.", USER_RESPONSE_SCHEMA),
                    "400": response("Validation error or self-deactivation denied.", ERROR_SCHEMA),
                    "401": response("Valid JWT or API token is required.", ERROR_SCHEMA),
                    "403": response("Admin role is required.", ERROR_SCHEMA),
                    "404": response("User or selected group not found.", ERROR_SCHEMA),
                    "409": response("User already exists.", ERROR_SCHEMA),
                },
            },
            "delete": {
                "tags": ["users"],
                "summary": "Remove user",
                "description": "Soft-deletes a user from the admin namespace. Historical alerts are preserved. The current user and the last active admin user cannot be removed.",
                "operationId": "removeAdminUser",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("user_id", "User id.")],
                "responses": {
                    "200": response("User removed.", USER_DELETE_RESPONSE_SCHEMA),
                    "400": response("Cannot remove own user account.", ERROR_SCHEMA),
                    "401": response("Valid JWT or API token is required.", ERROR_SCHEMA),
                    "403": response("Admin role is required.", ERROR_SCHEMA),
                    "404": response("User not found.", ERROR_SCHEMA),
                    "409": response("Cannot remove the last active admin user.", ERROR_SCHEMA),
                },
            },
        },
    }
