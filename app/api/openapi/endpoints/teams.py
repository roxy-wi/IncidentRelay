from app.api.schemas.limits import (
    DESCRIPTION_MAX_LENGTH,
    NAME_MAX_LENGTH,
    NAME_MIN_LENGTH,
    ROLE_MAX_LENGTH,
    SLUG_MAX_LENGTH,
    SLUG_MIN_LENGTH,
)
from app.api.schemas.roles import TEAM_ROLE_VALUES, TEAM_VIEWER_ROLE
from app.api.openapi.common import response, path_param, json_body, query_param

ERROR_SCHEMA = {
    "type": "object",
    "properties": {
        "error": {"type": "string", "example": "validation_error"},
        "message": {"type": "string", "nullable": True},
    },
}

TEAM_SCHEMA = {
    "type": "object",
    "required": ["group_id", "slug", "name"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "group_id": {"type": "integer", "minimum": 1, "description": "Owner group id.", "example": 1},
        "group_slug": {"type": "string", "readOnly": True, "example": "production"},
        "group_name": {"type": "string", "readOnly": True, "example": "Production"},
        "slug": {
            "type": "string",
            "minLength": SLUG_MIN_LENGTH,
            "maxLength": SLUG_MAX_LENGTH,
            "pattern": "^[a-z0-9][a-z0-9_-]*$",
            "description": "Stable URL/API friendly team identifier.",
            "example": "infra",
        },
        "name": {"type": "string", "minLength": NAME_MIN_LENGTH, "maxLength": NAME_MAX_LENGTH, "description": "Human-readable team name.", "example": "Infrastructure"},
        "description": {"type": "string", "nullable": True, "maxLength": DESCRIPTION_MAX_LENGTH, "description": "Optional team description.", "example": "Infrastructure administrators"},
        "escalation_enabled": {"type": "boolean", "description": "Enable escalation to the next rotation member after repeated reminders.", "default": True},
        "escalation_after_reminders": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Number of reminders before the alert is escalated.", "example": 2},
        "active": {"type": "boolean", "description": "Whether the team is active. Use false to disable the team without deleting it.", "default": True},
    },
}

TEAM_MEMBER_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "user_id": {"type": "integer", "minimum": 1},
        "username": {"type": "string", "readOnly": True},
        "display_name": {"type": "string", "nullable": True, "readOnly": True},
        "role": {"type": "string", "enum": list(TEAM_ROLE_VALUES), "default": TEAM_VIEWER_ROLE, "maxLength": ROLE_MAX_LENGTH},
        "active": {"type": "boolean", "default": True},
    },
}

TEAM_MEMBER_ADD_SCHEMA = {
    "type": "object",
    "required": ["user_id"],
    "additionalProperties": False,
    "properties": {
        "user_id": {"type": "integer", "minimum": 1, "example": 1},
        "role": {"type": "string", "enum": list(TEAM_ROLE_VALUES), "default": TEAM_VIEWER_ROLE, "maxLength": ROLE_MAX_LENGTH},
    },
}

TEAM_MEMBER_UPDATE_SCHEMA = {
    "type": "object",
    "required": ["role", "active"],
    "additionalProperties": False,
    "properties": {
        "role": {"type": "string", "enum": list(TEAM_ROLE_VALUES), "default": TEAM_VIEWER_ROLE, "maxLength": ROLE_MAX_LENGTH},
        "active": {"type": "boolean", "default": True},
    },
}


def tags():
    """Return OpenAPI tags."""
    return [
        {
            "name": "teams",
            "description": "Independent on-call teams. Team roles control read, alert response and manager actions.",
        }
    ]


def paths():
    """Return OpenAPI paths for team endpoints."""
    return {
        "/api/teams": {
            "get": {
                "tags": ["teams"],
                "summary": "List teams",
                "description": "Returns teams visible to the current user. Regular users must have active team membership.",
                "operationId": "listTeams",
                "parameters": [query_param("include_inactive", "Set to true/1 to include disabled teams.", {"type": "string", "enum": ["1", "true", "yes", "on"]})],
                "responses": {"200": response("List of teams.", {"type": "array", "items": TEAM_SCHEMA})},
            },
            "post": {
                "tags": ["teams"],
                "summary": "Create team",
                "description": "Creates a new on-call team in a group. Group editor or global admin is required. Non-admin creator is added as team manager.",
                "operationId": "createTeam",
                "requestBody": json_body("Team properties.", TEAM_SCHEMA),
                "responses": {
                    "201": response("Team created.", TEAM_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Group editor role is required.", ERROR_SCHEMA),
                },
            },
        },
        "/api/teams/{team_id}": {
            "get": {
                "tags": ["teams"],
                "summary": "Get team",
                "description": "Returns one team by id. Team viewer, responder, manager or global admin is required.",
                "operationId": "getTeam",
                "parameters": [path_param("team_id", "Team id.")],
                "responses": {"200": response("Team details.", TEAM_SCHEMA), "403": response("Access denied.", ERROR_SCHEMA), "404": response("Team not found.", ERROR_SCHEMA)},
            },
            "put": {
                "tags": ["teams"],
                "summary": "Update team",
                "description": "Updates team properties. Team manager or global admin is required. Only global admin can move a team to another group.",
                "operationId": "updateTeam",
                "parameters": [path_param("team_id", "Team id.")],
                "requestBody": json_body("Updated team properties.", TEAM_SCHEMA),
                "responses": {"200": response("Team updated.", TEAM_SCHEMA), "400": response("Validation error.", ERROR_SCHEMA), "403": response("Access denied.", ERROR_SCHEMA)},
            },
            "delete": {
                "tags": ["teams"],
                "summary": "Remove team",
                "description": "Soft-deletes a team and non-historical resources under it. Team manager or global admin is required.",
                "operationId": "removeTeam",
                "parameters": [path_param("team_id", "Team id.")],
                "responses": {
                    "200": response("Team removed.", {"type": "object", "properties": {"deleted": {"type": "boolean"}, "id": {"type": "integer"}}}),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Team not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/teams/{team_id}/users": {
            "get": {
                "tags": ["teams"],
                "summary": "List team users",
                "description": "Returns users that belong to a team with their team roles.",
                "operationId": "listTeamUsers",
                "parameters": [path_param("team_id", "Team id.")],
                "responses": {"200": response("List of team users.", {"type": "array", "items": TEAM_MEMBER_SCHEMA})},
            },
            "post": {
                "tags": ["teams"],
                "summary": "Add user to team",
                "description": "Adds an existing group user to a team. User must already belong to the team's group; this endpoint does not add group membership.",
                "operationId": "addUserToTeam",
                "parameters": [path_param("team_id", "Team id.")],
                "requestBody": json_body("Team membership data.", TEAM_MEMBER_ADD_SCHEMA),
                "responses": {"201": response("User added to team."), "400": response("Validation error.", ERROR_SCHEMA), "403": response("Team manager role is required.", ERROR_SCHEMA)},
            },
        },
        "/api/teams/users/{membership_id}": {
            "put": {
                "tags": ["teams"],
                "summary": "Update team membership",
                "description": "Updates team membership role and active flag. Team manager or global admin is required.",
                "operationId": "updateTeamUser",
                "parameters": [path_param("membership_id", "Team membership id.")],
                "requestBody": json_body("Updated team membership.", TEAM_MEMBER_UPDATE_SCHEMA),
                "responses": {"200": response("Team membership updated.", TEAM_MEMBER_SCHEMA), "400": response("Validation error.", ERROR_SCHEMA), "403": response("Access denied.", ERROR_SCHEMA), "404": response("Membership not found.", ERROR_SCHEMA)},
            },
            "delete": {
                "tags": ["teams"],
                "summary": "Remove team member",
                "description": "Removes user from the team and rotations of the same team. Team manager or global admin is required.",
                "operationId": "removeTeamUser",
                "parameters": [path_param("membership_id", "Team membership id.")],
                "responses": {"200": response("Team membership removed.", {"type": "object", "properties": {"deleted": {"type": "boolean"}, "id": {"type": "integer"}}}), "403": response("Access denied.", ERROR_SCHEMA), "404": response("Membership not found.", ERROR_SCHEMA)},
            },
        },
    }
