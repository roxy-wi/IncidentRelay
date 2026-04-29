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


def tags():
    """
    Return OpenAPI tags.
    """

    return [
        {
            "name": "calendar",
            "description": "Calendar view of future and current on-call duty per team.",
        }
    ]


def paths():
    """
    Return OpenAPI paths for calendar endpoints.
    """

    return {
        "/api/calendar": {
            "get": {
                "tags": ["calendar"],
                "summary": "Get team on-call calendar",
                "description": (
                    "Returns calculated calendar events for a team in a date range. The result includes rotation slots "
                    "and active overrides, so the web calendar shows the effective on-call schedule."
                ),
                "operationId": "getOnCallCalendar",
                "parameters": [
                    query_param("team_id", "Team id to build the calendar for.", {"type": "integer", "minimum": 1}, required=True),
                    query_param("start", "Start date or datetime, for example 2026-04-01.", {"type": "string"}),
                    query_param("end", "End date or datetime, for example 2026-05-01.", {"type": "string"}),
                ],
                "responses": {
                    "200": response(
                        "Calendar events.",
                        {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": {"type": "string"},
                                    "start": {"type": "string", "format": "date-time"},
                                    "end": {"type": "string", "format": "date-time"},
                                    "rotation_id": {"type": "integer"},
                                    "user_id": {"type": "integer"},
                                },
                            },
                        },
                    )
                },
            }
        }
    }
