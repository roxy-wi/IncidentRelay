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
                "schema": schema
            }
        },
    }


def response(description, schema=None):
    """
    Build a JSON response.
    """

    item = {"description": description}

    if schema:
        item["content"] = {
            "application/json": {
                "schema": schema
            }
        }

    return item


TEAM_SCHEMA = {
    "type": "object",
    "required": ["group_id", "slug", "name"],
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "group_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Owner group id.",
            "example": 1,
        },
        "group_slug": {
            "type": "string",
            "readOnly": True,
            "example": "production",
        },
        "group_name": {
            "type": "string",
            "readOnly": True,
            "example": "Production",
        },
        "slug": {
            "type": "string",
            "description": "Stable URL/API friendly team identifier.",
            "example": "infra",
        },
        "name": {
            "type": "string",
            "description": "Human-readable team name.",
            "example": "Infrastructure",
        },
        "description": {
            "type": "string",
            "nullable": True,
            "description": "Optional team description.",
            "example": "Infrastructure administrators",
        },
        "escalation_enabled": {
            "type": "boolean",
            "description": "Enable escalation to the next rotation member after repeated reminders.",
            "default": True,
        },
        "escalation_after_reminders": {
            "type": "integer",
            "description": "Number of reminders before the alert is escalated.",
            "example": 2,
        },
        "active": {
            "type": "boolean",
            "description": "Whether the team is active. Use false to disable the team without deleting it.",
            "default": True,
        },
    },
}

TEAM_MEMBER_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "user_id": {"type": "integer", "minimum": 1},
        "username": {"type": "string", "readOnly": True},
        "display_name": {"type": "string", "nullable": True, "readOnly": True},
        "role": {
            "type": "string",
            "enum": ["read_only", "rw"],
            "default": "read_only",
        },
        "active": {"type": "boolean", "default": True},
    },
}

TEAM_MEMBER_UPDATE_SCHEMA = {
    "type": "object",
    "required": ["role", "active"],
    "properties": {
        "role": {
            "type": "string",
            "enum": ["read_only", "rw"],
            "default": "read_only",
        },
        "active": {"type": "boolean", "default": True},
    },
}


def tags():
    """
    Return OpenAPI tags.
    """

    return [
        {
            "name": "teams",
            "description": (
                "Independent on-call teams. Each team can have its own users, rotations, "
                "routes, notification channels, silences and alerts."
            ),
        }
    ]


def paths():
    """
    Return OpenAPI paths for team endpoints.
    """

    return {
        "/api/teams": {
            "get": {
                "tags": ["teams"],
                "summary": "List teams",
                "description": "Returns all configured on-call teams. The UI uses this endpoint to build team filters.",
                "operationId": "listTeams",
                "responses": {
                    "200": response("List of teams.", {"type": "array", "items": TEAM_SCHEMA})
                },
            },
            "post": {
                "tags": ["teams"],
                "summary": "Create team",
                "description": (
                    "Creates a new independent on-call team. Alerts are routed to teams through alert routes, "
                    "usually by matching labels such as labels.team."
                ),
                "operationId": "createTeam",
                "requestBody": json_body("Team properties.", TEAM_SCHEMA),
                "responses": {
                    "201": response("Team created.", {"type": "object", "properties": {"id": {"type": "integer"}}}),
                    "400": response("Validation error."),
                },
            },
        },
        "/api/teams/{team_id}": {
            "get": {
                "tags": ["teams"],
                "summary": "Get team",
                "description": "Returns one team by id.",
                "operationId": "getTeam",
                "parameters": [path_param("team_id", "Team id.")],
                "responses": {"200": response("Team details.", TEAM_SCHEMA), "404": response("Team not found.")},
            },
            "put": {
                "tags": ["teams"],
                "summary": "Update team",
                "description": "Updates team properties, including escalation settings.",
                "operationId": "updateTeam",
                "parameters": [path_param("team_id", "Team id.")],
                "requestBody": json_body("Updated team properties.", TEAM_SCHEMA),
                "responses": {"200": response("Team updated."), "400": response("Validation error.")},
            },
            "delete": {
                "tags": ["teams"],
                "summary": "Remove team",
                "description": (
                    "Removes a team from management UI by soft-deleting the team and all "
                    "non-historical resources under it: rotations, alert routes, notification "
                    "channels and silences. Rotation members, overrides, team memberships and "
                    "route-channel links are deleted. Historical alerts are preserved."
                ),
                "operationId": "removeTeam",
                "responses": {
                    "200": response(
                        "Team removed.",
                        {
                            "type": "object",
                            "properties": {
                                "deleted": {"type": "boolean"},
                                "id": {"type": "integer"},
                            },
                        },
                    ),
                    "403": response("Access denied."),
                    "404": response("Team not found."),
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
                "responses": {"200": response("List of team users.")},
            },
            "post": {
                "tags": ["teams"],
                "summary": "Add user to team",
                "description": "Adds an existing user to a team. This is separate from rotation membership.",
                "operationId": "addUserToTeam",
                "parameters": [path_param("team_id", "Team id.")],
                "requestBody": json_body(
                    "Team membership data.",
                    {
                        "type": "object",
                        "required": ["user_id"],
                        "properties": {
                            "user_id": {"type": "integer", "minimum": 1, "example": 1},
                            "role": {
                                "type": "string",
                                "enum": ["read_only", "rw"],
                                "default": "read_only",
                            },
                        },
                    },
                ),
                "responses": {"201": response("User added to team."), "400": response("Validation error.")},
            },
        },
        "/api/teams/users/{membership_id}": {
            "put": {
                "tags": ["teams"],
                "summary": "Update team membership",
                "description": (
                    "Updates team membership role and active flag. "
                    "Use active=true to enable a disabled team member."
                ),
                "operationId": "updateTeamUser",
                "parameters": [path_param("membership_id", "Team membership id.")],
                "requestBody": json_body(
                    "Updated team membership.",
                    TEAM_MEMBER_UPDATE_SCHEMA,
                ),
                "responses": {
                    "200": response("Team membership updated.", TEAM_MEMBER_SCHEMA),
                    "400": response("Validation error."),
                    "403": response("Access denied."),
                    "404": response("Membership not found."),
                },
            },
            "delete": {
                "tags": ["teams"],
                "summary": "Remove team member",
                "description": (
                    "Removes user from the team. "
                    "Backend also removes this user from rotations of the same team."
                ),
                "operationId": "removeTeamUser",
                "parameters": [path_param("membership_id", "Team membership id.")],
                "responses": {
                    "200": response(
                        "Team membership removed.",
                        {
                            "type": "object",
                            "properties": {
                                "deleted": {"type": "boolean"},
                                "id": {"type": "integer"},
                            },
                        },
                    ),
                    "403": response("Access denied."),
                    "404": response("Membership not found."),
                },
            },
        },
    }
