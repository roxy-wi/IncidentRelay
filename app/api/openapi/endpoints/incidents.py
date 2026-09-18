from app.api.openapi.common import ERROR_SCHEMA, json_body, path_param, query_param, response


INCIDENT_STATUS_VALUES = [
    "declared",
    "investigating",
    "identified",
    "monitoring",
    "resolved",
    "closed",
    "cancelled",
]

INCIDENT_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "workflow_status", "title", "row_version"],
    "properties": {
        "id": {"type": "integer"},
        "type": {"type": "string", "enum": ["incident"]},
        "team_id": {"type": "integer", "nullable": True},
        "service_id": {"type": "integer", "nullable": True},
        "priority": {"type": "string", "nullable": True, "example": "p2"},
        "assignee_id": {"type": "integer", "nullable": True},
        "workflow_status": {"type": "string", "enum": INCIDENT_STATUS_VALUES},
        "title": {"type": "string"},
        "description": {"type": "string", "nullable": True},
        "row_version": {"type": "integer", "minimum": 1},
        "declared_at": {"type": "string", "format": "date-time"},
        "resolved_at": {"type": "string", "format": "date-time", "nullable": True},
        "closed_at": {"type": "string", "format": "date-time", "nullable": True},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
    },
}

INCIDENT_CREATE_SCHEMA = {
    "type": "object",
    "required": ["team_id", "title"],
    "additionalProperties": False,
    "properties": {
        "team_id": {"type": "integer", "minimum": 1},
        "service_id": {"type": "integer", "minimum": 1, "nullable": True},
        "title": {"type": "string", "minLength": 1, "maxLength": 255},
        "description": {"type": "string", "nullable": True, "maxLength": 10000},
        "priority": {"type": "string", "enum": ["p1", "p2", "p3", "p4", "p5"], "nullable": True},
        "assignee_id": {"type": "integer", "minimum": 1, "nullable": True},
    },
}

INCIDENT_UPDATE_SCHEMA = {
    "type": "object",
    "required": ["row_version"],
    "additionalProperties": False,
    "properties": {
        "row_version": {"type": "integer", "minimum": 1},
        "title": {"type": "string", "minLength": 1, "maxLength": 255},
        "description": {"type": "string", "nullable": True},
        "service_id": {"type": "integer", "minimum": 1, "nullable": True},
        "priority": {"type": "string", "enum": ["p1", "p2", "p3", "p4", "p5"]},
    },
}

INCIDENT_LINK_SCHEMA = {
    "type": "object",
    "required": ["alert_group_id"],
    "additionalProperties": False,
    "properties": {
        "alert_group_id": {"type": "integer", "minimum": 1},
        "relation_type": {"type": "string", "enum": ["primary", "related"], "default": "related"},
    },
}


def tags():
    return [{
        "name": "incidents",
        "description": "First-class operational Incidents, independent from AlertGroup technical lifecycle.",
    }]


def paths():
    auth = [{"bearerAuth": []}]
    standard_errors = {
        "400": response("Validation error.", ERROR_SCHEMA),
        "401": response("Authentication required.", ERROR_SCHEMA),
        "403": response("Access denied.", ERROR_SCHEMA),
        "404": response("Incident not found.", ERROR_SCHEMA),
        "409": response("Optimistic concurrency conflict.", ERROR_SCHEMA),
    }
    return {
        "/api/incidents": {
            "get": {
                "tags": ["incidents"],
                "summary": "List first-class Incidents",
                "security": auth,
                "parameters": [
                    query_param("team_id", "Owning team id.", {"type": "integer", "minimum": 1}),
                    query_param("status", "Incident workflow status.", {"type": "string", "enum": INCIDENT_STATUS_VALUES}),
                    query_param("search", "Case-insensitive title search."),
                    query_param("page", "Page number.", {"type": "integer", "minimum": 1, "default": 1}),
                    query_param("page_size", "Items per page.", {"type": "integer", "minimum": 1, "maximum": 100, "default": 25}),
                ],
                "responses": {"200": response("Incident page.", {"type": "object"}), **standard_errors},
            },
            "post": {
                "tags": ["incidents"],
                "summary": "Create a first-class Incident",
                "description": "Creates only an operational Incident. No Alert or AlertGroup is created implicitly.",
                "security": auth,
                "requestBody": json_body("Incident fields.", INCIDENT_CREATE_SCHEMA),
                "responses": {"201": response("Incident created.", INCIDENT_SCHEMA), **standard_errors},
            },
        },
        "/api/incidents/priorities": {
            "get": {
                "tags": ["incidents"],
                "summary": "List Incident priority definitions",
                "security": auth,
                "responses": {"200": response("Priority definitions.", {"type": "array", "items": {"type": "object"}})},
            }
        },
        "/api/incidents/{incident_id}": {
            "get": {
                "tags": ["incidents"], "summary": "Get Incident", "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "responses": {"200": response("Incident details.", INCIDENT_SCHEMA), **standard_errors},
            },
            "patch": {
                "tags": ["incidents"], "summary": "Update Incident", "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body("Mutable fields and current row_version.", INCIDENT_UPDATE_SCHEMA),
                "responses": {"200": response("Incident updated.", INCIDENT_SCHEMA), **standard_errors},
            },
        },
        "/api/incidents/{incident_id}/status": {
            "post": {
                "tags": ["incidents"], "summary": "Transition Incident workflow status", "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body("Target status and current row_version.", {
                    "type": "object", "required": ["status", "row_version"],
                    "properties": {"status": {"type": "string", "enum": INCIDENT_STATUS_VALUES}, "row_version": {"type": "integer", "minimum": 1}},
                }),
                "responses": {"200": response("Incident transitioned.", INCIDENT_SCHEMA), **standard_errors},
            }
        },
        "/api/incidents/{incident_id}/close": _simple_transition_path("Close Incident", "Explicitly closes a resolved Incident."),
        "/api/incidents/{incident_id}/reopen": _simple_transition_path("Reopen Incident", "Explicitly reopens a closed/resolved Incident into investigating."),
        "/api/incidents/{incident_id}/assignee": {
            "put": {
                "tags": ["incidents"], "summary": "Assign, reassign or unassign Incident", "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body("Concrete operational assignee and row_version.", {
                    "type": "object", "required": ["row_version"],
                    "properties": {"row_version": {"type": "integer", "minimum": 1}, "assignee_id": {"type": "integer", "minimum": 1, "nullable": True}},
                }),
                "responses": {"200": response("Incident assignment updated.", INCIDENT_SCHEMA), **standard_errors},
            }
        },
        "/api/incidents/{incident_id}/assignee/me": {
            "put": {
                "tags": ["incidents"], "summary": "Assign Incident to current user", "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body("Current row_version.", {"type": "object", "required": ["row_version"], "properties": {"row_version": {"type": "integer", "minimum": 1}}}),
                "responses": {"200": response("Incident assigned.", INCIDENT_SCHEMA), **standard_errors},
            }
        },
        "/api/incidents/{incident_id}/alert-groups": {
            "get": {
                "tags": ["incidents"], "summary": "List linked AlertGroups", "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "responses": {"200": response("Active links.", {"type": "array", "items": {"type": "object"}}), **standard_errors},
            },
            "post": {
                "tags": ["incidents"], "summary": "Link AlertGroup", "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body("AlertGroup link.", INCIDENT_LINK_SCHEMA),
                "responses": {"201": response("AlertGroup linked.", {"type": "object"}), **standard_errors},
            },
        },
        "/api/incidents/{incident_id}/alert-groups/{group_id}": {
            "delete": {
                "tags": ["incidents"], "summary": "Unlink AlertGroup", "security": auth,
                "parameters": [path_param("incident_id", "Incident id."), path_param("group_id", "AlertGroup id.")],
                "responses": {"200": response("AlertGroup unlinked.", {"type": "object"}), **standard_errors},
            }
        },
        "/api/incidents/{incident_id}/events": {
            "get": {
                "tags": ["incidents"], "summary": "List operational Incident events", "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "responses": {"200": response("Incident events.", {"type": "array", "items": {"type": "object"}}), **standard_errors},
            }
        },
    }


def _simple_transition_path(summary, description):
    return {
        "post": {
            "tags": ["incidents"], "summary": summary, "description": description,
            "security": [{"bearerAuth": []}],
            "parameters": [path_param("incident_id", "Incident id.")],
            "requestBody": json_body("Current row_version.", {"type": "object", "required": ["row_version"], "properties": {"row_version": {"type": "integer", "minimum": 1}}}),
            "responses": {
                "200": response("Incident transitioned.", INCIDENT_SCHEMA),
                "400": response("Invalid transition.", ERROR_SCHEMA),
                "401": response("Authentication required.", ERROR_SCHEMA),
                "403": response("Access denied.", ERROR_SCHEMA),
                "404": response("Incident not found.", ERROR_SCHEMA),
                "409": response("Optimistic concurrency conflict.", ERROR_SCHEMA),
            },
        }
    }
