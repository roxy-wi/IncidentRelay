from app.api.openapi.common import ERROR_SCHEMA, query_param, response


MATCHER_SUGGESTION_VALUES_SCHEMA = {
    "type": "object",
    "additionalProperties": {
        "type": "array",
        "items": {"type": "string"},
    },
    "description": "Known matcher names mapped to recent observed values.",
}


MATCHER_SUGGESTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "team_id": {"type": "integer", "minimum": 1},
        "route_id": {"type": "integer", "minimum": 1, "nullable": True},
        "service_id": {"type": "integer", "minimum": 1, "nullable": True},
        "sample_size": {
            "type": "integer",
            "minimum": 0,
            "description": "Number of recent alerts included in the sample.",
        },
        "sample_limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
        },
        "values_limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 50,
        },
        "labels": MATCHER_SUGGESTION_VALUES_SCHEMA,
        "fields": MATCHER_SUGGESTION_VALUES_SCHEMA,
    },
}


def tags():
    return [
        {
            "name": "matchers",
            "description": (
                "Shared alert matcher tools and suggestions from recent alerts."
            ),
        }
    ]


def paths():
    return {
        "/api/matchers/suggestions": {
            "get": {
                "tags": ["matchers"],
                "summary": "List matcher suggestions",
                "description": (
                    "Returns known matcher names and recent values from alerts "
                    "visible to the selected team. Optional route_id and "
                    "service_id filters narrow the sample."
                ),
                "operationId": "listMatcherSuggestions",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    query_param(
                        "team_id",
                        "Team used for RBAC and alert sampling.",
                        {"type": "integer", "minimum": 1},
                        required=True,
                    ),
                    query_param(
                        "route_id",
                        "Optionally limit suggestions to alerts routed through "
                        "this route.",
                        {"type": "integer", "minimum": 1},
                    ),
                    query_param(
                        "service_id",
                        "Optionally limit suggestions to alerts assigned to "
                        "this service.",
                        {"type": "integer", "minimum": 1},
                    ),
                    query_param(
                        "limit",
                        "Maximum number of recent alerts to inspect.",
                        {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 500,
                            "default": 200,
                        },
                    ),
                    query_param(
                        "values_limit",
                        "Maximum number of observed values returned for each "
                        "matcher name.",
                        {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 50,
                            "default": 20,
                        },
                    ),
                ],
                "responses": {
                    "200": response("Matcher suggestions.", MATCHER_SUGGESTIONS_SCHEMA),
                    "400": response("team_id is missing or invalid.", ERROR_SCHEMA),
                    "401": response("Authentication is required.", ERROR_SCHEMA),
                    "403": response("Team access is denied.", ERROR_SCHEMA),
                },
            }
        }
    }
