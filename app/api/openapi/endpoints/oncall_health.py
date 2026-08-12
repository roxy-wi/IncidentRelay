from app.api.openapi.common import path_param, response

HEALTH_STATUSES = [
    "ok",
    "warning",
    "critical",
    "unknown",
]

HEALTH_SEVERITIES = [
    "critical",
    "warning",
    "info",
]


def repeated_id_query_param(name, description):
    """Build a repeated integer query parameter."""
    return {
        "name": name,
        "in": "query",
        "required": False,
        "description": description,
        "style": "form",
        "explode": True,
        "schema": {
            "type": "array",
            "minItems": 1,
            "maxItems": 200,
            "items": {
                "type": "integer",
                "minimum": 1,
            },
        },
    }


def bearer_security():
    """Return bearer authentication requirement."""
    return [{"bearerAuth": []}]


def error_schema():
    """Build the standard API error schema."""
    return {
        "type": "object",
        "properties": {
            "error": {
                "type": "string",
                "example": "not_found",
            },
            "message": {
                "type": "string",
                "nullable": True,
                "example": "Rotation not found.",
            },
            "details": {
                "type": "array",
                "nullable": True,
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                },
            },
        },
        "additionalProperties": True,
    }


def health_summary_schema():
    """Build a row-level or full health summary schema."""
    return {
        "type": "object",
        "required": [
            "status",
            "critical",
            "warning",
            "info",
            "total",
        ],
        "properties": {
            "status": {
                "type": "string",
                "enum": HEALTH_STATUSES,
                "description": (
                    "Effective health status. Critical takes precedence over "
                    "warning; informational issues do not make the object unhealthy."
                ),
                "example": "warning",
            },
            "critical": {
                "type": "integer",
                "minimum": 0,
                "example": 0,
            },
            "warning": {
                "type": "integer",
                "minimum": 0,
                "example": 2,
            },
            "info": {
                "type": "integer",
                "minimum": 0,
                "example": 0,
            },
            "total": {
                "type": "integer",
                "minimum": 0,
                "example": 2,
            },
            "tooltip": {
                "type": "string",
                "nullable": True,
                "description": "Short text used by the health indicator tooltip.",
                "example": "Warnings: 2 · click for full diagnostics",
            },
            "partial": {
                "type": "boolean",
                "description": (
                    "True for lightweight table summaries. Partial summaries "
                    "do not run full schedule-gap or notification-delivery checks."
                ),
                "example": True,
            },
        },
        "additionalProperties": True,
    }


def health_issue_schema():
    """Build an individual on-call health issue schema."""
    return {
        "type": "object",
        "required": [
            "severity",
            "code",
            "title",
            "message",
            "target_type",
        ],
        "properties": {
            "severity": {
                "type": "string",
                "enum": HEALTH_SEVERITIES,
                "example": "critical",
            },
            "code": {
                "type": "string",
                "description": "Stable machine-readable issue code.",
                "example": "schedule_gap",
            },
            "title": {
                "type": "string",
                "example": "Schedule gap detected",
            },
            "message": {
                "type": "string",
                "example": (
                    "No active on-call user can be resolved for part "
                    "of the checked window."
                ),
            },
            "target_type": {
                "type": "string",
                "description": "Type of object affected by the issue.",
                "example": "rotation",
            },
            "target_id": {
                "type": "integer",
                "minimum": 1,
                "nullable": True,
                "example": 3,
            },
            "starts_at": {
                "type": "string",
                "format": "date-time",
                "nullable": True,
            },
            "ends_at": {
                "type": "string",
                "format": "date-time",
                "nullable": True,
            },
            "hint": {
                "type": "string",
                "nullable": True,
                "description": "Suggested action for resolving the issue.",
            },
            "rotation_id": {
                "type": "integer",
                "minimum": 1,
                "nullable": True,
            },
            "rotation_name": {
                "type": "string",
                "nullable": True,
            },
            "team_id": {
                "type": "integer",
                "minimum": 1,
                "nullable": True,
            },
            "team_name": {
                "type": "string",
                "nullable": True,
            },
            "route_id": {
                "type": "integer",
                "minimum": 1,
                "nullable": True,
            },
            "route_name": {
                "type": "string",
                "nullable": True,
            },
            "layer_id": {
                "type": "integer",
                "minimum": 1,
                "nullable": True,
            },
            "layer_name": {
                "type": "string",
                "nullable": True,
            },
            "user_id": {
                "type": "integer",
                "minimum": 1,
                "nullable": True,
            },
            "username": {
                "type": "string",
                "nullable": True,
            },
        },
        "additionalProperties": True,
    }


def health_window_schema():
    """Build a checked diagnostic window schema."""
    return {
        "type": "object",
        "required": [
            "starts_at",
            "ends_at",
        ],
        "properties": {
            "starts_at": {
                "type": "string",
                "format": "date-time",
            },
            "ends_at": {
                "type": "string",
                "format": "date-time",
            },
        },
        "additionalProperties": True,
    }


def rotation_health_details_schema():
    """Build full rotation health response schema."""
    return {
        "type": "object",
        "required": [
            "scope",
            "rotation_id",
            "summary",
            "issues",
        ],
        "properties": {
            "scope": {
                "type": "string",
                "enum": ["rotation"],
            },
            "rotation_id": {
                "type": "integer",
                "minimum": 1,
            },
            "rotation_name": {
                "type": "string",
                "nullable": True,
            },
            "team_id": {
                "type": "integer",
                "minimum": 1,
                "nullable": True,
            },
            "team_name": {
                "type": "string",
                "nullable": True,
            },
            "window": health_window_schema(),
            "summary": health_summary_schema(),
            "issues": {
                "type": "array",
                "items": health_issue_schema(),
            },
        },
        "additionalProperties": True,
    }


def team_health_details_schema():
    """Build full team health response schema."""
    return {
        "type": "object",
        "required": [
            "scope",
            "team_id",
            "summary",
            "issues",
        ],
        "properties": {
            "scope": {
                "type": "string",
                "enum": ["team"],
            },
            "team_id": {
                "type": "integer",
                "minimum": 1,
            },
            "team_name": {
                "type": "string",
                "nullable": True,
            },
            "team_slug": {
                "type": "string",
                "nullable": True,
            },
            "window": health_window_schema(),
            "summary": health_summary_schema(),
            "issues": {
                "type": "array",
                "items": health_issue_schema(),
            },
        },
        "additionalProperties": True,
    }


def rotation_summary_item_schema():
    """Build one rotation summary item."""
    return {
        "type": "object",
        "required": [
            "rotation_id",
            "summary",
        ],
        "properties": {
            "rotation_id": {
                "type": "integer",
                "minimum": 1,
            },
            "summary": health_summary_schema(),
        },
        "additionalProperties": False,
    }


def team_summary_item_schema():
    """Build one team summary item."""
    return {
        "type": "object",
        "required": [
            "team_id",
            "summary",
        ],
        "properties": {
            "team_id": {
                "type": "integer",
                "minimum": 1,
            },
            "summary": health_summary_schema(),
        },
        "additionalProperties": False,
    }


def rotation_summary_batch_schema():
    """Build batched rotation summary response schema."""
    return {
        "type": "object",
        "required": [
            "items",
            "by_id",
        ],
        "properties": {
            "items": {
                "type": "array",
                "items": rotation_summary_item_schema(),
            },
            "by_id": {
                "type": "object",
                "description": "Health summaries indexed by string rotation id.",
                "additionalProperties": health_summary_schema(),
                "example": {
                    "3": {
                        "status": "ok",
                        "critical": 0,
                        "warning": 0,
                        "info": 0,
                        "total": 0,
                        "partial": True,
                    },
                },
            },
        },
        "additionalProperties": False,
    }


def team_summary_batch_schema():
    """Build batched team summary response schema."""
    return {
        "type": "object",
        "required": [
            "items",
            "by_id",
        ],
        "properties": {
            "items": {
                "type": "array",
                "items": team_summary_item_schema(),
            },
            "by_id": {
                "type": "object",
                "description": "Health summaries indexed by string team id.",
                "additionalProperties": health_summary_schema(),
                "example": {
                    "2": {
                        "status": "warning",
                        "critical": 0,
                        "warning": 1,
                        "info": 0,
                        "total": 1,
                        "partial": True,
                    },
                },
            },
        },
        "additionalProperties": False,
    }


def tags():
    """Return OpenAPI tags."""
    return [
        {
            "name": "on-call health",
            "description": (
                "Diagnostics for rotation and team readiness. Lightweight "
                "summary endpoints power table indicators, while detail "
                "endpoints calculate and return full health issues."
            ),
        },
    ]


def paths():
    """Return OpenAPI paths for on-call health endpoints."""
    return {
        "/api/oncall-health/rotations/summaries": {
            "get": {
                "tags": ["on-call health"],
                "summary": "Get rotation health summaries",
                "description": (
                    "Returns lightweight structural health summaries for the "
                    "requested rotations. The same rotation_id query parameter "
                    "may be supplied multiple times. Missing or inaccessible "
                    "rotations are omitted from items and by_id."
                ),
                "operationId": "listRotationHealthSummaries",
                "security": bearer_security(),
                "parameters": [
                    repeated_id_query_param(
                        "rotation_id",
                        "Rotation ids to include in the summary response.",
                    ),
                ],
                "responses": {
                    "200": response(
                        "Rotation health summaries.",
                        rotation_summary_batch_schema(),
                    ),
                    "400": response(
                        "Invalid rotation id or too many ids.",
                        error_schema(),
                    ),
                    "401": response(
                        "Authentication required.",
                        error_schema(),
                    ),
                },
            },
        },
        "/api/oncall-health/rotations/{rotation_id}": {
            "get": {
                "tags": ["on-call health"],
                "summary": "Get full rotation health diagnostics",
                "description": (
                    "Runs full diagnostics for one rotation, including current "
                    "assignment, schedule gaps and other configured checks."
                ),
                "operationId": "getRotationHealth",
                "security": bearer_security(),
                "parameters": [
                    path_param(
                        "rotation_id",
                        "Rotation id.",
                    ),
                ],
                "responses": {
                    "200": response(
                        "Full rotation health diagnostics.",
                        rotation_health_details_schema(),
                    ),
                    "401": response(
                        "Authentication required.",
                        error_schema(),
                    ),
                    "403": response(
                        "Access denied.",
                        error_schema(),
                    ),
                    "404": response(
                        "Rotation not found.",
                        error_schema(),
                    ),
                },
            },
        },
        "/api/oncall-health/teams/summaries": {
            "get": {
                "tags": ["on-call health"],
                "summary": "Get team health summaries",
                "description": (
                    "Returns lightweight on-call readiness summaries for the "
                    "requested teams. The same team_id query parameter may be "
                    "supplied multiple times. Missing or inaccessible teams "
                    "are omitted from items and by_id."
                ),
                "operationId": "listTeamHealthSummaries",
                "security": bearer_security(),
                "parameters": [
                    repeated_id_query_param(
                        "team_id",
                        "Team ids to include in the summary response.",
                    ),
                ],
                "responses": {
                    "200": response(
                        "Team health summaries.",
                        team_summary_batch_schema(),
                    ),
                    "400": response(
                        "Invalid team id or too many ids.",
                        error_schema(),
                    ),
                    "401": response(
                        "Authentication required.",
                        error_schema(),
                    ),
                },
            },
        },
        "/api/oncall-health/teams/{team_id}": {
            "get": {
                "tags": ["on-call health"],
                "summary": "Get full team health diagnostics",
                "description": (
                    "Returns full on-call readiness diagnostics for one team, "
                    "including related rotations, routes and assignment targets."
                ),
                "operationId": "getTeamHealth",
                "security": bearer_security(),
                "parameters": [
                    path_param(
                        "team_id",
                        "Team id.",
                    ),
                ],
                "responses": {
                    "200": response(
                        "Full team health diagnostics.",
                        team_health_details_schema(),
                    ),
                    "401": response(
                        "Authentication required.",
                        error_schema(),
                    ),
                    "403": response(
                        "Access denied.",
                        error_schema(),
                    ),
                    "404": response(
                        "Team not found.",
                        error_schema(),
                    ),
                },
            },
        },
    }
