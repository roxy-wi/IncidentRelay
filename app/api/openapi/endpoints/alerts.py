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
            "name": "alerts",
            "description": (
                "Alert lifecycle endpoints. Alerts can be listed, inspected, acknowledged, resolved and audited "
                "through event history."
            ),
        }
    ]


def paths():
    """
    Return OpenAPI paths for alert endpoints.
    """

    return {
        "/api/alerts": {
            "get": {
                "tags": ["alerts"],
                "summary": "List alerts",
                "description": (
                    "Returns alerts sorted by last_seen_at. Supports filtering by team, status, source and severity. "
                    "Use this endpoint to verify that incoming webhooks were routed correctly."
                ),
                "operationId": "listAlerts",
                "parameters": [
                    query_param("team_id", "Filter alerts by team id.", {"type": "integer", "minimum": 1}),
                    query_param("status", "Filter by status: firing, acknowledged, resolved or silenced."),
                    query_param("source", "Filter by source: alertmanager, zabbix or webhook."),
                    query_param("severity", "Filter by severity label or payload value."),
                ],
                "responses": {"200": response("List of alerts.")},
            }
        },
        "/api/alerts/{alert_id}": {
            "get": {
                "tags": ["alerts"],
                "summary": "Get alert",
                "description": "Returns a single alert with labels, payload, route, team, assignee and status details.",
                "operationId": "getAlert",
                "parameters": [path_param("alert_id", "Alert id.")],
                "responses": {"200": response("Alert details."), "404": response("Alert not found.")},
            }
        },
        "/api/alerts/{alert_id}/ack": {
            "post": {
                "tags": ["alerts"],
                "summary": "Acknowledge alert",
                "description": (
                    "Marks an alert as acknowledged. Once acknowledged, reminder notifications stop for this alert. "
                    "Optionally pass user_id to record who acknowledged it."
                ),
                "operationId": "acknowledgeAlert",
                "parameters": [path_param("alert_id", "Alert id.")],
                "requestBody": json_body(
                    "Optional acknowledge user.",
                    {
                        "type": "object",
                        "properties": {
                            "user_id": {"type": "integer", "minimum": 1, "nullable": True},
                        },
                    },
                    required=False,
                ),
                "responses": {"200": response("Alert acknowledged."), "404": response("Alert not found.")},
            }
        },
        "/api/alerts/{alert_id}/resolve": {
            "post": {
                "tags": ["alerts"],
                "summary": "Resolve alert",
                "description": (
                    "Marks an alert as resolved and sends a resolved notification to the route channels. "
                    "Optionally pass user_id to record who resolved it."
                ),
                "operationId": "resolveAlert",
                "parameters": [path_param("alert_id", "Alert id.")],
                "requestBody": json_body(
                    "Optional resolve user.",
                    {
                        "type": "object",
                        "properties": {
                            "user_id": {"type": "integer", "minimum": 1, "nullable": True},
                        },
                    },
                    required=False,
                ),
                "responses": {"200": response("Alert resolved."), "404": response("Alert not found.")},
            }
        },
        "/api/alerts/{alert_id}/events": {
            "get": {
                "tags": ["alerts"],
                "summary": "List alert events",
                "description": (
                    "Returns alert history events. This is the main debug endpoint for notifications. "
                    "Failed notifications are stored as notification_failed, reminder_failed or escalation_failed events."
                ),
                "operationId": "listAlertEvents",
                "parameters": [path_param("alert_id", "Alert id.")],
                "responses": {"200": response("Alert event history.")},
            }
        },
    }
