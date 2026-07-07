from app.api.openapi.common import response, path_param, json_body, query_param

MAINTENANCE_BEHAVIORS = [
    "suppress_notifications",
    "suppress_incident",
    "create_maintenance_incident",
    "pause_escalation_only",
]

MAINTENANCE_STATUSES = [
    "scheduled",
    "active",
    "finished",
    "cancelled",
]

MAINTENANCE_SCOPE_TYPES = [
    "group",
    "team",
    "service",
    "route",
]


def date_time_property(description, nullable=False):
    """Build an OpenAPI date-time property."""
    schema = {
        "type": "string",
        "format": "date-time",
        "description": description,
    }

    if nullable:
        schema["nullable"] = True

    return schema


def error_schema():
    """Build a standard error response schema."""
    return {
        "type": "object",
        "properties": {
            "error": {"type": "string", "example": "validation_error"},
            "message": {"type": "string", "nullable": True},
            "details": {
                "type": "array",
                "nullable": True,
                "items": {"type": "object", "additionalProperties": True},
            },
        },
        "additionalProperties": True,
    }


def maintenance_scope_schema():
    """Build maintenance window scope response schema."""
    return {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "readOnly": True},
            "scope_type": {
                "type": "string",
                "enum": MAINTENANCE_SCOPE_TYPES,
            },
            "group_id": {"type": "integer", "nullable": True},
            "group_name": {"type": "string", "nullable": True},
            "team_id": {"type": "integer", "nullable": True},
            "team_name": {"type": "string", "nullable": True},
            "service_id": {"type": "integer", "nullable": True},
            "service_name": {"type": "string", "nullable": True},
            "route_id": {"type": "integer", "nullable": True},
            "route_name": {"type": "string", "nullable": True},
        },
    }


def maintenance_scope_request_schema():
    """Build maintenance window scope request schema."""
    return {
        "type": "object",
        "required": ["scope_type"],
        "additionalProperties": False,
        "properties": {
            "scope_type": {
                "type": "string",
                "enum": MAINTENANCE_SCOPE_TYPES,
                "description": "Scope kind affected by the maintenance window.",
            },
            "group_id": {
                "type": "integer",
                "nullable": True,
                "minimum": 1,
                "description": "Required when scope_type is group.",
            },
            "team_id": {
                "type": "integer",
                "nullable": True,
                "minimum": 1,
                "description": "Required when scope_type is team.",
            },
            "service_id": {
                "type": "integer",
                "nullable": True,
                "minimum": 1,
                "description": "Required when scope_type is service.",
            },
            "route_id": {
                "type": "integer",
                "nullable": True,
                "minimum": 1,
                "description": "Required when scope_type is route.",
            },
        },
    }


def maintenance_window_schema():
    """Build maintenance window response schema."""
    return {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "readOnly": True},
            "group_id": {"type": "integer", "nullable": True},
            "team_id": {"type": "integer", "nullable": True},
            "name": {"type": "string"},
            "description": {"type": "string", "nullable": True},
            "status": {
                "type": "string",
                "enum": MAINTENANCE_STATUSES,
                "description": "Effective status calculated from starts_at, ends_at and timezone.",
            },
            "stored_status": {
                "type": "string",
                "nullable": True,
                "description": "Status stored in the database before dynamic calculation.",
            },
            "behavior": {
                "type": "string",
                "enum": MAINTENANCE_BEHAVIORS,
            },
            "timezone": {
                "type": "string",
                "example": "Europe/Moscow",
            },
            "rrule": {
                "type": "string",
                "nullable": True,
                "description": "Optional RFC5545 RRULE string for recurring windows.",
                "example": "FREQ=WEEKLY;BYDAY=MO",
            },
            "starts_at": date_time_property(
                "Maintenance start as wall-clock time in the selected timezone."
            ),
            "ends_at": date_time_property(
                "Maintenance end as wall-clock time in the selected timezone."
            ),
            "occurrence": maintenance_window_occurrence_schema(),
            "enabled": {"type": "boolean"},
            "deleted": {"type": "boolean"},
            "cancelled_by_id": {"type": "integer", "nullable": True},
            "cancelled_at": date_time_property(
                "Cancellation timestamp.",
                nullable=True,
            ),
            "cancel_reason": {"type": "string", "nullable": True},
            "created_at": date_time_property("Creation timestamp.", nullable=True),
            "updated_at": date_time_property("Last update timestamp.", nullable=True),
            "scopes": {
                "type": "array",
                "items": maintenance_scope_schema(),
            },
        },
        "additionalProperties": True,
    }


def maintenance_window_list_schema():
    """Build maintenance window list response schema."""
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": maintenance_window_schema(),
            },
        },
    }


def maintenance_window_request_schema():
    """Build create or update maintenance window request schema."""
    return {
        "type": "object",
        "required": [
            "name",
            "behavior",
            "starts_at",
            "ends_at",
            "timezone",
            "scopes",
        ],
        "additionalProperties": False,
        "properties": {
            "name": {
                "type": "string",
                "minLength": 1,
                "maxLength": 255,
                "example": "Payments deploy",
            },
            "description": {
                "type": "string",
                "nullable": True,
                "maxLength": 2000,
                "example": "Planned deployment for payments services.",
            },
            "behavior": {
                "type": "string",
                "enum": MAINTENANCE_BEHAVIORS,
                "default": "suppress_notifications",
            },
            "timezone": {
                "type": "string",
                "default": "UTC",
                "example": "Europe/Moscow",
            },
            "rrule": {
                "type": "string",
                "nullable": True,
                "description": "Optional RFC5545 RRULE string.",
                "example": "FREQ=WEEKLY;BYDAY=MO",
            },
            "starts_at": {
                "type": "string",
                "format": "date-time",
                "description": (
                    "Wall-clock start time in the selected timezone. "
                    "Do not convert datetime-local values to UTC before sending."
                ),
                "example": "2026-06-07T07:52:00",
            },
            "ends_at": {
                "type": "string",
                "format": "date-time",
                "description": (
                    "Wall-clock end time in the selected timezone. "
                    "Do not convert datetime-local values to UTC before sending."
                ),
                "example": "2026-06-07T11:37:00",
            },
            "enabled": {
                "type": "boolean",
                "default": True,
            },
            "scopes": {
                "type": "array",
                "minItems": 1,
                "items": maintenance_scope_request_schema(),
            },
        },
    }


def cancel_maintenance_window_request_schema():
    """Build cancel maintenance window request schema."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "reason": {
                "type": "string",
                "nullable": True,
                "maxLength": 2000,
                "example": "Deployment postponed.",
            },
        },
    }


def delete_response_schema():
    """Build delete response schema."""
    return {
        "type": "object",
        "properties": {
            "deleted": {"type": "boolean", "example": True},
            "id": {"type": "integer", "example": 1},
        },
    }


def maintenance_window_occurrence_schema():
    """Build maintenance window occurrence response schema."""
    return {
        "type": "object",
        "nullable": True,
        "properties": {
            "status": {
                "type": "string",
                "enum": MAINTENANCE_STATUSES,
            },
            "starts_at": date_time_property(
                "Current or next occurrence start time.",
                nullable=True,
            ),
            "ends_at": date_time_property(
                "Current or next occurrence end time.",
                nullable=True,
            ),
            "timezone": {
                "type": "string",
                "nullable": True,
                "example": "Europe/Moscow",
            },
            "recurring": {
                "type": "boolean",
                "description": "Whether this occurrence comes from RRULE.",
            },
        },
    }


def bearer_security():
    """Return bearer auth security requirement."""
    return [{"bearerAuth": []}]


def tags():
    """Return OpenAPI tags."""
    return [
        {
            "name": "maintenance windows",
            "description": (
                "Maintenance window endpoints. Maintenance windows can suppress "
                "notifications, suppress incident creation, create maintenance "
                "incidents, or pause escalations for groups, teams, services or routes."
            ),
        }
    ]


def paths():
    """Return OpenAPI paths for maintenance window endpoints."""
    return {
        "/api/maintenance-windows": {
            "get": {
                "tags": ["maintenance windows"],
                "summary": "List maintenance windows",
                "description": (
                    "Returns maintenance windows visible to the current user. "
                    "The status field is calculated dynamically from starts_at, "
                    "ends_at and timezone."
                ),
                "operationId": "listMaintenanceWindows",
                "security": bearer_security(),
                "parameters": [
                    query_param(
                        "include_finished",
                        "Set to 1 to include finished maintenance windows.",
                        {"type": "string", "enum": ["0", "1"], "default": "0"},
                    ),
                    query_param(
                        "team_id",
                        "Filter by team id.",
                        {"type": "integer", "minimum": 1},
                    ),
                    query_param(
                        "service_id",
                        "Filter by service id.",
                        {"type": "integer", "minimum": 1},
                    ),
                    query_param(
                        "route_id",
                        "Filter by route id.",
                        {"type": "integer", "minimum": 1},
                    ),
                ],
                "responses": {
                    "200": response(
                        "Maintenance window list.",
                        maintenance_window_list_schema(),
                    ),
                    "401": response("Authentication required.", error_schema()),
                    "403": response("Access denied.", error_schema()),
                },
            },
            "post": {
                "tags": ["maintenance windows"],
                "summary": "Create maintenance window",
                "description": (
                    "Creates a maintenance window for group, team, service or route scope. "
                    "starts_at and ends_at are treated as wall-clock values in the selected timezone."
                ),
                "operationId": "createMaintenanceWindow",
                "security": bearer_security(),
                "requestBody": json_body(
                    "Maintenance window payload.",
                    maintenance_window_request_schema(),
                ),
                "responses": {
                    "201": response(
                        "Maintenance window created.",
                        maintenance_window_schema(),
                    ),
                    "400": response("Invalid request.", error_schema()),
                    "401": response("Authentication required.", error_schema()),
                    "403": response("Access denied.", error_schema()),
                },
            },
        },
        "/api/maintenance-windows/{window_id}": {
            "get": {
                "tags": ["maintenance windows"],
                "summary": "Get maintenance window",
                "operationId": "getMaintenanceWindow",
                "security": bearer_security(),
                "parameters": [
                    path_param("window_id", "Maintenance window id."),
                ],
                "responses": {
                    "200": response(
                        "Maintenance window details.",
                        maintenance_window_schema(),
                    ),
                    "401": response("Authentication required.", error_schema()),
                    "403": response("Access denied.", error_schema()),
                    "404": response("Maintenance window not found.", error_schema()),
                },
            },
            "put": {
                "tags": ["maintenance windows"],
                "summary": "Update maintenance window",
                "description": (
                    "Updates a maintenance window and replaces its scopes when scopes are provided."
                ),
                "operationId": "updateMaintenanceWindow",
                "security": bearer_security(),
                "parameters": [
                    path_param("window_id", "Maintenance window id."),
                ],
                "requestBody": json_body(
                    "Maintenance window payload.",
                    maintenance_window_request_schema(),
                ),
                "responses": {
                    "200": response(
                        "Maintenance window updated.",
                        maintenance_window_schema(),
                    ),
                    "400": response("Invalid request.", error_schema()),
                    "401": response("Authentication required.", error_schema()),
                    "403": response("Access denied.", error_schema()),
                    "404": response("Maintenance window not found.", error_schema()),
                },
            },
            "delete": {
                "tags": ["maintenance windows"],
                "summary": "Delete maintenance window",
                "description": "Soft-deletes a maintenance window.",
                "operationId": "deleteMaintenanceWindow",
                "security": bearer_security(),
                "parameters": [
                    path_param("window_id", "Maintenance window id."),
                ],
                "responses": {
                    "200": response(
                        "Maintenance window deleted.",
                        delete_response_schema(),
                    ),
                    "401": response("Authentication required.", error_schema()),
                    "403": response("Access denied.", error_schema()),
                    "404": response("Maintenance window not found.", error_schema()),
                },
            },
        },
        "/api/maintenance-windows/{window_id}/cancel": {
            "post": {
                "tags": ["maintenance windows"],
                "summary": "Cancel maintenance window",
                "description": (
                    "Marks a maintenance window as cancelled and stores an optional cancel reason."
                ),
                "operationId": "cancelMaintenanceWindow",
                "security": bearer_security(),
                "parameters": [
                    path_param("window_id", "Maintenance window id."),
                ],
                "requestBody": json_body(
                    "Optional cancellation reason.",
                    cancel_maintenance_window_request_schema(),
                    required=False,
                ),
                "responses": {
                    "200": response(
                        "Maintenance window cancelled.",
                        maintenance_window_schema(),
                    ),
                    "400": response("Invalid request.", error_schema()),
                    "401": response("Authentication required.", error_schema()),
                    "403": response("Access denied.", error_schema()),
                    "404": response("Maintenance window not found.", error_schema()),
                },
            },
        },
    }
