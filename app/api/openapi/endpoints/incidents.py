from app.api.openapi.common import (
    ERROR_SCHEMA,
    json_body,
    path_param,
    query_param,
    response,
)


INCIDENT_STATUS_VALUES = [
    "declared",
    "investigating",
    "identified",
    "monitoring",
    "resolved",
    "closed",
    "cancelled",
]

INCIDENT_ACTOR_SCHEMA = {
    "nullable": True,
    "properties": {
        "display_name": {"nullable": True, "type": "string"},
        "id": {"type": "integer"},
        "username": {"type": "string"},
    },
    "required": ["id", "username", "display_name"],
    "type": "object",
}

INCIDENT_USER_SCHEMA = {
    "nullable": True,
    "properties": {
        "display_name": {"nullable": True, "type": "string"},
        "email": {"nullable": True, "type": "string"},
        "id": {"type": "integer"},
        "username": {"type": "string"},
    },
    "required": ["id", "username", "display_name", "email"],
    "type": "object",
}

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
        "workflow_status": {
            "type": "string",
            "enum": INCIDENT_STATUS_VALUES,
        },
        "title": {"type": "string"},
        "description": {"type": "string", "nullable": True},
        "row_version": {"type": "integer", "minimum": 1},
        "declared_at": {"type": "string", "format": "date-time"},
        "resolved_at": {"type": "string", "format": "date-time", "nullable": True},
        "closed_at": {"type": "string", "format": "date-time", "nullable": True},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
        "team_name": {"type": "string", "nullable": True},
        "team_slug": {"type": "string", "nullable": True},
        "service_name": {"type": "string", "nullable": True},
        "service_slug": {"type": "string", "nullable": True},
        "priority_id": {"type": "integer", "nullable": True},
        "assignee": INCIDENT_USER_SCHEMA,
        "declared_by_id": {"type": "integer", "nullable": True},
        "closed_by_id": {"type": "integer", "nullable": True},
        "investigation_started_at": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
        },
        "identified_at": {"type": "string", "format": "date-time", "nullable": True},
        "monitoring_at": {"type": "string", "format": "date-time", "nullable": True},
        "summary": {"type": "string", "nullable": True},
        "root_cause": {"type": "string", "nullable": True},
        "resolution_summary": {"type": "string", "nullable": True},
        "permissions": {"type": "object", "additionalProperties": {"type": "boolean"}},
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
        "priority": {
            "type": "string",
            "enum": ["p1", "p2", "p3", "p4", "p5", None],
            "nullable": True,
        },
        "assignee_id": {"type": "integer", "minimum": 1, "nullable": True},
    },
}

INCIDENT_UPDATE_SCHEMA = {
    "type": "object",
    "required": ["row_version"],
    "additionalProperties": False,
    "properties": {
        "row_version": {"type": "integer", "minimum": 1},
        "title": {"type": "string", "minLength": 1, "maxLength": 255, "nullable": True},
        "description": {"type": "string", "nullable": True, "maxLength": 10000},
        "service_id": {"type": "integer", "minimum": 1, "nullable": True},
        "priority": {
            "type": "string",
            "enum": ["p1", "p2", "p3", "p4", "p5", None],
            "nullable": True,
        },
        "root_cause": {"type": "string", "nullable": True, "maxLength": 10000},
        "resolution_summary": {"type": "string", "nullable": True, "maxLength": 10000},
    },
}

INCIDENT_LINK_SCHEMA = {
    "type": "object",
    "required": ["alert_group_id"],
    "additionalProperties": False,
    "properties": {
        "alert_group_id": {"type": "integer", "minimum": 1},
        "relation_type": {
            "type": "string",
            "enum": ["primary", "related"],
            "default": "related",
        },
    },
}

INCIDENT_COMMENT_SCHEMA = {
    "type": "object",
    "required": [
        "id",
        "incident_id",
        "author_id",
        "body",
        "created_at",
        "updated_at",
        "author",
    ],
    "properties": {
        "id": {"type": "integer"},
        "incident_id": {"type": "integer"},
        "author_id": {"type": "integer", "nullable": True},
        "body": {"type": "string"},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
        "author": INCIDENT_ACTOR_SCHEMA,
    },
}

INCIDENT_AFFECTED_SERVICE_SCHEMA = {
    "type": "object",
    "required": ["id", "incident_id", "service_id", "added_at"],
    "properties": {
        "id": {"type": "integer"},
        "incident_id": {"type": "integer"},
        "service_id": {"type": "integer"},
        "permissions": {
            "type": "object",
            "properties": {"can_remove": {"type": "boolean"}},
        },
        "impact": {
            "type": "object",
            "nullable": True,
            "properties": {
                "own_status": {"type": "string"},
                "effective_status": {"type": "string"},
                "effective_impact_score": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                },
            },
        },
        "added_at": {"type": "string", "format": "date-time"},
        "service_name": {"type": "string"},
        "service_slug": {"type": "string"},
        "status": {"type": "string"},
        "criticality": {"type": "string"},
        "tier": {"type": "string", "nullable": True},
        "environment": {"type": "string", "nullable": True},
        "team_id": {"type": "integer", "nullable": True},
        "runbooks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "url"],
                "properties": {"title": {"type": "string"}, "url": {"type": "string"}},
            },
        },
        "links": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["label", "type", "url"],
                "properties": {
                    "label": {"type": "string"},
                    "type": {"type": "string"},
                    "url": {"type": "string"},
                },
            },
        },
        "dependencies": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["service_id", "name", "criticality", "dependency_type"],
                "properties": {
                    "service_id": {"type": "integer"},
                    "name": {"type": "string"},
                    "criticality": {"type": "string"},
                    "dependency_type": {"type": "string"},
                },
            },
        },
    },
}

INCIDENT_PARTICIPANT_SCHEMA = {
    "type": "object",
    "required": [
        "id",
        "incident_id",
        "user_id",
        "user",
        "role",
        "assigned_by_id",
        "created_at",
    ],
    "properties": {
        "id": {"type": "integer"},
        "incident_id": {"type": "integer"},
        "user_id": {"type": "integer", "nullable": True},
        "user": INCIDENT_USER_SCHEMA,
        "role": {
            "type": "string",
            "enum": ["commander", "responder", "communications"],
        },
        "assigned_by_id": {"type": "integer", "nullable": True},
        "created_at": {"type": "string", "format": "date-time"},
    },
}

INCIDENT_STAKEHOLDER_SCHEMA = {
    "type": "object",
    "required": [
        "id",
        "incident_id",
        "user_id",
        "email",
        "display_name",
        "user",
        "role",
        "source",
        "created_at",
    ],
    "properties": {
        "id": {"type": "integer"},
        "incident_id": {"type": "integer"},
        "user_id": {"type": "integer", "nullable": True},
        "email": {"type": "string", "nullable": True},
        "display_name": {"type": "string", "nullable": True},
        "user": INCIDENT_USER_SCHEMA,
        "role": {
            "type": "string",
            "description": "Manual roles or the preserved ServiceOwner/legacy role.",
        },
        "source": {"type": "string"},
        "created_at": {"type": "string", "format": "date-time"},
    },
}

INCIDENT_RESPONDER_SCHEMA = {
    "type": "object",
    "required": [
        "id",
        "incident_id",
        "role",
        "target_type",
        "target_user_id",
        "target_team_id",
        "target_rotation_id",
        "target_escalation_policy_id",
        "target",
        "requested_by_id",
        "requested_by",
        "accepted_by_id",
        "accepted_by",
        "declined_by_id",
        "declined_by",
        "status",
        "message",
        "response_message",
        "notification_status",
        "notification_error",
        "requested_at",
        "responded_at",
        "expires_at",
        "created_at",
        "updated_at",
    ],
    "properties": {
        "id": {"type": "integer"},
        "incident_id": {"type": "integer"},
        "role": {"type": "string"},
        "target_type": {"type": "string"},
        "target_user_id": {"type": "integer", "nullable": True},
        "target_team_id": {"type": "integer", "nullable": True},
        "target_rotation_id": {"type": "integer", "nullable": True},
        "target_escalation_policy_id": {"type": "integer", "nullable": True},
        "target": {
            "type": "object",
            "required": ["type", "id", "label"],
            "properties": {
                "type": {"type": "string"},
                "id": {"type": "integer", "nullable": True},
                "label": {"type": "string"},
            },
        },
        "requested_by_id": {"type": "integer", "nullable": True},
        "requested_by": INCIDENT_USER_SCHEMA,
        "accepted_by_id": {"type": "integer", "nullable": True},
        "accepted_by": INCIDENT_USER_SCHEMA,
        "declined_by_id": {"type": "integer", "nullable": True},
        "declined_by": INCIDENT_USER_SCHEMA,
        "status": {
            "type": "string",
            "enum": ["requested", "accepted", "declined", "expired", "resolved"],
        },
        "message": {"type": "string", "nullable": True},
        "response_message": {"type": "string", "nullable": True},
        "notification_status": {"type": "string"},
        "notification_error": {"type": "string", "nullable": True},
        "requested_at": {"type": "string", "format": "date-time"},
        "responded_at": {"type": "string", "format": "date-time", "nullable": True},
        "expires_at": {"type": "string", "format": "date-time", "nullable": True},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
    },
}

INCIDENT_RESPONDER_CREATE_SCHEMA = {
    "type": "object",
    "required": ["target_type"],
    "additionalProperties": False,
    "properties": {
        "target_type": {
            "type": "string",
            "enum": ["user", "team", "rotation", "escalation_policy"],
        },
        "target_user_id": {"type": "integer", "minimum": 1, "nullable": True},
        "target_team_id": {"type": "integer", "minimum": 1, "nullable": True},
        "target_rotation_id": {"type": "integer", "minimum": 1, "nullable": True},
        "target_escalation_policy_id": {
            "type": "integer",
            "minimum": 1,
            "nullable": True,
        },
        "message": {"type": "string", "nullable": True, "maxLength": 2000},
        "expires_after_minutes": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10080,
            "nullable": True,
        },
    },
    "oneOf": [
        {
            "required": ["target_user_id"],
            "properties": {
                "target_type": {"enum": ["user"]},
                "target_user_id": {"type": "integer", "minimum": 1},
                "target_team_id": {"nullable": True, "enum": [None]},
                "target_rotation_id": {"nullable": True, "enum": [None]},
                "target_escalation_policy_id": {"nullable": True, "enum": [None]},
            },
        },
        {
            "required": ["target_team_id"],
            "properties": {
                "target_type": {"enum": ["team"]},
                "target_team_id": {"type": "integer", "minimum": 1},
                "target_user_id": {"nullable": True, "enum": [None]},
                "target_rotation_id": {"nullable": True, "enum": [None]},
                "target_escalation_policy_id": {"nullable": True, "enum": [None]},
            },
        },
        {
            "required": ["target_rotation_id"],
            "properties": {
                "target_type": {"enum": ["rotation"]},
                "target_rotation_id": {"type": "integer", "minimum": 1},
                "target_user_id": {"nullable": True, "enum": [None]},
                "target_team_id": {"nullable": True, "enum": [None]},
                "target_escalation_policy_id": {"nullable": True, "enum": [None]},
            },
        },
        {
            "required": ["target_escalation_policy_id"],
            "properties": {
                "target_type": {"enum": ["escalation_policy"]},
                "target_escalation_policy_id": {"type": "integer", "minimum": 1},
                "target_user_id": {"nullable": True, "enum": [None]},
                "target_team_id": {"nullable": True, "enum": [None]},
                "target_rotation_id": {"nullable": True, "enum": [None]},
            },
        },
    ],
}

INCIDENT_STAKEHOLDER_CREATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "description": "Specify exactly one non-null user_id or non-empty email. Email is trimmed and "
    "lowercased.",
    "properties": {
        "user_id": {"type": "integer", "minimum": 1, "nullable": True},
        "email": {"type": "string", "nullable": True, "maxLength": 255},
        "display_name": {"type": "string", "nullable": True, "maxLength": 255},
        "role": {
            "type": "string",
            "enum": ["stakeholder", "communications", "observer"],
            "default": "stakeholder",
        },
    },
    "oneOf": [
        {
            "required": ["user_id"],
            "properties": {
                "user_id": {"type": "integer", "minimum": 1},
                "email": {"enum": [None, ""], "nullable": True},
            },
        },
        {
            "required": ["email"],
            "properties": {
                "email": {"type": "string", "minLength": 1, "pattern": "@"},
                "user_id": {"enum": [None], "nullable": True},
            },
        },
    ],
}

INCIDENT_EVENT_SCHEMA = {
    "type": "object",
    "required": [
        "id",
        "incident_id",
        "event_type",
        "user_id",
        "message",
        "data",
        "created_at",
    ],
    "properties": {
        "id": {"type": "integer"},
        "incident_id": {"type": "integer"},
        "event_type": {"type": "string"},
        "user_id": {"type": "integer", "nullable": True},
        "message": {"type": "string", "nullable": True},
        "data": {"type": "object"},
        "created_at": {"type": "string", "format": "date-time"},
    },
}

INCIDENT_ALERT_GROUP_LINK_SCHEMA = {
    "type": "object",
    "required": [
        "id",
        "incident_id",
        "alert_group_id",
        "relation_type",
        "active",
        "linked_by_id",
        "linked_at",
        "removed_by_id",
        "removed_at",
        "permissions",
        "alert_group",
    ],
    "properties": {
        "id": {"type": "integer"},
        "incident_id": {"type": "integer"},
        "alert_group_id": {"type": "integer"},
        "relation_type": {"type": "string", "enum": ["primary", "related"]},
        "active": {"type": "boolean"},
        "linked_by_id": {"type": "integer", "nullable": True},
        "linked_at": {"type": "string", "format": "date-time"},
        "removed_by_id": {"type": "integer", "nullable": True},
        "removed_at": {"type": "string", "format": "date-time", "nullable": True},
        "permissions": {
            "type": "object",
            "required": ["can_unlink"],
            "properties": {"can_unlink": {"type": "boolean"}},
        },
        "alert_group": {
            "type": "object",
            "nullable": True,
            "properties": {
                "id": {"type": "integer"},
                "title": {"type": "string"},
                "status": {"type": "string"},
                "severity": {"type": "string"},
                "priority": {"type": "string", "nullable": True},
                "source": {"type": "string", "nullable": True},
                "service_id": {"type": "integer", "nullable": True},
                "assignee_id": {"type": "integer", "nullable": True},
                "last_seen_at": {
                    "type": "string",
                    "format": "date-time",
                    "nullable": True,
                },
            },
        },
    },
}

INCIDENT_PAGE_SCHEMA = {
    "type": "object",
    "required": ["items", "pagination"],
    "properties": {
        "items": {
            "type": "array",
            "items": INCIDENT_SCHEMA,
        },
        "pagination": {
            "type": "object",
            "required": ["page", "page_size", "total", "pages"],
            "properties": {
                "page": {"type": "integer"},
                "page_size": {"type": "integer"},
                "total": {"type": "integer"},
                "pages": {"type": "integer"},
            },
        },
    },
}


INCIDENT_DETAIL_SCHEMA = {
    **INCIDENT_SCHEMA,
    "properties": {
        **INCIDENT_SCHEMA["properties"],
        "alert_groups": {"type": "array", "items": INCIDENT_ALERT_GROUP_LINK_SCHEMA},
        "events": {"type": "array", "items": INCIDENT_EVENT_SCHEMA},
    },
}


def tags():
    return [
        {
            "name": "incidents",
            "description": "First-class operational Incidents, independent from AlertGroup technical lifecycle.",
        }
    ]


def paths():
    auth = [{"bearerAuth": []}]
    standard_errors = {
        "400": response("Validation error.", ERROR_SCHEMA),
        "401": response("Authentication required.", ERROR_SCHEMA),
        "403": response("Access denied.", ERROR_SCHEMA),
        "404": response("Incident not found.", ERROR_SCHEMA),
        "409": response(
            "Stale row_version or conflicting Incident/participant state.", ERROR_SCHEMA
        ),
    }
    return {
        "/api/incidents": {
            "get": {
                "tags": ["incidents"],
                "summary": "List first-class Incidents",
                "security": auth,
                "parameters": [
                    query_param(
                        "team_id", "Owning team id.", {"type": "integer", "minimum": 1}
                    ),
                    query_param(
                        "status",
                        "Incident workflow status.",
                        {"type": "string", "enum": INCIDENT_STATUS_VALUES},
                    ),
                    query_param("search", "Case-insensitive title search."),
                    query_param(
                        "page",
                        "Page number.",
                        {"type": "integer", "minimum": 1, "default": 1},
                    ),
                    query_param(
                        "page_size",
                        "Items per page.",
                        {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 25,
                        },
                    ),
                ],
                "responses": {
                    "200": response("Incident page.", INCIDENT_PAGE_SCHEMA),
                    **standard_errors,
                },
            },
            "post": {
                "tags": ["incidents"],
                "summary": "Create a first-class Incident",
                "description": "Creates only an operational Incident. No Alert or AlertGroup is created implicitly.",
                "security": auth,
                "requestBody": json_body("Incident fields.", INCIDENT_CREATE_SCHEMA),
                "responses": {
                    "201": response("Incident created.", INCIDENT_SCHEMA),
                    **standard_errors,
                },
            },
        },
        "/api/incidents/priorities": {
            "get": {
                "tags": ["incidents"],
                "summary": "List Incident priority definitions",
                "security": auth,
                "responses": {
                    "200": response(
                        "Priority definitions.",
                        {"type": "array", "items": {"type": "object"}},
                    )
                },
            }
        },
        "/api/incidents/{incident_id}": {
            "get": {
                "tags": ["incidents"],
                "summary": "Get Incident",
                "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "responses": {
                    "200": response("Incident details.", INCIDENT_DETAIL_SCHEMA),
                    **standard_errors,
                },
            },
            "patch": {
                "tags": ["incidents"],
                "summary": "Update Incident",
                "security": auth,
                "description": "Updates fields including root_cause and resolution_summary. Null fields are unchanged; use an empty string to clear root_cause or resolution_summary. A stale row_version returns 409 when applying changes; reload before retrying.",
                "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body(
                    "Mutable fields and current row_version.", INCIDENT_UPDATE_SCHEMA
                ),
                "responses": {
                    "200": response("Incident updated.", INCIDENT_SCHEMA),
                    **standard_errors,
                },
            },
        },
        "/api/incidents/{incident_id}/status": {
            "post": {
                "tags": ["incidents"],
                "summary": "Transition Incident workflow status",
                "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body(
                    "Target status and current row_version.",
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["status", "row_version"],
                        "properties": {
                            "status": {
                                "type": "string",
                                "enum": INCIDENT_STATUS_VALUES,
                            },
                            "row_version": {"type": "integer", "minimum": 1},
                        },
                    },
                ),
                "responses": {
                    "200": response("Incident transitioned.", INCIDENT_SCHEMA),
                    **standard_errors,
                },
            }
        },
        "/api/incidents/{incident_id}/close": _simple_transition_path(
            "Close Incident", "Explicitly closes a resolved Incident."
        ),
        "/api/incidents/{incident_id}/reopen": _simple_transition_path(
            "Reopen Incident",
            "Explicitly reopens a closed/resolved Incident into investigating.",
        ),
        "/api/incidents/{incident_id}/assignee": {
            "put": {
                "tags": ["incidents"],
                "summary": "Assign, reassign or unassign Incident",
                "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body(
                    "Concrete operational assignee and row_version.",
                    {
                        "type": "object",
                        "required": ["row_version"],
                        "properties": {
                            "row_version": {"type": "integer", "minimum": 1},
                            "assignee_id": {
                                "type": "integer",
                                "minimum": 1,
                                "nullable": True,
                            },
                        },
                    },
                ),
                "responses": {
                    "200": response("Incident assignment updated.", INCIDENT_SCHEMA),
                    **standard_errors,
                },
            }
        },
        "/api/incidents/{incident_id}/assignee/me": {
            "put": {
                "tags": ["incidents"],
                "summary": "Assign Incident to current user",
                "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body(
                    "Current row_version.",
                    {
                        "type": "object",
                        "required": ["row_version"],
                        "properties": {
                            "row_version": {"type": "integer", "minimum": 1}
                        },
                    },
                ),
                "responses": {
                    "200": response("Incident assigned.", INCIDENT_SCHEMA),
                    **standard_errors,
                },
            }
        },
        "/api/incidents/{incident_id}/alert-groups": {
            "get": {
                "tags": ["incidents"],
                "summary": "List linked AlertGroups",
                "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "responses": {
                    "200": response(
                        "Active links.",
                        {"type": "array", "items": INCIDENT_ALERT_GROUP_LINK_SCHEMA},
                    ),
                    **standard_errors,
                },
            },
            "post": {
                "tags": ["incidents"],
                "summary": "Link AlertGroup",
                "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body("AlertGroup link.", INCIDENT_LINK_SCHEMA),
                "responses": {
                    "201": response(
                        "AlertGroup linked.", INCIDENT_ALERT_GROUP_LINK_SCHEMA
                    ),
                    **standard_errors,
                },
            },
        },
        "/api/incidents/{incident_id}/alert-groups/{group_id}": {
            "delete": {
                "tags": ["incidents"],
                "summary": "Unlink AlertGroup",
                "security": auth,
                "parameters": [
                    path_param("incident_id", "Incident id."),
                    path_param("group_id", "AlertGroup id."),
                ],
                "responses": {
                    "200": response(
                        "AlertGroup unlinked.",
                        {
                            "type": "object",
                            "required": ["unlinked", "link"],
                            "properties": {
                                "unlinked": {"type": "boolean"},
                                "link": INCIDENT_ALERT_GROUP_LINK_SCHEMA,
                            },
                        },
                    ),
                    **standard_errors,
                },
            }
        },
        "/api/incidents/{incident_id}/activity": {
            "get": {
                "tags": ["incidents"],
                "summary": "Combined Incident and authorized linked AlertGroup activity",
                "description": "Newest first. Comments appear once with their original author and source. "
                "All timestamps use explicit UTC. Only currently linked, readable AlertGroups contribute.",
                "security": auth,
                "parameters": [
                    path_param("incident_id", "Incident id."),
                    query_param(
                        "limit",
                        "Maximum combined entries (1-500), default 200.",
                        schema={
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 500,
                            "default": 200,
                        },
                    ),
                ],
                "responses": {
                    "200": response(
                        "Attributed activity entries.",
                        {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": [
                                    "source_type",
                                    "source_id",
                                    "target_type",
                                    "target_id",
                                    "record_type",
                                    "record_id",
                                    "created_at",
                                ],
                                "properties": {
                                    "source_type": {
                                        "type": "string",
                                        "enum": ["Incident", "AlertGroup"],
                                    },
                                    "source_id": {"type": "integer"},
                                    "target_type": {
                                        "type": "string",
                                        "enum": ["Incident", "AlertGroup"],
                                    },
                                    "target_id": {"type": "integer"},
                                    "record_type": {
                                        "type": "string",
                                        "enum": ["event", "comment"],
                                    },
                                    "record_id": {"type": "integer"},
                                    "actor_id": {"type": "integer", "nullable": True},
                                    "actor": {
                                        "type": "object",
                                        "nullable": True,
                                        "properties": {
                                            "id": {"type": "integer"},
                                            "username": {"type": "string"},
                                            "display_name": {
                                                "type": "string",
                                                "nullable": True,
                                            },
                                        },
                                    },
                                    "data": {
                                        "type": "object",
                                        "description": "Presentation fields only; inaccessible object references are omitted.",
                                    },
                                    "created_at": {
                                        "type": "string",
                                        "format": "date-time",
                                    },
                                    "event_type": {"type": "string"},
                                    "message": {"type": "string", "nullable": True},
                                },
                            },
                        },
                    ),
                    **standard_errors,
                },
            }
        },
        "/api/incidents/{incident_id}/responders": {
            "get": {
                "tags": ["incidents"],
                "summary": "List Incident responder requests and assignments",
                "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "responses": {
                    "200": response(
                        "Responders.",
                        {"type": "array", "items": INCIDENT_RESPONDER_SCHEMA},
                    ),
                    **standard_errors,
                },
            },
            "post": {
                "tags": ["incidents"],
                "summary": "Request operational responders",
                "description": "Creates a request, not an accepted participant. Repeated POSTs create separate requests. Delivery is queued durably and retried independently of HTTP success.",
                "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body(
                    "Exactly one target id matching target_type.",
                    INCIDENT_RESPONDER_CREATE_SCHEMA,
                ),
                "responses": {
                    "201": response(
                        "Responder request created.", INCIDENT_RESPONDER_SCHEMA
                    ),
                    **standard_errors,
                },
            },
        },
        "/api/incidents/{incident_id}/responders/{responder_id}": {
            "put": {
                "tags": ["incidents"],
                "summary": "Accept/decline/resolve responder request",
                "security": auth,
                "parameters": [
                    path_param("incident_id", "Incident id."),
                    path_param("responder_id", "Responder id."),
                ],
                "requestBody": json_body(
                    "Responder status.",
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["status"],
                        "properties": {
                            "status": {
                                "type": "string",
                                "enum": ["accepted", "declined", "resolved", "expired"],
                            },
                            "response_message": {
                                "type": "string",
                                "nullable": True,
                                "maxLength": 2000,
                            },
                        },
                    },
                ),
                "responses": {
                    "200": response(
                        "Responder status changed.", INCIDENT_RESPONDER_SCHEMA
                    ),
                    **standard_errors,
                },
            },
        },
        "/api/incidents/{incident_id}/participants": {
            "get": {
                "tags": ["incidents"],
                "summary": "List concrete operational Incident assignments",
                "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "responses": {
                    "200": response(
                        "Assigned responders.",
                        {"type": "array", "items": INCIDENT_PARTICIPANT_SCHEMA},
                    ),
                    **standard_errors,
                },
            },
            "post": {
                "tags": ["incidents"],
                "summary": "Assign concrete Incident commander/responder/communications user",
                "description": "One active assignment per user/role pair and one commander per Incident. Different roles for the same user are allowed. Conflicting or duplicate assignments return 409.",
                "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body(
                    "Operational assignment.",
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["user_id", "role"],
                        "properties": {
                            "user_id": {"type": "integer", "minimum": 1},
                            "role": {
                                "type": "string",
                                "enum": ["commander", "responder", "communications"],
                            },
                        },
                    },
                ),
                "responses": {
                    "201": response("Assignment created.", INCIDENT_PARTICIPANT_SCHEMA),
                    **standard_errors,
                },
            },
        },
        "/api/incidents/{incident_id}/participants/{participant_id}": {
            "delete": {
                "tags": ["incidents"],
                "summary": "Remove concrete assignment",
                "security": auth,
                "parameters": [
                    path_param("incident_id", "Incident id."),
                    path_param("participant_id", "Assignment id."),
                ],
                "responses": {
                    "204": {"description": "Assignment removed."},
                    **standard_errors,
                },
            },
        },
        "/api/incidents/{incident_id}/stakeholders": {
            "get": {
                "tags": ["incidents"],
                "summary": "List Incident stakeholders",
                "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "responses": {
                    "200": response(
                        "Stakeholders.",
                        {"type": "array", "items": INCIDENT_STAKEHOLDER_SCHEMA},
                    ),
                    **standard_errors,
                },
            },
            "post": {
                "tags": ["incidents"],
                "summary": "Add Incident stakeholder",
                "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body(
                    "Stakeholder user or email.", INCIDENT_STAKEHOLDER_CREATE_SCHEMA
                ),
                "responses": {
                    "200": response(
                        "Existing active stakeholder; unchanged.",
                        INCIDENT_STAKEHOLDER_SCHEMA,
                    ),
                    "201": response(
                        "Stakeholder created or reactivated.",
                        INCIDENT_STAKEHOLDER_SCHEMA,
                    ),
                    **standard_errors,
                },
            },
        },
        "/api/incidents/{incident_id}/stakeholders/{stakeholder_id}": {
            "delete": {
                "tags": ["incidents"],
                "summary": "Deactivate Incident stakeholder",
                "security": auth,
                "parameters": [
                    path_param("incident_id", "Incident id."),
                    path_param("stakeholder_id", "Stakeholder id."),
                ],
                "responses": {
                    "204": {"description": "Stakeholder deactivated."},
                    **standard_errors,
                },
            },
        },
        "/api/incidents/{incident_id}/comments": {
            "get": {
                "tags": ["incidents"],
                "summary": "List operational Incident comments",
                "description": "Technical AlertGroup comments are not copied or returned.",
                "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "responses": {
                    "200": response(
                        "Incident comments.",
                        {"type": "array", "items": INCIDENT_COMMENT_SCHEMA},
                    ),
                    **standard_errors,
                },
            },
            "post": {
                "tags": ["incidents"],
                "summary": "Add operational Incident comment",
                "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body(
                    "Comment body.",
                    {
                        "type": "object",
                        "required": ["body"],
                        "additionalProperties": False,
                        "properties": {
                            "body": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 10000,
                            }
                        },
                    },
                ),
                "responses": {
                    "201": response("Comment created.", INCIDENT_COMMENT_SCHEMA),
                    **standard_errors,
                },
            },
        },
        "/api/incidents/{incident_id}/affected-services": {
            "get": {
                "tags": ["incidents"],
                "summary": "List visible affected services",
                "description": "Services outside the caller's team read scope are omitted.",
                "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "responses": {
                    "200": response(
                        "Visible service links.",
                        {"type": "array", "items": INCIDENT_AFFECTED_SERVICE_SCHEMA},
                    ),
                    **standard_errors,
                },
            },
            "post": {
                "tags": ["incidents"],
                "summary": "Link an affected service",
                "description": "Requires Incident respond and affected Service team respond rights. Existing links return 200.",
                "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "requestBody": json_body(
                    "Service identifier.",
                    {
                        "type": "object",
                        "required": ["service_id"],
                        "additionalProperties": False,
                        "properties": {"service_id": {"type": "integer", "minimum": 1}},
                    },
                ),
                "responses": {
                    "200": response("Existing link.", INCIDENT_AFFECTED_SERVICE_SCHEMA),
                    "201": response("Link created.", INCIDENT_AFFECTED_SERVICE_SCHEMA),
                    **standard_errors,
                },
            },
        },
        "/api/incidents/{incident_id}/affected-services/{service_id}": {
            "delete": {
                "tags": ["incidents"],
                "summary": "Remove affected service link",
                "security": auth,
                "parameters": [
                    path_param("incident_id", "Incident id."),
                    path_param("service_id", "Service id."),
                ],
                "responses": {
                    "200": response(
                        "Link removed.",
                        {
                            "type": "object",
                            "properties": {"removed": {"type": "boolean"}},
                        },
                    ),
                    **standard_errors,
                },
            },
        },
        "/api/incidents/{incident_id}/events": {
            "get": {
                "tags": ["incidents"],
                "summary": "List operational Incident events",
                "security": auth,
                "parameters": [path_param("incident_id", "Incident id.")],
                "responses": {
                    "200": response(
                        "Incident events.",
                        {"type": "array", "items": INCIDENT_EVENT_SCHEMA},
                    ),
                    **standard_errors,
                },
            }
        },
    }


def _simple_transition_path(summary, description):
    return {
        "post": {
            "tags": ["incidents"],
            "summary": summary,
            "description": description,
            "security": [{"bearerAuth": []}],
            "parameters": [path_param("incident_id", "Incident id.")],
            "requestBody": json_body(
                "Current row_version.",
                {
                    "type": "object",
                    "required": ["row_version"],
                    "properties": {"row_version": {"type": "integer", "minimum": 1}},
                },
            ),
            "responses": {
                "200": response("Incident transitioned.", INCIDENT_SCHEMA),
                "400": response("Invalid transition.", ERROR_SCHEMA),
                "401": response("Authentication required.", ERROR_SCHEMA),
                "403": response("Access denied.", ERROR_SCHEMA),
                "404": response("Incident not found.", ERROR_SCHEMA),
                "409": response(
                    "Stale row_version or conflicting Incident/participant state.",
                    ERROR_SCHEMA,
                ),
            },
        }
    }
