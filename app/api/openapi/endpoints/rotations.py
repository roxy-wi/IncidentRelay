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


ROTATION_SCHEMA = {
    "type": "object",
    "required": ["team_id", "name", "start_at"],
    "properties": {
        "team_id": {"type": "integer", "minimum": 1, "description": "Owner team id."},
        "name": {"type": "string", "example": "infra-primary"},
        "description": {"type": "string", "nullable": True},
        "start_at": {"type": "string", "format": "date-time", "example": "2026-04-27T09:00:00"},
        "rotation_type": {
            "type": "string",
            "enum": ["daily", "weekly", "custom"],
            "description": "rotation mode.",
            "example": "daily",
        },
        "interval_value": {"type": "integer", "minimum": 1, "example": 1},
        "interval_unit": {"type": "string", "enum": ["minutes", "hours", "days", "weeks"], "example": "days"},
        "handoff_time": {"type": "string", "description": "Local handoff time in HH:MM format.", "example": "09:00"},
        "handoff_weekday": {"type": "integer", "nullable": True, "description": "Weekday for weekly handoff. Monday is 0.", "example": 0},
        "timezone": {"type": "string", "example": "UTC"},
        "duration_seconds": {"type": "integer", "nullable": True, "description": "Calculated or custom slot duration."},
        "reminder_interval_seconds": {"type": "integer", "minimum": 60, "default": 300, "description": "How often reminders are sent for unacknowledged alerts assigned to this rotation."},
        "enabled": {"type": "boolean", "default": True},
        "add_team_members": {
            "type": "boolean",
            "default": True,
            "description": "Add all active team members to the rotation after creation."
        },
    },
}

ROTATION_MEMBER_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "user_id": {"type": "integer", "minimum": 1},
        "username": {"type": "string", "readOnly": True},
        "display_name": {"type": "string", "nullable": True, "readOnly": True},
        "position": {"type": "integer", "minimum": 0},
        "active": {"type": "boolean", "default": True},
    },
}

ROTATION_MEMBER_UPDATE_SCHEMA = {
    "type": "object",
    "required": ["position", "active"],
    "properties": {
        "position": {"type": "integer", "minimum": 0},
        "active": {"type": "boolean", "default": True},
    },
}


def tags():
    """
    Return OpenAPI tags.
    """

    return [
        {
            "name": "rotations",
            "description": (
                "On-call rotations. A rotation belongs to one team and contains ordered members. "
                "Overrides can temporarily replace the calculated on-call user."
            ),
        }
    ]


def paths():
    """
    Return OpenAPI paths for rotation endpoints.
    """

    return {
        "/api/rotations": {
            "get": {
                "tags": ["rotations"],
                "summary": "List rotations",
                "description": "Returns rotations with current on-call users. Optional team_id filters the result.",
                "operationId": "listRotations",
                "parameters": [query_param("team_id", "Filter rotations by team id.", {"type": "integer", "minimum": 1})],
                "responses": {"200": response("List of rotations.", {"type": "array", "items": ROTATION_SCHEMA})},
            },
            "post": {
                "tags": ["rotations"],
                "summary": "Create rotation",
                "description": (
                    "Creates a rotation using daily, weekly or custom handoff settings. The service keeps calculating "
                    "future shifts automatically instead of materializing all future duties."
                ),
                "operationId": "createRotation",
                "requestBody": json_body("Rotation properties.", ROTATION_SCHEMA),
                "responses": {"201": response("Rotation created."), "400": response("Validation error.")},
            },
        },
        "/api/rotations/{rotation_id}": {
            "get": {
                "tags": ["rotations"],
                "summary": "Get rotation",
                "description": "Returns one rotation by id.",
                "operationId": "getRotation",
                "parameters": [path_param("rotation_id", "Rotation id.")],
                "responses": {"200": response("Rotation details.", ROTATION_SCHEMA)},
            },
            "put": {
                "tags": ["rotations"],
                "summary": "Update rotation",
                "description": "Updates rotation schedule settings, handoff time, reminder interval and timezone.",
                "operationId": "updateRotation",
                "parameters": [path_param("rotation_id", "Rotation id.")],
                "requestBody": json_body("Updated rotation properties.", ROTATION_SCHEMA),
                "responses": {"200": response("Rotation updated.")},
            },
            "delete": {
                "tags": ["rotations"],
                "summary": "Disable rotation",
                "description": "Soft-deletes a rotation by marking it disabled.",
                "operationId": "disableRotation",
                "parameters": [path_param("rotation_id", "Rotation id.")],
                "responses": {"200": response("Rotation disabled.")},
            },
        },
        "/api/rotations/{rotation_id}/members": {
            "get": {
                "tags": ["rotations"],
                "summary": "List rotation members",
                "description": "Returns ordered rotation members. The position controls the duty order.",
                "operationId": "listRotationMembers",
                "parameters": [path_param("rotation_id", "Rotation id.")],
                "responses": {"200": response("List of rotation members.")},
            },
            "post": {
                "tags": ["rotations"],
                "summary": "Add rotation member",
                "description": (
                    "Adds or reactivates a user in a rotation at a specific position. "
                    "The user must be an active member of the rotation's team."
                ),
                "operationId": "addRotationMember",
                "parameters": [path_param("rotation_id", "Rotation id.")],
                "requestBody": json_body(
                    "Rotation member properties.",
                    {
                        "type": "object",
                        "required": ["user_id", "position"],
                        "properties": {
                            "user_id": {"type": "integer", "minimum": 1},
                            "position": {"type": "integer", "minimum": 0},
                        },
                    },
                ),
                "responses": {"201": response("Member added.")},
            },
        },
        "/api/rotations/{rotation_id}/overrides": {
            "post": {
                "tags": ["rotations"],
                "summary": "Create rotation override",
                "description": (
                    "Creates a temporary override for a rotation. When an override is active, the selected user "
                    "is returned as current on-call instead of the calculated rotation member."
                ),
                "operationId": "createRotationOverride",
                "parameters": [path_param("rotation_id", "Rotation id.")],
                "requestBody": json_body(
                    "Override properties.",
                    {
                        "type": "object",
                        "required": ["user_id", "starts_at", "ends_at"],
                        "properties": {
                            "user_id": {"type": "integer", "minimum": 1},
                            "starts_at": {"type": "string", "format": "date-time"},
                            "ends_at": {"type": "string", "format": "date-time"},
                            "reason": {"type": "string", "nullable": True},
                        },
                    },
                ),
                "responses": {"201": response("Override created.")},
            },
        },
        "/api/rotations/overrides/{override_id}": {
            "delete": {
                "tags": ["rotations"],
                "summary": "Delete rotation override",
                "operationId": "deleteRotationOverride",
                "parameters": [path_param("override_id", "Rotation override id.")],
                "responses": {"200": response("Override deleted.")},
            },
        },
        "/api/rotations/members/{member_id}": {
            "put": {
                "tags": ["rotations"],
                "summary": "Update rotation member",
                "description": (
                    "Updates rotation member position and active flag. "
                    "Use active=true to enable a disabled rotation member."
                ),
                "operationId": "updateRotationMember",
                "parameters": [path_param("member_id", "Rotation member id.")],
                "requestBody": json_body(
                    "Updated rotation member.",
                    ROTATION_MEMBER_UPDATE_SCHEMA,
                ),
                "responses": {
                    "200": response("Rotation member updated.", ROTATION_MEMBER_SCHEMA),
                    "400": response("Validation error."),
                    "403": response("Access denied."),
                    "404": response("Rotation member not found."),
                },
            },
            "delete": {
                "tags": ["rotations"],
                "summary": "Remove rotation member",
                "description": "Permanently removes user from this rotation.",
                "operationId": "removeRotationMember",
                "parameters": [path_param("member_id", "Rotation member id.")],
                "responses": {
                    "200": response(
                        "Rotation member removed.",
                        {
                            "type": "object",
                            "properties": {
                                "deleted": {"type": "boolean"},
                                "id": {"type": "integer"},
                            },
                        },
                    ),
                    "403": response("Access denied."),
                    "404": response("Rotation member not found."),
                },
            },
        },
    }
