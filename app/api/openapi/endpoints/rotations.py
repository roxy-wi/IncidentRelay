from app.api.openapi.common import response, path_param, json_body, query_param


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
        "reminder_interval_seconds": {"type": "integer", "minimum": 0, "default": 300, "description": "How often reminders are sent for unacknowledged alerts assigned to this rotation. 0 disables reminders. Otherwise, use 1 minute or more."},
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

ROTATION_LAYER_SCHEMA = {
    "type": "object",
    "required": ["name"],
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "rotation_id": {"type": "integer", "readOnly": True},
        "team_id": {"type": "integer", "readOnly": True},
        "name": {"type": "string", "example": "Business hours"},
        "description": {"type": "string", "nullable": True},
        "priority": {
            "type": "integer",
            "minimum": 0,
            "default": 0,
            "description": "Higher priority active layer wins.",
        },
        "start_at": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
            "example": "2026-05-22T09:00:00",
        },
        "rotation_type": {
            "type": "string",
            "enum": ["daily", "weekly", "custom"],
            "nullable": True,
            "example": "daily",
        },
        "interval_value": {"type": "integer", "minimum": 1, "nullable": True},
        "interval_unit": {
            "type": "string",
            "enum": ["minutes", "hours", "days", "weeks"],
            "nullable": True,
        },
        "handoff_time": {
            "type": "string",
            "nullable": True,
            "example": "09:00",
        },
        "handoff_weekday": {
            "type": "integer",
            "minimum": 0,
            "maximum": 6,
            "nullable": True,
            "description": "Monday is 0, Sunday is 6.",
        },
        "timezone": {
            "type": "string",
            "nullable": True,
            "example": "Europe/Berlin",
        },
        "duration_seconds": {
            "type": "integer",
            "minimum": 60,
            "nullable": True,
        },
        "enabled": {"type": "boolean", "default": True},
        "deleted": {"type": "boolean", "readOnly": True},
    },
}

ROTATION_LAYER_MEMBER_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "layer_id": {"type": "integer", "readOnly": True},
        "user_id": {"type": "integer", "minimum": 1},
        "username": {"type": "string", "readOnly": True},
        "display_name": {"type": "string", "nullable": True, "readOnly": True},
        "position": {"type": "integer", "minimum": 0},
        "active": {
            "type": "boolean",
            "description": "True while this membership period is open.",
            "default": True,
        },
        "starts_at": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
            "description": (
                "Membership period start. In API requests this value is interpreted "
                "as local time in the layer timezone when no timezone offset is provided."
            ),
            "example": "2026-06-10T09:00:00",
        },
        "ends_at": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
            "readOnly": True,
            "description": "Membership period end. Null means the member is still open.",
        },
    },
}


ROTATION_LAYER_MEMBER_ADD_SCHEMA = {
    "type": "object",
    "required": ["user_id", "position"],
    "properties": {
        "user_id": {
            "type": "integer",
            "minimum": 1,
            "description": "User id to add to the layer.",
        },
        "position": {
            "type": "integer",
            "minimum": 0,
            "description": "Position in the layer rotation order.",
        },
        "starts_at": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
            "description": (
                "When this user starts participating in this layer. "
                "If omitted, the user starts from the current time. "
                "Naive datetimes are interpreted in the layer timezone."
            ),
            "example": "2026-06-10T09:00:00",
        },
    },
}


ROTATION_LAYER_MEMBER_UPDATE_SCHEMA = {
    "type": "object",
    "required": ["position", "active"],
    "properties": {
        "position": {
            "type": "integer",
            "minimum": 0,
            "description": (
                "New position. Changing position closes the old membership period "
                "and creates a new one."
            ),
        },
        "active": {
            "type": "boolean",
            "default": True,
            "description": (
                "Use false to close this membership period. "
                "Re-adding the user should be done with POST and creates a new period."
            ),
        },
    },
}

ROTATION_LAYER_MEMBER_CREATE_SCHEMA = {
    "type": "object",
    "required": ["user_id", "position"],
    "properties": {
        "user_id": {"type": "integer", "minimum": 1},
        "position": {"type": "integer", "minimum": 0},
    },
}

ROTATION_LAYER_RESTRICTION_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "layer_id": {"type": "integer", "readOnly": True},
        "weekday": {
            "type": "integer",
            "minimum": 0,
            "maximum": 6,
            "nullable": True,
            "description": "Monday is 0. Null means every day.",
        },
        "start_time": {
            "type": "string",
            "example": "09:00",
            "description": "Local layer time in HH:MM.",
        },
        "end_time": {
            "type": "string",
            "example": "18:00",
            "description": "Local layer time in HH:MM. Same as start_time means full day.",
        },
    },
}

ROTATION_LAYER_RESTRICTIONS_REPLACE_SCHEMA = {
    "type": "object",
    "required": ["restrictions"],
    "properties": {
        "restrictions": {
            "type": "array",
            "items": ROTATION_LAYER_RESTRICTION_SCHEMA,
        },
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
        "/api/rotations/{rotation_id}/layers": {
            "get": {
                "tags": ["rotations"],
                "summary": "List rotation layers",
                "description": "Returns schedule layers for a rotation ordered by priority.",
                "operationId": "listRotationLayers",
                "parameters": [path_param("rotation_id", "Rotation id.")],
                "responses": {
                    "200": response(
                        "List of rotation layers.",
                        {"type": "array", "items": ROTATION_LAYER_SCHEMA},
                    ),
                    "403": response("Access denied."),
                    "404": response("Rotation not found."),
                },
            },
            "post": {
                "tags": ["rotations"],
                "summary": "Create rotation layer",
                "description": (
                    "Creates a schedule layer inside a rotation. "
                    "Layer restrictions decide when the layer is active."
                ),
                "operationId": "createRotationLayer",
                "parameters": [path_param("rotation_id", "Rotation id.")],
                "requestBody": json_body("Rotation layer properties.", ROTATION_LAYER_SCHEMA),
                "responses": {
                    "201": response("Rotation layer created.", ROTATION_LAYER_SCHEMA),
                    "400": response("Validation error."),
                    "403": response("Access denied."),
                    "404": response("Rotation not found."),
                },
            },
        },

        "/api/rotations/layers/{layer_id}": {
            "put": {
                "tags": ["rotations"],
                "summary": "Update rotation layer",
                "description": "Updates layer cadence, priority, timezone and enabled flag.",
                "operationId": "updateRotationLayer",
                "parameters": [path_param("layer_id", "Rotation layer id.")],
                "requestBody": json_body("Updated rotation layer.", ROTATION_LAYER_SCHEMA),
                "responses": {
                    "200": response("Rotation layer updated.", ROTATION_LAYER_SCHEMA),
                    "400": response("Validation error."),
                    "403": response("Access denied."),
                    "404": response("Layer not found."),
                },
            },
            "delete": {
                "tags": ["rotations"],
                "summary": "Delete rotation layer",
                "description": "Soft-deletes a rotation layer.",
                "operationId": "deleteRotationLayer",
                "parameters": [path_param("layer_id", "Rotation layer id.")],
                "responses": {
                    "200": response(
                        "Rotation layer deleted.",
                        {
                            "type": "object",
                            "properties": {
                                "deleted": {"type": "boolean"},
                                "id": {"type": "integer"},
                            },
                        },
                    ),
                    "403": response("Access denied."),
                    "404": response("Layer not found."),
                },
            },
        },

        "/api/rotations/layers/{layer_id}/members": {
            "get": {
                "tags": ["rotations"],
                "summary": "List rotation layer members",
                "description": (
                    "Returns open membership periods for a rotation layer. "
                    "Members with starts_at in the future are returned because they are already "
                    "configured, but they do not participate in on-call calculation until starts_at."
                ),
                "operationId": "listRotationLayerMembers",
                "parameters": [path_param("layer_id", "Rotation layer id.")],
                "responses": {
                    "200": response(
                        "List of open layer member periods.",
                        {
                            "type": "array",
                            "items": ROTATION_LAYER_MEMBER_SCHEMA,
                        },
                    ),
                    "403": response("Access denied."),
                    "404": response("Rotation layer not found."),
                },
            },
            "post": {
                "tags": ["rotations"],
                "summary": "Add rotation layer member",
                "description": (
                    "Adds a user to a rotation layer as a new membership period. "
                    "If starts_at is omitted, the user starts from the current time. "
                    "If starts_at is provided without timezone offset, it is interpreted "
                    "in the layer timezone. Re-adding a previously removed user creates "
                    "a new membership period and does not rewrite historical shifts."
                ),
                "operationId": "addRotationLayerMember",
                "parameters": [path_param("layer_id", "Rotation layer id.")],
                "requestBody": json_body(
                    "Layer member properties.",
                    ROTATION_LAYER_MEMBER_ADD_SCHEMA,
                ),
                "responses": {
                    "201": response("Layer member added.", ROTATION_LAYER_MEMBER_SCHEMA),
                    "400": response("Validation error or position conflict."),
                    "403": response("Access denied."),
                    "404": response("Rotation layer not found."),
                },
            },
        },

        "/api/rotations/layers/members/{member_id}": {
            "put": {
                "tags": ["rotations"],
                "summary": "Update rotation layer member",
                "description": (
                    "Updates a layer member period. Changing the position does not rewrite "
                    "history: the old period is closed and a new period is created. "
                    "Use active=false to remove a user from future shifts."
                ),
                "operationId": "updateRotationLayerMember",
                "parameters": [path_param("member_id", "Rotation layer member id.")],
                "requestBody": json_body(
                    "Updated layer member.",
                    ROTATION_LAYER_MEMBER_UPDATE_SCHEMA,
                ),
                "responses": {
                    "200": response(
                        "Layer member updated.",
                        ROTATION_LAYER_MEMBER_SCHEMA,
                    ),
                    "400": response("Validation error or position conflict."),
                    "403": response("Access denied."),
                    "404": response("Rotation layer member not found."),
                },
            },
            "delete": {
                "tags": ["rotations"],
                "summary": "Remove rotation layer member from future shifts",
                "description": (
                    "Closes the membership period instead of deleting it. "
                    "Past on-call shifts remain visible in the calendar. "
                    "To add the same user again, use POST /api/rotations/layers/{layer_id}/members."
                ),
                "operationId": "removeRotationLayerMember",
                "parameters": [path_param("member_id", "Rotation layer member id.")],
                "responses": {
                    "200": response(
                        "Layer member removed from future shifts.",
                        {
                            "type": "object",
                            "properties": {
                                "deleted": {"type": "boolean"},
                                "id": {"type": "integer"},
                            },
                        },
                    ),
                    "403": response("Access denied."),
                    "404": response("Rotation layer member not found."),
                },
            },
        },

        "/api/rotations/layers/{layer_id}/restrictions": {
            "get": {
                "tags": ["rotations"],
                "summary": "List rotation layer restrictions",
                "description": (
                    "Returns active windows for a layer. "
                    "When no restrictions exist, the layer is active 24/7."
                ),
                "operationId": "listRotationLayerRestrictions",
                "parameters": [path_param("layer_id", "Rotation layer id.")],
                "responses": {
                    "200": response(
                        "List of layer restrictions.",
                        {"type": "array", "items": ROTATION_LAYER_RESTRICTION_SCHEMA},
                    ),
                    "403": response("Access denied."),
                    "404": response("Layer not found."),
                },
            },
            "put": {
                "tags": ["rotations"],
                "summary": "Replace rotation layer restrictions",
                "description": (
                    "Replaces all active windows for a layer. "
                    "Times are interpreted in the layer timezone."
                ),
                "operationId": "replaceRotationLayerRestrictions",
                "parameters": [path_param("layer_id", "Rotation layer id.")],
                "requestBody": json_body(
                    "Restriction list.",
                    ROTATION_LAYER_RESTRICTIONS_REPLACE_SCHEMA,
                ),
                "responses": {
                    "200": response(
                        "Layer restrictions replaced.",
                        {"type": "array", "items": ROTATION_LAYER_RESTRICTION_SCHEMA},
                    ),
                    "400": response("Validation error."),
                    "403": response("Access denied."),
                    "404": response("Layer not found."),
                },
            },
        },
    }
