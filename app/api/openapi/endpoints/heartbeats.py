from app.api.openapi.common import json_body, path_param, query_param, response

def tags():
    return [{"name": "Heartbeats", "description": "Dead-man-switch checks that page when expected pings stop."}]


HEARTBEAT_INSTANCE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "heartbeat_id": {"type": "integer"},
        "instance_key": {"type": "string"},
        "status": {"type": "string", "enum": ["new", "ok", "overdue", "paused"]},
        "enabled": {"type": "boolean"},
        "auto_discovered": {"type": "boolean"},
        "last_seen_at": {"type": "string", "format": "date-time", "nullable": True},
        "next_expected_at": {"type": "string", "format": "date-time", "nullable": True},
        "deadline_at": {"type": "string", "format": "date-time", "nullable": True},
        "current_alert_group_id": {"type": "integer", "nullable": True},
    },
}


HEARTBEAT_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "uid": {"type": "string", "format": "uuid"},
        "name": {"type": "string"},
        "slug": {"type": "string"},
        "team_id": {"type": "integer"},
        "route_id": {"type": "integer"},
        "service_id": {"type": "integer", "nullable": True},
        "mode": {"type": "string", "enum": ["interval", "scheduled"]},
        "status": {"type": "string", "enum": ["new", "ok", "overdue", "paused"]},
        "expected_interval_seconds": {"type": "integer", "nullable": True},
        "grace_period_seconds": {"type": "integer"},
        "schedule_kind": {"type": "string", "nullable": True, "enum": ["daily", "weekly", "monthly"]},
        "schedule_time": {"type": "string", "nullable": True},
        "timezone": {"type": "string"},
        "last_seen_at": {"type": "string", "format": "date-time", "nullable": True},
        "next_expected_at": {"type": "string", "format": "date-time", "nullable": True},
        "deadline_at": {"type": "string", "format": "date-time", "nullable": True},
        "current_alert_group_id": {"type": "integer", "nullable": True},
        "instance_tracking_enabled": {"type": "boolean"},
        "instance_key": {"type": "string"},
        "expected_instances_mode": {"type": "string", "enum": ["none", "static", "auto"]},
        "auto_discovery_ttl_days": {"type": "integer", "nullable": True},
        "instance_summary": {"type": "object"},
        "instances": {"type": "array", "items": HEARTBEAT_INSTANCE_SCHEMA},
        "ping_url": {"type": "string", "nullable": True},
    },
}

HEARTBEAT_INPUT_SCHEMA = {
    "type": "object",
    "required": ["team_id", "route_id", "name", "slug", "mode"],
    "properties": {
        "team_id": {"type": "integer", "minimum": 1},
        "route_id": {"type": "integer", "minimum": 1, "description": "Route with source=heartbeat."},
        "service_id": {"type": "integer", "minimum": 1, "nullable": True},
        "name": {"type": "string"},
        "slug": {"type": "string"},
        "description": {"type": "string", "nullable": True},
        "mode": {"type": "string", "enum": ["interval", "scheduled"]},
        "expected_interval_seconds": {"type": "integer", "nullable": True},
        "grace_period_seconds": {"type": "integer"},
        "schedule_kind": {"type": "string", "nullable": True, "enum": ["daily", "weekly", "monthly"]},
        "schedule_time": {"type": "string", "nullable": True, "example": "03:00"},
        "schedule_weekday": {"type": "integer", "nullable": True, "minimum": 0, "maximum": 6},
        "schedule_monthday": {"type": "integer", "nullable": True, "minimum": 1, "maximum": 31},
        "timezone": {"type": "string", "default": "UTC"},
        "severity": {"type": "string", "default": "critical"},
        "priority_slug": {"type": "string", "default": "p2"},
        "enabled": {"type": "boolean"},
        "auto_resolve": {"type": "boolean"},
        "instance_tracking_enabled": {"type": "boolean", "default": False},
        "instance_key": {"type": "string", "default": "instance"},
        "expected_instances_mode": {"type": "string", "enum": ["none", "static", "auto"], "default": "none"},
        "expected_instances": {"type": "array", "items": {"type": "string"}},
        "auto_discovery_ttl_days": {"type": "integer", "nullable": True, "default": 30},
        "labels": {"type": "object"},
        "metadata": {"type": "object"},
    },
}


def paths():
    return {
        "/api/heartbeats": {
            "get": {
                "tags": ["Heartbeats"],
                "summary": "List heartbeats",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    query_param("team_id", "Filter by team id", {"type": "integer"}),
                    query_param("status", "Filter by heartbeat status"),
                    query_param("enabled", "Set true to return enabled checks only", {"type": "boolean"}),
                ],
                "responses": {"200": response("Heartbeat checks", {"type": "array", "items": HEARTBEAT_SCHEMA})},
            },
            "post": {
                "tags": ["Heartbeats"],
                "summary": "Create heartbeat",
                "security": [{"bearerAuth": []}],
                "requestBody": json_body("Heartbeat definition", HEARTBEAT_INPUT_SCHEMA),
                "responses": {"201": response("Created heartbeat. Includes one-time token and ping_url.", HEARTBEAT_SCHEMA)},
            },
        },
        "/api/heartbeats/{heartbeat_id}": {
            "get": {
                "tags": ["Heartbeats"],
                "summary": "Get heartbeat details",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("heartbeat_id", "Heartbeat id")],
                "responses": {"200": response("Heartbeat details", HEARTBEAT_SCHEMA)},
            },
            "put": {
                "tags": ["Heartbeats"],
                "summary": "Update heartbeat",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("heartbeat_id", "Heartbeat id")],
                "requestBody": json_body("Heartbeat definition", HEARTBEAT_INPUT_SCHEMA),
                "responses": {"200": response("Updated heartbeat", HEARTBEAT_SCHEMA)},
            },
            "delete": {
                "tags": ["Heartbeats"],
                "summary": "Delete heartbeat",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("heartbeat_id", "Heartbeat id")],
                "responses": {"200": response("Deleted")},
            },
        },
        "/api/heartbeats/{heartbeat_id}/instances": {
            "get": {
                "tags": ["Heartbeats"],
                "summary": "List heartbeat instances",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("heartbeat_id", "Heartbeat id")],
                "responses": {"200": response("Heartbeat instances", {"type": "array", "items": HEARTBEAT_INSTANCE_SCHEMA})},
            }
        },
        "/api/heartbeats/{heartbeat_id}/instances/{instance_id}/disable": {
            "post": {
                "tags": ["Heartbeats"],
                "summary": "Disable heartbeat instance",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("heartbeat_id", "Heartbeat id"),
                    path_param("instance_id", "Instance id"),
                ],
                "responses": {"200": response("Disabled heartbeat instance", HEARTBEAT_INSTANCE_SCHEMA)},
            }
        },
        "/api/heartbeats/{heartbeat_id}/regenerate-token": {
            "post": {
                "tags": ["Heartbeats"],
                "summary": "Regenerate heartbeat token",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("heartbeat_id", "Heartbeat id")],
                "responses": {"200": response("Heartbeat with a new one-time token", HEARTBEAT_SCHEMA)},
            }
        },
        "/api/heartbeats/{heartbeat_id}/pause": {
            "post": {
                "tags": ["Heartbeats"],
                "summary": "Pause heartbeat overdue checks",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("heartbeat_id", "Heartbeat id")],
                "responses": {"200": response("Paused heartbeat", HEARTBEAT_SCHEMA)},
            }
        },
        "/api/heartbeats/{heartbeat_id}/resume": {
            "post": {
                "tags": ["Heartbeats"],
                "summary": "Resume heartbeat overdue checks",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("heartbeat_id", "Heartbeat id")],
                "responses": {"200": response("Resumed heartbeat", HEARTBEAT_SCHEMA)},
            }
        },
        "/api/heartbeats/ping/{token}": {
            "get": {
                "tags": ["Heartbeats"],
                "summary": "Receive heartbeat ping",
                "parameters": [{"name": "token", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": response("Ping accepted")},
            },
            "post": {
                "tags": ["Heartbeats"],
                "summary": "Receive heartbeat ping with optional payload",
                "parameters": [{"name": "token", "in": "path", "required": True, "schema": {"type": "string"}}],
                "requestBody": json_body("Optional ping payload", {"type": "object"}, required=False),
                "responses": {"200": response("Ping accepted")},
            },
        },
    }
