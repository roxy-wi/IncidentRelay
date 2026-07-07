from app.api.schemas.limits import (
    DESCRIPTION_MAX_LENGTH,
    NAME_MAX_LENGTH,
    NAME_MIN_LENGTH,
    ROLE_MAX_LENGTH,
    SLUG_MAX_LENGTH,
    SLUG_MIN_LENGTH,
    USERNAME_MAX_LENGTH,
    USERNAME_MIN_LENGTH,
    DISPLAY_NAME_MAX_LENGTH,
    PHONE_MAX_LENGTH,
    CONTACT_ID_MAX_LENGTH,
)
from app.api.schemas.roles import (
    GROUP_ASSIGNABLE_BY_USER_ADMIN_VALUES,
    GROUP_ROLE_VALUES,
    GROUP_VIEWER_ROLE,
)
from app.api.openapi.common import response, path_param, json_body


ERROR_SCHEMA = {
    "type": "object",
    "properties": {
        "error": {"type": "string", "example": "validation_error"},
        "message": {"type": "string", "nullable": True},
    },
}

GROUP_SCHEMA = {
    "type": "object",
    "required": ["slug", "name"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "integer", "readOnly": True, "example": 1},
        "slug": {
            "type": "string",
            "minLength": SLUG_MIN_LENGTH,
            "maxLength": SLUG_MAX_LENGTH,
            "pattern": "^[a-z0-9][a-z0-9_-]*$",
            "example": "infra",
            "description": "Stable group slug.",
        },
        "name": {
            "type": "string",
            "minLength": NAME_MIN_LENGTH,
            "maxLength": NAME_MAX_LENGTH,
            "example": "Infrastructure",
            "description": "Human-readable group name.",
        },
        "description": {
            "type": "string",
            "nullable": True,
            "maxLength": DESCRIPTION_MAX_LENGTH,
            "example": "Infrastructure access boundary.",
        },
        "active": {"type": "boolean", "default": True, "description": "Whether the group is active."},
    },
}

GROUP_MEMBER_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "user_id": {"type": "integer", "minimum": 1},
        "username": {"type": "string", "readOnly": True},
        "display_name": {"type": "string", "nullable": True, "readOnly": True},
        "role": {"type": "string", "enum": list(GROUP_ROLE_VALUES), "default": GROUP_VIEWER_ROLE, "maxLength": ROLE_MAX_LENGTH},
        "active": {"type": "boolean", "default": True},
    },
}

GROUP_MEMBER_ADD_SCHEMA = {
    "type": "object",
    "required": ["user_id"],
    "additionalProperties": False,
    "properties": {
        "user_id": {"type": "integer", "minimum": 1, "example": 1},
        "role": {"type": "string", "enum": list(GROUP_ROLE_VALUES), "default": GROUP_VIEWER_ROLE, "maxLength": ROLE_MAX_LENGTH},
    },
}

GROUP_MEMBER_UPDATE_SCHEMA = {
    "type": "object",
    "required": ["role", "active"],
    "additionalProperties": False,
    "properties": {
        "role": {"type": "string", "enum": list(GROUP_ROLE_VALUES), "default": GROUP_VIEWER_ROLE, "maxLength": ROLE_MAX_LENGTH},
        "active": {"type": "boolean", "default": True},
    },
}

GROUP_USER_CREATE_SCHEMA = {
    "type": "object",
    "required": ["username", "password"],
    "additionalProperties": False,
    "properties": {
        "username": {
            "type": "string",
            "minLength": USERNAME_MIN_LENGTH,
            "maxLength": USERNAME_MAX_LENGTH,
            "pattern": "^[a-zA-Z0-9._-]+$",
            "example": "ivan",
        },
        "display_name": {"type": "string", "nullable": True, "maxLength": DISPLAY_NAME_MAX_LENGTH, "example": "Ivan"},
        "email": {"type": "string", "format": "email", "nullable": True, "example": "ivan@example.com"},
        "phone": {"type": "string", "nullable": True, "maxLength": PHONE_MAX_LENGTH, "example": "+77001234567"},
        "telegram_user_id": {"type": "string", "nullable": True, "maxLength": CONTACT_ID_MAX_LENGTH, "example": "123456789"},
        "slack_user_id": {"type": "string", "nullable": True, "maxLength": CONTACT_ID_MAX_LENGTH, "example": "U012ABCDEF"},
        "mattermost_user_id": {"type": "string", "nullable": True, "maxLength": CONTACT_ID_MAX_LENGTH, "example": "9x8y7z6abc"},
        "password": {"type": "string", "minLength": 8, "maxLength": 256, "writeOnly": True, "example": "strong-password"},
        "group_role": {
            "type": "string",
            "enum": list(GROUP_ASSIGNABLE_BY_USER_ADMIN_VALUES),
            "default": GROUP_VIEWER_ROLE,
            "maxLength": ROLE_MAX_LENGTH,
            "description": "Initial group role. Group user-admins may assign only viewer or editor.",
        },
    },
}


USER_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "username": {"type": "string"},
        "display_name": {"type": "string", "nullable": True},
        "email": {"type": "string", "format": "email", "nullable": True},
        "phone": {"type": "string", "nullable": True},
        "telegram_user_id": {"type": "string", "nullable": True},
        "slack_user_id": {"type": "string", "nullable": True},
        "mattermost_user_id": {"type": "string", "nullable": True},
        "active": {"type": "boolean"},
        "is_admin": {"type": "boolean"},
        "active_group_id": {"type": "integer", "nullable": True},
        "active_group_slug": {"type": "string", "nullable": True},
    },
}

GROUP_DELETE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "deleted": {"type": "boolean", "example": True},
        "id": {"type": "integer", "example": 1},
        "slug": {"type": "string", "example": "infra"},
        "name": {"type": "string", "example": "Infrastructure"},
    },
}


def tags():
    """Return OpenAPI tags."""
    return [
        {
            "name": "groups",
            "description": "Access boundaries for teams, users, routes, rotations, notification channels and silences.",
        }
    ]


def paths():
    """Return OpenAPI paths for group endpoints."""
    return {
        "/api/groups": {
            "get": {
                "tags": ["groups"],
                "summary": "List groups",
                "description": "Returns groups visible to the current user. Admins see all active groups.",
                "operationId": "listGroups",
                "responses": {"200": response("List of groups.", {"type": "array", "items": GROUP_SCHEMA})},
            },
            "post": {
                "tags": ["groups"],
                "summary": "Create group",
                "description": "Creates a new group. Admin permission is required.",
                "operationId": "createGroup",
                "requestBody": json_body("Group properties.", GROUP_SCHEMA),
                "responses": {
                    "201": response("Group created.", GROUP_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Admin permission is required.", ERROR_SCHEMA),
                },
            },
        },
        "/api/groups/{group_id}": {
            "put": {
                "tags": ["groups"],
                "summary": "Update group",
                "description": "Updates group properties. Group editor or global admin is required.",
                "operationId": "updateGroup",
                "parameters": [path_param("group_id", "Group id.")],
                "requestBody": json_body("Updated group properties.", GROUP_SCHEMA),
                "responses": {
                    "200": response("Group updated.", GROUP_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Group not found.", ERROR_SCHEMA),
                },
            },
            "delete": {
                "tags": ["groups"],
                "summary": "Delete group",
                "description": "Soft-deletes a group and disables resources under it. Admin permission is required.",
                "operationId": "deleteGroup",
                "parameters": [path_param("group_id", "Group id.")],
                "responses": {
                    "200": response("Group deleted.", GROUP_DELETE_RESPONSE_SCHEMA),
                    "403": response("Admin permission is required.", ERROR_SCHEMA),
                    "404": response("Group not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/groups/{group_id}/users": {
            "get": {
                "tags": ["groups"],
                "summary": "List group users",
                "description": "Returns users that belong to the group.",
                "operationId": "listGroupUsers",
                "parameters": [path_param("group_id", "Group id.")],
                "responses": {"200": response("List of group users.", {"type": "array", "items": GROUP_MEMBER_SCHEMA})},
            },
            "post": {
                "tags": ["groups"],
                "summary": "Add existing user to group",
                "description": "Adds an existing user to the group. This changes the group boundary and is global-admin only.",
                "operationId": "addGroupUser",
                "parameters": [path_param("group_id", "Group id.")],
                "requestBody": json_body("Group membership data.", GROUP_MEMBER_ADD_SCHEMA),
                "responses": {
                    "201": response("User added to group.", GROUP_MEMBER_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Admin role is required.", ERROR_SCHEMA),
                },
            },
        },
        "/api/groups/{group_id}/users/create": {
            "post": {
                "tags": ["groups"],
                "summary": "Create user in group",
                "description": "Creates a new user inside this group. Requires user_admin role in this group or global admin. group_id, active and is_admin are not accepted in the body.",
                "operationId": "createGroupUser",
                "parameters": [path_param("group_id", "Group id.")],
                "requestBody": json_body("User properties for group-scoped creation.", GROUP_USER_CREATE_SCHEMA),
                "responses": {
                    "201": response("User created.", USER_RESPONSE_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Group user-admin role is required.", ERROR_SCHEMA),
                    "409": response("User already exists.", ERROR_SCHEMA),
                },
            },
        },
        "/api/groups/users/{membership_id}": {
            "put": {
                "tags": ["groups"],
                "summary": "Update group membership",
                "description": "Updates group membership role and active flag. user_admin can manage users in the same group but cannot assign user_admin role; global admin can assign any group role.",
                "operationId": "updateGroupUser",
                "parameters": [path_param("membership_id", "Group membership id.")],
                "requestBody": json_body("Updated group membership.", GROUP_MEMBER_UPDATE_SCHEMA),
                "responses": {
                    "200": response("Group membership updated.", GROUP_MEMBER_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Membership not found.", ERROR_SCHEMA),
                },
            },
            "delete": {
                "tags": ["groups"],
                "summary": "Remove group member",
                "description": "Removes user from the group and related group teams/rotations. Global admin only.",
                "operationId": "removeGroupUser",
                "parameters": [path_param("membership_id", "Group membership id.")],
                "responses": {
                    "200": response("Group membership removed.", {"type": "object", "properties": {"deleted": {"type": "boolean"}, "id": {"type": "integer"}}}),
                    "403": response("Admin role is required.", ERROR_SCHEMA),
                    "404": response("Membership not found.", ERROR_SCHEMA),
                },
            },
        },
    }
