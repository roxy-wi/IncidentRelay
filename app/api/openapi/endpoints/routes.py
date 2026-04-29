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


ROUTE_SCHEMA = {
    "type": "object",
    "required": ["team_id", "name", "source"],
    "properties": {
        "team_id": {"type": "integer", "minimum": 1},
        "name": {"type": "string", "example": "infra-alertmanager"},
        "source": {"type": "string", "enum": ["alertmanager", "zabbix", "webhook"]},
        "rotation_id": {"type": "integer", "nullable": True, "description": "Rotation that receives alerts for this route."},
        "channel_ids": {"type": "array", "items": {"type": "integer"}, "description": "Notification channels used by this route."},
        "matchers": {
            "type": "object",
            "description": "Matcher object. Example: {'labels': {'team': 'infra'}, 'severity': 'critical'}",
            "example": {"labels": {"team": "infra"}},
        },
        "group_by": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Label names used for alert grouping.",
            "example": ["alertname", "instance"],
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
            "name": "routes",
            "description": (
                "Alert routes connect incoming alert sources to teams, rotations and channels. "
                "This is where rotation-to-channel delivery is configured."
            ),
        }
    ]


def paths():
    """
    Return OpenAPI paths for route endpoints.
    """

    return {
        "/api/routes": {
            "get": {
                "tags": ["routes"],
                "summary": "List routes",
                "description": "Returns alert routes, including attached channels. Optional team_id filters routes by team.",
                "operationId": "listRoutes",
                "parameters": [query_param("team_id", "Filter routes by team id.", {"type": "integer", "minimum": 1})],
                "responses": {"200": response("List of routes.", {"type": "array", "items": ROUTE_SCHEMA})},
            },
            "post": {
                "tags": ["routes"],
                "summary": "Create route",
                "description": (
                    "Creates an alert route. Incoming alerts match routes by source and matchers. "
                    "When a route matches, the alert is assigned to the route rotation and sent to route channels."
                ),
                "operationId": "createRoute",
                "requestBody": json_body("Route properties.", ROUTE_SCHEMA),
                "responses": {"201": response("Route created."), "400": response("Validation error.")},
            },
        },
        "/api/routes/{route_id}": {
            "get": {
                "tags": ["routes"],
                "summary": "Get route",
                "description": "Returns one alert route by id, including selected channels.",
                "operationId": "getRoute",
                "parameters": [path_param("route_id", "Route id.")],
                "responses": {"200": response("Route details.", ROUTE_SCHEMA)},
            },
            "put": {
                "tags": ["routes"],
                "summary": "Update route",
                "description": "Updates route source, rotation, matchers, grouping and enabled flag.",
                "operationId": "updateRoute",
                "parameters": [path_param("route_id", "Route id.")],
                "requestBody": json_body("Updated route properties.", ROUTE_SCHEMA),
                "responses": {"200": response("Route updated.")},
            },
            "delete": {
                "tags": ["routes"],
                "summary": "Disable route",
                "description": "Soft-deletes a route by setting enabled=false. Existing alerts keep their route reference.",
                "operationId": "disableRoute",
                "parameters": [path_param("route_id", "Route id.")],
                "responses": {"200": response("Route disabled.")},
            },
        },
        "/api/routes/{route_id}/channels": {
            "put": {
                "tags": ["routes"],
                "summary": "Replace route channels",
                "description": "Replaces the complete channel list for a route. This is used by the web UI multi-select.",
                "operationId": "replaceRouteChannels",
                "parameters": [path_param("route_id", "Route id.")],
                "requestBody": json_body(
                    "New channel list.",
                    {
                        "type": "object",
                        "required": ["channel_ids"],
                        "properties": {
                            "channel_ids": {"type": "array", "items": {"type": "integer"}},
                        },
                    },
                ),
                "responses": {"200": response("Route channels replaced.")},
            }
        },
        "/api/routes/{route_id}/channels/{channel_id}": {
            "post": {
                "tags": ["routes"],
                "summary": "Attach channel to route",
                "description": "Adds one channel to a route without replacing existing channels.",
                "operationId": "attachChannelToRoute",
                "parameters": [
                    path_param("route_id", "Route id."),
                    path_param("channel_id", "Channel id."),
                ],
                "responses": {"201": response("Channel attached.")},
            },
            "delete": {
                "tags": ["routes"],
                "summary": "Detach channel from route",
                "description": "Removes one channel from a route. The channel itself is not deleted.",
                "operationId": "detachChannelFromRoute",
                "parameters": [
                    path_param("route_id", "Route id."),
                    path_param("channel_id", "Channel id."),
                ],
                "responses": {"200": response("Channel detached.")},
            },
        },
    }
