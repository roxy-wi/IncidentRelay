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


SILENCE_SCHEMA = {
    "type": "object",
    "required": ["team_id", "name", "starts_at", "ends_at"],
    "properties": {
        "team_id": {"type": "integer", "minimum": 1},
        "name": {"type": "string", "example": "maintenance-window"},
        "reason": {"type": "string", "nullable": True, "example": "Planned maintenance"},
        "matchers": {
            "type": "object",
            "description": "Matcher object applied to normalized alerts.",
            "example": {"labels": {"host": "host1"}},
        },
        "starts_at": {"type": "string", "format": "date-time"},
        "ends_at": {"type": "string", "format": "date-time"},
        "created_by": {"type": "integer", "nullable": True},
        "enabled": {"type": "boolean", "default": True},
    },
}


def tags():
    """
    Return OpenAPI tags.
    """

    return [
        {
            "name": "silences",
            "description": "Temporary mute rules that suppress notifications for matching alerts.",
        }
    ]


def paths():
    """
    Return OpenAPI paths for silence endpoints.
    """

    return {
        "/api/silences": {
            "get": {
                "tags": ["silences"],
                "summary": "List silences",
                "description": "Returns silence rules. Optional team_id filters silences by team.",
                "operationId": "listSilences",
                "parameters": [query_param("team_id", "Filter silences by team id.", {"type": "integer", "minimum": 1})],
                "responses": {"200": response("List of silences.", {"type": "array", "items": SILENCE_SCHEMA})},
            },
            "post": {
                "tags": ["silences"],
                "summary": "Create silence",
                "description": (
                    "Creates a silence rule for a team. Matching firing alerts are stored as silenced and notifications "
                    "are not sent while the silence is active."
                ),
                "operationId": "createSilence",
                "requestBody": json_body("Silence properties.", SILENCE_SCHEMA),
                "responses": {"201": response("Silence created."), "400": response("Validation error.")},
            },
        },
        "/api/silences/{silence_id}": {
            "get": {
                "tags": ["silences"],
                "summary": "Get silence",
                "description": "Returns one silence rule by id.",
                "operationId": "getSilence",
                "parameters": [path_param("silence_id", "Silence id.")],
                "responses": {"200": response("Silence details.", SILENCE_SCHEMA)},
            },
            "put": {
                "tags": ["silences"],
                "summary": "Update silence",
                "description": "Updates silence time range, matchers, reason and enabled flag.",
                "operationId": "updateSilence",
                "parameters": [path_param("silence_id", "Silence id.")],
                "requestBody": json_body("Updated silence properties.", SILENCE_SCHEMA),
                "responses": {"200": response("Silence updated.")},
            },
            "delete": {
                "tags": ["silences"],
                "summary": "Disable silence",
                "description": "Soft-deletes a silence rule by setting enabled=false.",
                "operationId": "disableSilence",
                "parameters": [path_param("silence_id", "Silence id.")],
                "responses": {"200": response("Silence disabled.")},
            },
        },
    }
