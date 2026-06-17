from app.api.openapi.common import ERROR_SCHEMA, json_body, path_param, query_param, response


RESPONDER_TARGET_TYPES = [
    "user",
    "team",
    "rotation",
    "escalation_policy",
]

RESPONDER_STATUSES = [
    "requested",
    "accepted",
    "declined",
    "resolved",
    "expired",
]

RESPONDER_UPDATE_STATUSES = [
    "accepted",
    "declined",
    "resolved",
    "expired",
]


def date_time_schema(description, nullable=True):
    schema = {
        "type": "string",
        "format": "date-time",
        "description": description,
    }

    if nullable:
        schema["nullable"] = True

    return schema


USER_SHORT_SCHEMA = {
    "type": "object",
    "nullable": True,
    "properties": {
        "id": {"type": "integer", "example": 42},
        "username": {"type": "string", "nullable": True, "example": "alice"},
        "display_name": {
            "type": "string",
            "nullable": True,
            "example": "Alice Smith",
        },
        "email": {
            "type": "string",
            "format": "email",
            "nullable": True,
            "example": "alice@example.com",
        },
        "telegram_user_id": {"type": "string", "nullable": True},
        "slack_user_id": {"type": "string", "nullable": True},
        "mattermost_user_id": {"type": "string", "nullable": True},
    },
}

TEAM_SHORT_SCHEMA = {
    "type": "object",
    "nullable": True,
    "properties": {
        "id": {"type": "integer", "example": 7},
        "slug": {"type": "string", "nullable": True, "example": "infra"},
        "name": {"type": "string", "nullable": True, "example": "Infrastructure"},
        "active": {"type": "boolean", "nullable": True, "example": True},
        "group_id": {"type": "integer", "nullable": True, "example": 1},
        "group_slug": {"type": "string", "nullable": True, "example": "default"},
    },
}

ROTATION_SHORT_SCHEMA = {
    "type": "object",
    "nullable": True,
    "properties": {
        "id": {"type": "integer", "example": 11},
        "name": {"type": "string", "nullable": True, "example": "Primary on-call"},
        "team_id": {"type": "integer", "nullable": True, "example": 7},
        "team_slug": {"type": "string", "nullable": True, "example": "infra"},
        "team_name": {
            "type": "string",
            "nullable": True,
            "example": "Infrastructure",
        },
        "enabled": {"type": "boolean", "nullable": True, "example": True},
        "timezone": {"type": "string", "nullable": True, "example": "UTC"},
    },
}

ESCALATION_POLICY_SHORT_SCHEMA = {
    "type": "object",
    "nullable": True,
    "properties": {
        "id": {"type": "integer", "example": 5},
        "name": {
            "type": "string",
            "nullable": True,
            "example": "Critical incidents",
        },
        "team_id": {"type": "integer", "nullable": True, "example": 7},
        "team_slug": {"type": "string", "nullable": True, "example": "infra"},
        "team_name": {
            "type": "string",
            "nullable": True,
            "example": "Infrastructure",
        },
        "enabled": {"type": "boolean", "nullable": True, "example": True},
    },
}

INCIDENT_RESPONDER_TARGET_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": RESPONDER_TARGET_TYPES,
            "example": "user",
        },
        "id": {"type": "integer", "nullable": True, "example": 42},
        "label": {
            "type": "string",
            "description": "Human-readable responder target label.",
            "example": "Alice Smith",
        },
        "user": USER_SHORT_SCHEMA,
        "team": TEAM_SHORT_SCHEMA,
        "rotation": ROTATION_SHORT_SCHEMA,
        "escalation_policy": ESCALATION_POLICY_SHORT_SCHEMA,
    },
}

INCIDENT_RESPONDER_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "readOnly": True, "example": 15},
        "incident_id": {"type": "integer", "example": 14784},
        "group_id": {"type": "integer", "example": 14784},

        "target_type": {
            "type": "string",
            "enum": RESPONDER_TARGET_TYPES,
            "example": "user",
        },
        "target_user_id": {"type": "integer", "nullable": True, "example": 42},
        "target_team_id": {"type": "integer", "nullable": True},
        "target_rotation_id": {"type": "integer", "nullable": True},
        "target_escalation_policy_id": {"type": "integer", "nullable": True},
        "target": INCIDENT_RESPONDER_TARGET_SCHEMA,

        "requested_by_id": {"type": "integer", "nullable": True, "example": 1},
        "requested_by": USER_SHORT_SCHEMA,

        "accepted_by_id": {"type": "integer", "nullable": True},
        "accepted_by": USER_SHORT_SCHEMA,

        "declined_by_id": {"type": "integer", "nullable": True},
        "declined_by": USER_SHORT_SCHEMA,

        "status": {
            "type": "string",
            "enum": RESPONDER_STATUSES,
            "example": "requested",
        },
        "message": {
            "type": "string",
            "nullable": True,
            "example": "Please help with database checks.",
        },
        "response_message": {
            "type": "string",
            "nullable": True,
            "example": "I am joining.",
        },

        "notification_status": {
            "type": "string",
            "nullable": True,
            "example": "sent",
        },
        "notification_error": {
            "type": "string",
            "nullable": True,
            "example": None,
        },

        "requested_at": date_time_schema("Responder request timestamp in UTC."),
        "responded_at": date_time_schema("Responder response timestamp in UTC."),
        "expires_at": date_time_schema("Responder request expiration timestamp in UTC."),
        "created_at": date_time_schema("Responder record creation timestamp in UTC."),
        "updated_at": date_time_schema("Responder record update timestamp in UTC."),
    },
}

INCIDENT_RESPONDER_CREATE_SCHEMA = {
    "type": "object",
    "required": ["target_type"],
    "additionalProperties": False,
    "properties": {
        "target_type": {
            "type": "string",
            "enum": RESPONDER_TARGET_TYPES,
            "description": (
                "Responder target type. Exactly one matching target_*_id "
                "field must be provided."
            ),
            "example": "user",
        },
        "target_user_id": {
            "type": "integer",
            "minimum": 1,
            "nullable": True,
            "example": 42,
        },
        "target_team_id": {
            "type": "integer",
            "minimum": 1,
            "nullable": True,
        },
        "target_rotation_id": {
            "type": "integer",
            "minimum": 1,
            "nullable": True,
        },
        "target_escalation_policy_id": {
            "type": "integer",
            "minimum": 1,
            "nullable": True,
        },
        "message": {
            "type": "string",
            "nullable": True,
            "maxLength": 2000,
            "example": "Please help with database checks.",
        },
        "expires_after_minutes": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10080,
            "nullable": True,
            "description": "Optional request lifetime in minutes.",
            "example": 30,
        },
    },
}

INCIDENT_RESPONDER_UPDATE_SCHEMA = {
    "type": "object",
    "required": ["status"],
    "additionalProperties": False,
    "properties": {
        "status": {
            "type": "string",
            "enum": RESPONDER_UPDATE_STATUSES,
            "example": "accepted",
        },
        "response_message": {
            "type": "string",
            "nullable": True,
            "maxLength": 2000,
            "example": "I am joining.",
        },
    },
}

INCIDENT_PRIORITY_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "nullable": True, "example": 1},
        "slug": {"type": "string", "example": "p1"},
        "name": {"type": "string", "nullable": True, "example": "P1 Critical"},
        "description": {"type": "string", "nullable": True},
        "level": {"type": "integer", "nullable": True, "example": 1},
        "color": {"type": "string", "nullable": True, "example": "#d93025"},
        "enabled": {"type": "boolean", "nullable": True, "example": True},
        "default": {"type": "boolean", "nullable": True, "example": False},
    },
}

INCIDENT_PRIORITY_UPDATE_SCHEMA = {
    "type": "object",
    "required": ["priority"],
    "additionalProperties": False,
    "properties": {
        "priority": {
            "type": "string",
            "description": "Priority slug.",
            "example": "p1",
        },
    },
}

INCIDENT_STAKEHOLDER_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "readOnly": True, "example": 9},
        "incident_id": {"type": "integer", "example": 14784},
        "user_id": {"type": "integer", "nullable": True, "example": 42},
        "user": USER_SHORT_SCHEMA,
        "email": {
            "type": "string",
            "format": "email",
            "nullable": True,
            "example": "manager@example.com",
        },
        "display_name": {
            "type": "string",
            "nullable": True,
            "example": "Manager",
        },
        "role": {"type": "string", "nullable": True, "example": "stakeholder"},
        "source": {"type": "string", "nullable": True, "example": "manual"},
        "notify_on_created": {"type": "boolean", "example": True},
        "notify_on_priority_change": {"type": "boolean", "example": True},
        "notify_on_status_change": {"type": "boolean", "example": True},
        "notify_on_resolved": {"type": "boolean", "example": True},
        "notify_on_comment": {"type": "boolean", "example": True},
        "active": {"type": "boolean", "example": True},
        "created_by_id": {"type": "integer", "nullable": True},
        "created_at": date_time_schema("Stakeholder creation timestamp in UTC."),
        "updated_at": date_time_schema("Stakeholder update timestamp in UTC."),
    },
}

INCIDENT_STAKEHOLDER_CREATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "user_id": {"type": "integer", "minimum": 1, "nullable": True},
        "email": {
            "type": "string",
            "format": "email",
            "nullable": True,
            "example": "manager@example.com",
        },
        "display_name": {
            "type": "string",
            "nullable": True,
            "example": "Manager",
        },
        "role": {"type": "string", "nullable": True, "example": "stakeholder"},
        "notify_on_created": {"type": "boolean", "default": True},
        "notify_on_priority_change": {"type": "boolean", "default": True},
        "notify_on_status_change": {"type": "boolean", "default": True},
        "notify_on_resolved": {"type": "boolean", "default": True},
        "notify_on_comment": {"type": "boolean", "default": True},
    },
}

DELETE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "deleted": {"type": "boolean", "example": True},
        "id": {"type": "integer", "example": 9},
    },
}

INCIDENT_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "example": 14784},
        "incident_id": {"type": "integer", "example": 14784},
        "type": {"type": "string", "example": "alert_group"},
        "team_id": {"type": "integer", "nullable": True, "example": 7},
        "team_slug": {"type": "string", "nullable": True, "example": "infra"},
        "team_name": {
            "type": "string",
            "nullable": True,
            "example": "Infrastructure",
        },
        "service_id": {"type": "integer", "nullable": True, "example": 3},
        "service_slug": {"type": "string", "nullable": True, "example": "postgres"},
        "service_name": {"type": "string", "nullable": True, "example": "PostgreSQL"},
        "title": {"type": "string", "example": "DiskFull"},
        "message": {"type": "string", "nullable": True, "example": "/var is 95% full"},
        "severity": {"type": "string", "nullable": True, "example": "critical"},
        "status": {
            "type": "string",
            "example": "firing",
        },
        "priority": {
            "type": "object",
            "additionalProperties": True,
            "description": "Current incident priority summary.",
        },
        "maintenance": {
            "type": "object",
            "additionalProperties": True,
            "description": "Maintenance status attached to this incident.",
        },
        "permissions": {
            "type": "object",
            "additionalProperties": True,
            "description": "Current user's permissions for this incident/team.",
        },
    },
    "additionalProperties": True,
}

INCIDENT_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": INCIDENT_SUMMARY_SCHEMA,
        },
        "pagination": {"type": "object", "additionalProperties": True},
        "summary": {"type": "object", "additionalProperties": True},
        "sort": {"type": "object", "additionalProperties": True},
    },
}

INCIDENT_DETAILS_SCHEMA = {
    "allOf": [
        INCIDENT_SUMMARY_SCHEMA,
        {
            "type": "object",
            "properties": {
                "alerts": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                },
                "events": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                },
                "responders": {
                    "type": "array",
                    "items": INCIDENT_RESPONDER_SCHEMA,
                },
                "stakeholders": {
                    "type": "array",
                    "items": INCIDENT_STAKEHOLDER_SCHEMA,
                },
            },
        },
    ],
}


def tags():
    """Return OpenAPI tags."""
    return [
        {
            "name": "incidents",
            "description": (
                "Incident-level API for alert groups, priorities, stakeholders "
                "and responder requests."
            ),
        }
    ]


def paths():
    """Return OpenAPI paths for incident endpoints."""
    return {
        "/api/incidents": {
            "get": {
                "tags": ["incidents"],
                "summary": "List incidents",
                "description": (
                    "Returns alert groups using the incident API shape. "
                    "Supports filtering by team, status, source, severity, "
                    "priority, service and search text."
                ),
                "operationId": "listIncidents",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    query_param(
                        "team_id",
                        "Filter incidents by team id.",
                        {"type": "integer", "minimum": 1},
                    ),
                    query_param("status", "Filter by incident status."),
                    query_param("source", "Filter by alert source."),
                    query_param("severity", "Filter by severity."),
                    query_param("priority", "Filter by priority slug."),
                    query_param(
                        "service_id",
                        "Filter by service id.",
                        {"type": "integer", "minimum": 1},
                    ),
                    query_param("service_slug", "Filter by service slug."),
                    query_param("service_status", "Filter by service status."),
                    query_param(
                        "service_criticality",
                        "Filter by service criticality.",
                    ),
                    query_param("search", "Search incident fields."),
                    query_param(
                        "page",
                        "Page number.",
                        {"type": "integer", "minimum": 1, "default": 1},
                    ),
                    query_param(
                        "page_size",
                        "Rows per page.",
                        {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 25,
                        },
                    ),
                    query_param(
                        "sort",
                        "Sort field.",
                        {"type": "string", "default": "activity"},
                    ),
                    query_param(
                        "order",
                        "Sort order.",
                        {
                            "type": "string",
                            "enum": ["asc", "desc"],
                            "default": "desc",
                        },
                    ),
                    query_param(
                        "include_merged",
                        "Set to 1 to include merged incidents.",
                        {
                            "type": "string",
                            "enum": ["0", "1"],
                            "default": "0",
                        },
                    ),
                ],
                "responses": {
                    "200": response("Incidents returned.", INCIDENT_LIST_SCHEMA),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                },
            },
        },
        "/api/incidents/{incident_id}": {
            "get": {
                "tags": ["incidents"],
                "summary": "Get incident details",
                "description": (
                    "Returns one incident with child alerts, events, responders "
                    "and stakeholders."
                ),
                "operationId": "getIncident",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("incident_id", "Incident id."),
                ],
                "responses": {
                    "200": response("Incident details returned.", INCIDENT_DETAILS_SCHEMA),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Incident not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/incidents/priorities": {
            "get": {
                "tags": ["incidents"],
                "summary": "List incident priorities",
                "description": "Returns configured incident priorities.",
                "operationId": "listIncidentPriorities",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    query_param(
                        "include_disabled",
                        "Set to 1 to include disabled priorities.",
                        {
                            "type": "string",
                            "enum": ["0", "1"],
                            "default": "0",
                        },
                    ),
                ],
                "responses": {
                    "200": response(
                        "Incident priorities returned.",
                        {"type": "array", "items": INCIDENT_PRIORITY_SCHEMA},
                    ),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                },
            },
        },
        "/api/incidents/{incident_id}/priority": {
            "put": {
                "tags": ["incidents"],
                "summary": "Update incident priority",
                "description": (
                    "Sets incident priority manually and records a priority "
                    "change event."
                ),
                "operationId": "updateIncidentPriority",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("incident_id", "Incident id."),
                ],
                "requestBody": json_body(
                    "Priority update payload.",
                    INCIDENT_PRIORITY_UPDATE_SCHEMA,
                ),
                "responses": {
                    "200": response("Incident priority updated.", INCIDENT_DETAILS_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Incident not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/incidents/{incident_id}/responders": {
            "get": {
                "tags": ["incidents"],
                "summary": "List incident responders",
                "description": "Returns responder requests for one incident.",
                "operationId": "listIncidentResponders",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("incident_id", "Incident id."),
                ],
                "responses": {
                    "200": response(
                        "Incident responders returned.",
                        {"type": "array", "items": INCIDENT_RESPONDER_SCHEMA},
                    ),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Incident not found.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["incidents"],
                "summary": "Request incident responder",
                "description": (
                    "Creates a responder request for a user, team, rotation or "
                    "escalation policy. Accepting a responder request does not "
                    "assign the incident to that user."
                ),
                "operationId": "createIncidentResponder",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("incident_id", "Incident id."),
                ],
                "requestBody": json_body(
                    "Responder request payload.",
                    INCIDENT_RESPONDER_CREATE_SCHEMA,
                ),
                "responses": {
                    "201": response(
                        "Responder request created.",
                        INCIDENT_RESPONDER_SCHEMA,
                    ),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Incident or responder target not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/incidents/{incident_id}/responders/{responder_id}": {
            "put": {
                "tags": ["incidents"],
                "summary": "Update incident responder status",
                "description": (
                    "Accepts, declines, resolves or expires a responder request. "
                    "Only the requested user or an authorized responder for the "
                    "target can update the request."
                ),
                "operationId": "updateIncidentResponderStatus",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("incident_id", "Incident id."),
                    path_param("responder_id", "Responder request id."),
                ],
                "requestBody": json_body(
                    "Responder status update payload.",
                    INCIDENT_RESPONDER_UPDATE_SCHEMA,
                ),
                "responses": {
                    "200": response(
                        "Responder request updated.",
                        INCIDENT_RESPONDER_SCHEMA,
                    ),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Incident or responder request not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/incidents/{incident_id}/stakeholders": {
            "get": {
                "tags": ["incidents"],
                "summary": "List incident stakeholders",
                "description": "Returns stakeholders attached to one incident.",
                "operationId": "listIncidentStakeholders",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("incident_id", "Incident id."),
                ],
                "responses": {
                    "200": response(
                        "Incident stakeholders returned.",
                        {"type": "array", "items": INCIDENT_STAKEHOLDER_SCHEMA},
                    ),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Incident not found.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["incidents"],
                "summary": "Add incident stakeholder",
                "description": "Adds a user or email stakeholder to an incident.",
                "operationId": "createIncidentStakeholder",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("incident_id", "Incident id."),
                ],
                "requestBody": json_body(
                    "Stakeholder properties.",
                    INCIDENT_STAKEHOLDER_CREATE_SCHEMA,
                ),
                "responses": {
                    "201": response(
                        "Incident stakeholder created.",
                        INCIDENT_STAKEHOLDER_SCHEMA,
                    ),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Incident or stakeholder user not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/incidents/{incident_id}/stakeholders/{stakeholder_id}": {
            "delete": {
                "tags": ["incidents"],
                "summary": "Remove incident stakeholder",
                "description": "Removes a stakeholder from an incident.",
                "operationId": "deleteIncidentStakeholder",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("incident_id", "Incident id."),
                    path_param("stakeholder_id", "Stakeholder id."),
                ],
                "responses": {
                    "200": response(
                        "Incident stakeholder removed.",
                        DELETE_RESPONSE_SCHEMA,
                    ),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Incident or stakeholder not found.", ERROR_SCHEMA),
                },
            },
        },
    }
