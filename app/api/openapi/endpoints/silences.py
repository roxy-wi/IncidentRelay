from app.api.openapi.common import response, path_param, json_body, query_param


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
        "apply_to_existing": {
            "type": "boolean",
            "default": False,
            "description": (
                "When true, matching unresolved firing alerts are silenced "
                "when this Silence becomes active."
            ),
        },
        "reactivate_on_end": {
            "type": "boolean",
            "default": True,
            "description": (
                "When true, alerts affected by this Silence are reactivated "
                "after it expires or is disabled, unless another Silence applies."
            ),
        },
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
                "parameters": [
                    query_param(
                        "team_id",
                        "Filter silences by team id.",
                        {"type": "integer", "minimum": 1},
                    )
                ],
                "responses": {"200": response("List of silences.", {"type": "array", "items": SILENCE_SCHEMA})},
            },
            "post": {
                "tags": ["silences"],
                "summary": "Create silence",
                "description": (
                    "Creates a silence rule for a team. New matching alerts are stored as silenced. "
                    "Set apply_to_existing=true to also silence matching unresolved firing alerts. "
                    "Set reactivate_on_end=false to keep affected alerts silenced after the Silence ends."
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
                "description": "Updates Silence scope, time range, matchers and lifecycle behavior.",
                "operationId": "updateSilence",
                "parameters": [path_param("silence_id", "Silence id.")],
                "requestBody": json_body("Updated silence properties.", SILENCE_SCHEMA),
                "responses": {"200": response("Silence updated.")},
            },
            "delete": {
                "tags": ["silences"],
                "summary": "Disable silence",
                "description": (
                    "Disables a Silence. Affected alerts are reactivated when "
                    "reactivate_on_end is enabled and no other Silence applies."
                ),
                "operationId": "disableSilence",
                "parameters": [path_param("silence_id", "Silence id.")],
                "responses": {"200": response("Silence disabled.")},
            },
        },
        "/api/silences/{silence_id}/enable": {
            "post": {
                "tags": ["silences"],
                "summary": "Enable silence",
                "description": "Enables a Silence and immediately reconciles its configured lifecycle behavior.",
                "operationId": "enableSilence",
                "parameters": [path_param("silence_id", "Silence id.")],
                "responses": {"200": response("Silence enabled.", SILENCE_SCHEMA)},
            },
        },
    }
