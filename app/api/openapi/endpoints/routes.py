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


SOURCE_SCHEMA_WITH_SENTRY = {
    "type": "string",
    "enum": ["alertmanager", "zabbix", "webhook", "sentry", "librenms"],
    "description": "Incoming alert source type.",
}

ROUTE_INTEGRATION_CONFIG_SCHEMA = {
    "type": "object",
    "description": (
        "Provider-specific route integration settings. "
        "For source=sentry this stores the Sentry Client Secret write-only "
        "and returns safe read-only status fields."
    ),
    "additionalProperties": True,
    "properties": {
        "sentry": {
            "type": "object",
            "description": "Sentry-specific route integration settings.",
            "additionalProperties": False,
            "properties": {
                "webhook_secret": {
                    "type": "string",
                    "writeOnly": True,
                    "nullable": True,
                    "description": (
                        "Sentry Internal Integration Client Secret. "
                        "Only accepted on create/update. Never returned by the API. "
                        "When updating an existing Sentry route, omit or send empty value "
                        "to keep the current secret."
                    ),
                    "example": "sntrys_client_secret_value",
                },
                "has_webhook_secret": {
                    "type": "boolean",
                    "readOnly": True,
                    "description": "Whether a Sentry webhook secret is configured for this route.",
                    "example": True,
                },
                "webhook_path": {
                    "type": "string",
                    "readOnly": True,
                    "description": "Route-scoped Sentry webhook path.",
                    "example": "/api/integrations/sentry/42",
                },
            },
        }
    },
    "example": {
        "sentry": {
            "webhook_secret": "sntrys_client_secret_value"
        }
    },
}

CREATE_ROUTE_DESCRIPTION = (
    "Creates an alert route. Incoming alerts match routes by source and matchers. "
    "When a route matches, the alert is assigned to the route rotation or escalation policy "
    "and sent to route channels. For source=sentry, the response includes "
    "integration_config.sentry.webhook_path; configure that URL in Sentry Internal Integration "
    "and store the Sentry Client Secret in integration_config.sentry.webhook_secret."
)

ROUTE_SCHEMA = {
    "type": "object",
    "required": ["team_id", "name", "source"],
    "properties": {
        "team_id": {"type": "integer", "minimum": 1},
        "name": {"type": "string", "example": "infra-alertmanager"},
        "source": {"type": "string", "enum": ["alertmanager", "zabbix", "webhook"]},
        "rotation_id": {"type": "integer", "nullable": True, "description": "Rotation that receives alerts for this route."},
        "service_id": {
            "type": "integer",
            "nullable": True,
            "minimum": 1,
            "description": (
                "Default service associated with this route. "
                "Service match rules can override it for individual alerts."
            ),
        },
        "service_name": {
            "type": "string",
            "nullable": True,
            "readOnly": True,
            "description": "Human-readable default service name.",
        },
        "service_slug": {
            "type": "string",
            "nullable": True,
            "readOnly": True,
            "description": "Default service slug.",
        },
        "channel_ids": {
            "type": "array",
            "items": {"type": "integer"},
            "description": (
                "Channels configured directly on this route. They are used in route_only and service_policy_plus_route modes."
            ),
        },
        "notification_channel_mode": {
            "type": "string",
            "enum": [
                "route_only",
                "service_policy",
                "service_policy_plus_route",
            ],
            "default": "route_only",
            "description": (
                "Selects whether shared notifications use route channels, the matched service notification policy, or both."
            ),
        },
        "matchers": {
            "type": "object",
            "description": "Matcher object. Example: {'labels': {'team': 'infra'}, 'severity': 'critical'}",
            "example": {"labels": {"team": "infra"}},
        },
        "group_by": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
            "description": (
                "Label names used for alert grouping. Leave empty to keep each dedup key "
                "in its own group. If any configured grouping value is missing from an alert, "
                "the alert dedup key is added to the group key to avoid merging unrelated alerts."
            ),
            "example": ["alertname", "instance"],
        },
        "enabled": {"type": "boolean", "default": True},
        "intake_token_prefix": {"type": "string", "nullable": True, "readOnly": True},
        "has_intake_token": {"type": "boolean", "readOnly": True},
        "channels": {
            "type": "array",
            "readOnly": True,
            "items": {"type": "object"},
        },
        "intake_token": {
            "type": "string",
            "readOnly": True,
            "description": "Returned only on route creation and token regeneration. Used by Alertmanager, Zabbix and Generic Webhook routes as bearer intake token.",
        },
        "escalation_policy_id": {
            "type": "integer",
            "nullable": True,
            "description": (
                "Escalation policy used by this route. "
                "When set, rotation_id should be null and team reminder-based escalation is ignored."
            ),
        },
        "escalation_policy_name": {
            "type": "string",
            "nullable": True,
            "readOnly": True,
            "description": "Human-readable policy name.",
        },
        "escalation_mode": {
            "type": "string",
            "readOnly": True,
            "enum": ["rotation", "policy"],
            "description": "Route escalation mode.",
        },
        "team_escalation_enabled": {
            "type": "boolean",
            "nullable": True,
            "readOnly": True,
            "description": "Team simple rotation escalation flag.",
        },
        "team_escalation_after_reminders": {
            "type": "integer",
            "nullable": True,
            "readOnly": True,
            "description": "Team simple rotation escalation threshold.",
        },
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
                "description": CREATE_ROUTE_DESCRIPTION,
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
                "summary": "Delete route",
                "description": (
                    "Soft-deletes a route by setting deleted=true and enabled=false. "
                    "Deleted routes are hidden from active route lists. Existing alerts "
                    "keep their route reference."
                ),
                "operationId": "deleteRoute",
                "parameters": [path_param("route_id", "Route id.")],
                "responses": {
                    "200": response(
                        "Route deleted.",
                        {
                            "type": "object",
                            "properties": {
                                "deleted": {"type": "boolean", "example": True},
                                "id": {"type": "integer", "example": 1},
                                "name": {"type": "string", "example": "infra-alertmanager"},
                            },
                        },
                    ),
                    "403": response("Access denied."),
                    "404": response("Route not found."),
                },
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
        "/api/routes/{route_id}/intake-token": {
            "post": {
                "tags": ["routes"],
                "summary": "Regenerate route intake token",
                "description": (
                    "Generates a new route intake token. "
                    "The full token is returned only in this response."
                ),
                "operationId": "regenerateRouteIntakeToken",
                "parameters": [path_param("route_id", "Route id.")],
                "responses": {
                    "200": response(
                        "New route intake token returned.",
                        {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer"},
                                "intake_token": {"type": "string"},
                                "intake_token_prefix": {"type": "string"},
                                "has_intake_token": {"type": "boolean"},
                            },
                        },
                    )
                },
            }
        },
        "/api/routes/{route_id}/disable": {
            "post": {
                "tags": ["routes"],
                "summary": "Disable route",
                "description": (
                    "Disables a route by setting enabled=false. "
                    "The route stays visible and can be enabled again."
                ),
                "operationId": "disableRoute",
                "parameters": [path_param("route_id", "Route id.")],
                "responses": {
                    "200": response("Route disabled.", ROUTE_SCHEMA),
                    "403": response("Access denied."),
                    "404": response("Route not found."),
                },
            },
        },
        "/api/routes/{route_id}/enable": {
            "post": {
                "tags": ["routes"],
                "summary": "Enable route",
                "description": "Enables a previously disabled route by setting enabled=true.",
                "operationId": "enableRoute",
                "parameters": [path_param("route_id", "Route id.")],
                "responses": {
                    "200": response("Route enabled.", ROUTE_SCHEMA),
                    "403": response("Access denied."),
                    "404": response("Route not found."),
                },
            },
        },
    }
