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



INCIDENT_COMMENT_SCHEMA = {
    "type": "object",
    "required": ["id", "incident_id", "author_id", "body", "created_at", "updated_at"],
    "properties": {
        "id": {"type": "integer"},
        "incident_id": {"type": "integer"},
        "author_id": {"type": "integer"},
        "body": {"type": "string"},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
    },
}
INCIDENT_AFFECTED_SERVICE_SCHEMA = {
    "type": "object",
    "required": ["id", "incident_id", "service_id", "added_at"],
    "properties": {
        "id": {"type": "integer"},
        "incident_id": {"type": "integer"},
        "service_id": {"type": "integer"},
        "added_at": {"type": "string", "format": "date-time"},
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
        "/api/incidents/{incident_id}/activity": {
            "get": {
                "tags": ["incidents"],
                "summary": "Combined Incident and authorized linked AlertGroup activity",
                "security": auth,
                "parameters": [path_param("incident_id", "Incident id."),
                               query_param("limit", "Maximum combined entries (1-500), default 200.",
                                           schema={"type": "integer", "minimum": 1, "maximum": 500})],
                "responses": {"200": response("Attributed activity entries.", {
                    "type": "array", "items": {"type": "object", "required": [
                        "source_type", "source_id", "target_type", "target_id",
                        "record_type", "record_id", "created_at"],
                    "properties": {"source_type": {"type": "string", "enum": ["Incident", "AlertGroup"]},
                                   "source_id": {"type": "integer"},
                                   "target_type": {"type": "string", "enum": ["Incident", "AlertGroup"]},
                                   "target_id": {"type": "integer"},
                                   "record_type": {"type": "string", "enum": ["event", "comment"]},
                                   "record_id": {"type": "integer"},
                                   "actor_id": {"type": "integer", "nullable": True},
                                   "created_at": {"type": "string", "format": "date-time"},
                                   "event_type": {"type": "string"},
                                   "message": {"type": "string", "nullable": True}}}}), **standard_errors},
            }
        },
        "/api/incidents/{incident_id}/responders": {
            "get": {
                "tags": ["incidents"], "summary": "List Incident responder requests and assignments",
                "security": auth, "parameters": [path_param("incident_id", "Incident id.")],
                "responses": {"200": response("Responders.", {"type": "array", "items": {"type": "object"}}), **standard_errors},
            },
            "post": {
                "tags": ["incidents"], "summary": "Request operational responders",
                "security": auth, "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body("Incident responder target.", {
                    "type": "object", "required": ["target_type"],
                    "properties": {
                        "target_type": {"type": "string", "enum": ["user", "team", "rotation", "escalation_policy"]},
                        "target_user_id": {"type": "integer"}, "target_team_id": {"type": "integer"},
                        "target_rotation_id": {"type": "integer"},
                        "target_escalation_policy_id": {"type": "integer"},
                        "message": {"type": "string", "maxLength": 2000},
                        "expires_after_minutes": {"type": "integer"},
                    },
                }),
                "responses": {"201": response("Responder request created.", {"type": "object"}), **standard_errors},
            },
        },
        "/api/incidents/{incident_id}/responders/{responder_id}": {
            "put": {
                "tags": ["incidents"], "summary": "Accept/decline/resolve responder request",
                "security": auth, "parameters": [path_param("incident_id", "Incident id."), path_param("responder_id", "Responder id.")],
                "requestBody": json_body("Responder status.", {
                    "type": "object", "required": ["status"],
                    "properties": {"status": {"type": "string", "enum": ["accepted", "declined", "resolved", "expired"]},
                                   "response_message": {"type": "string", "nullable": True}},
                }),
                "responses": {"200": response("Responder status changed.", {"type": "object"}), **standard_errors},
            },
        },
        "/api/incidents/{incident_id}/participants": {
            "get": {
                "tags": ["incidents"], "summary": "List concrete operational Incident assignments",
                "security": auth, "parameters": [path_param("incident_id", "Incident id.")],
                "responses": {"200": response("Assigned responders.", {"type": "array", "items": {"type": "object"}}), **standard_errors},
            },
            "post": {
                "tags": ["incidents"], "summary": "Assign concrete Incident commander/responder/communications user",
                "security": auth, "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body("Operational assignment.", {
                    "type": "object", "required": ["user_id", "role"],
                    "properties": {"user_id": {"type": "integer", "minimum": 1},
                                   "role": {"type": "string", "enum": ["commander", "responder", "communications"]}},
                }),
                "responses": {"201": response("Assignment created.", {"type": "object"}), **standard_errors},
            },
        },
        "/api/incidents/{incident_id}/participants/{participant_id}": {
            "delete": {
                "tags": ["incidents"], "summary": "Remove concrete assignment",
                "security": auth, "parameters": [path_param("incident_id", "Incident id."), path_param("participant_id", "Assignment id.")],
                "responses": {"204": {"description": "Assignment removed."}, **standard_errors},
            },
        },
        "/api/incidents/{incident_id}/stakeholders": {
            "get": {
                "tags": ["incidents"], "summary": "List Incident stakeholders",
                "security": auth, "parameters": [path_param("incident_id", "Incident id.")],
                "responses": {"200": response("Stakeholders.", {"type": "array", "items": {"type": "object"}}), **standard_errors},
            },
            "post": {
                "tags": ["incidents"], "summary": "Add Incident stakeholder",
                "security": auth, "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body("Stakeholder user or email.", {
                    "type": "object", "properties": {"user_id": {"type": "integer", "minimum": 1},
                    "email": {"type": "string", "maxLength": 255}, "display_name": {"type": "string"},
                    "role": {"type": "string", "enum": ["stakeholder", "communications", "observer"]}}}),
                "responses": {"201": response("Stakeholder created.", {"type": "object"}), **standard_errors},
            },
        },
        "/api/incidents/{incident_id}/stakeholders/{stakeholder_id}": {
            "delete": {
                "tags": ["incidents"], "summary": "Deactivate Incident stakeholder",
                "security": auth, "parameters": [path_param("incident_id", "Incident id."), path_param("stakeholder_id", "Stakeholder id.")],
                "responses": {"204": {"description": "Stakeholder deactivated."}, **standard_errors},
            },
        },
        "/api/incidents/{incident_id}/comments": {
            "get": {
                "tags": ["incidents"], "summary": "List operational Incident comments",
                "description": "Technical AlertGroup comments are not copied or returned.",
                "security": auth, "parameters": [path_param("incident_id", "Incident id.")],
                "responses": {"200": response("Incident comments.", {"type": "array", "items": INCIDENT_COMMENT_SCHEMA}), **standard_errors},
            },
            "post": {
                "tags": ["incidents"], "summary": "Add operational Incident comment",
                "security": auth, "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body("Comment body.", {"type": "object", "required": ["body"],
                    "additionalProperties": False, "properties": {"body": {"type": "string", "minLength": 1, "maxLength": 10000}}}),
                "responses": {"201": response("Comment created.", INCIDENT_COMMENT_SCHEMA), **standard_errors},
            },
        },
        "/api/incidents/{incident_id}/affected-services": {
            "get": {
                "tags": ["incidents"], "summary": "List visible affected services",
                "description": "Services outside the caller's team read scope are omitted.",
                "security": auth, "parameters": [path_param("incident_id", "Incident id.")],
                "responses": {"200": response("Visible service links.", {"type": "array", "items": INCIDENT_AFFECTED_SERVICE_SCHEMA}), **standard_errors},
            },
            "post": {
                "tags": ["incidents"], "summary": "Link an affected service",
                "description": "Requires Incident respond and affected Service team respond rights. Existing links return 200.",
                "security": auth, "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body("Service identifier.", {"type": "object", "required": ["service_id"],
                    "additionalProperties": False, "properties": {"service_id": {"type": "integer", "minimum": 1}}}),
                "responses": {"200": response("Existing link.", INCIDENT_AFFECTED_SERVICE_SCHEMA),
                              "201": response("Link created.", INCIDENT_AFFECTED_SERVICE_SCHEMA), **standard_errors},
            },
        },
        "/api/incidents/{incident_id}/affected-services/{service_id}": {
            "delete": {
                "tags": ["incidents"], "summary": "Remove affected service link",
                "security": auth, "parameters": [path_param("incident_id", "Incident id."), path_param("service_id", "Service id.")],
                "responses": {"200": response("Link removed.", {"type": "object", "properties": {"removed": {"type": "boolean"}}}), **standard_errors},
            },
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
