from app.api.openapi.common import ERROR_SCHEMA, json_body, path_param, query_param, response


BUSINESS_SERVICE_STATUSES = [
    "unknown",
    "operational",
    "degraded",
    "partial_outage",
    "major_outage",
    "maintenance",
]

BUSINESS_SERVICE_CRITICALITIES = [
    "critical",
    "important",
    "optional",
]

BUSINESS_SERVICE_TIERS = [
    "tier_1",
    "tier_2",
    "tier_3",
    "tier_4",
]

BUSINESS_SERVICE_COMPONENT_CRITICALITIES = [
    "required",
    "critical",
    "important",
    "optional",
    "informational",
]


BUSINESS_SERVICE_COMPONENT_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "business_service_id": {"type": "integer"},
        "business_service_slug": {"type": "string", "nullable": True},
        "business_service_name": {"type": "string", "nullable": True},

        "service_id": {"type": "integer"},
        "service_slug": {"type": "string", "nullable": True},
        "service_name": {"type": "string", "nullable": True},
        "service_status": {
            "type": "string",
            "nullable": True,
            "description": "Raw persisted technical service status.",
        },
        "effective_status": {
            "type": "string",
            "nullable": True,
            "enum": BUSINESS_SERVICE_STATUSES,
            "description": "Calculated Service Impact v2 status used by Business Services.",
        },
        "effective_status_reason": {
            "type": "string",
            "nullable": True,
            "description": "Primary reason for the effective status, for example alert_group or upstream_dependency.",
        },
        "alert_impact_status": {
            "type": "string",
            "nullable": True,
            "enum": BUSINESS_SERVICE_STATUSES,
            "description": "Effective status contribution from open alert groups.",
        },
        "dependency_impact_status": {
            "type": "string",
            "nullable": True,
            "enum": BUSINESS_SERVICE_STATUSES,
            "description": "Effective status contribution from upstream dependencies.",
        },
        "open_alert_groups": {
            "type": "integer",
            "minimum": 0,
            "description": "Number of open alert groups affecting the component service.",
        },
        "critical_open_alert_groups": {
            "type": "integer",
            "minimum": 0,
            "description": "Number of critical open alert groups affecting the component service.",
        },
        "upstream_issues_count": {
            "type": "integer",
            "minimum": 0,
            "description": "Number of upstream dependency issues affecting the component service.",
        },
        "service_criticality": {"type": "string", "nullable": True},
        "service_environment": {"type": "string", "nullable": True},

        "team_id": {"type": "integer", "nullable": True},
        "team_slug": {"type": "string", "nullable": True},
        "team_name": {"type": "string", "nullable": True},

        "component_type": {
            "type": "string",
            "enum": ["technical_service"],
            "default": "technical_service",
        },
        "criticality": {
            "type": "string",
            "enum": BUSINESS_SERVICE_COMPONENT_CRITICALITIES,
            "default": "required",
        },
        "impact_weight": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
            "default": 100,
        },
        "position": {
            "type": "integer",
            "minimum": 0,
            "default": 0,
        },
        "status_rule": {
            "type": "string",
            "enum": ["inherit"],
            "default": "inherit",
        },
        "description": {"type": "string", "nullable": True},
        "enabled": {"type": "boolean", "default": True},

        "created_at": {"type": "string", "format": "date-time", "nullable": True},
        "updated_at": {"type": "string", "format": "date-time", "nullable": True},
    },
}


BUSINESS_SERVICE_STATUS_HISTORY_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "business_service_id": {"type": "integer"},
        "old_status": {"type": "string", "nullable": True},
        "new_status": {"type": "string"},
        "status_source": {"type": "string"},
        "message": {"type": "string", "nullable": True},
        "impact_score": {"type": "integer"},
        "component_snapshot": {"type": "array", "items": {"type": "object"}},
        "created_at": {"type": "string", "format": "date-time", "nullable": True},
    },
}


BUSINESS_SERVICE_IMPACT_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "business_service_id": {"type": "integer"},
        "business_service_slug": {"type": "string"},
        "business_service_name": {"type": "string"},
        "public_name": {"type": "string"},
        "service_id": {"type": "integer", "nullable": True},
        "service_slug": {"type": "string", "nullable": True},
        "service_name": {"type": "string", "nullable": True},
        "impact_status": {"type": "string", "enum": BUSINESS_SERVICE_STATUSES},
        "impact_score": {"type": "integer"},
        "relation": {"type": "string"},
        "reason": {"type": "string", "nullable": True},
        "active": {"type": "boolean"},
        "component_snapshot": {"type": "array", "items": {"type": "object"}},
        "first_seen_at": {"type": "string", "format": "date-time", "nullable": True},
        "last_seen_at": {"type": "string", "format": "date-time", "nullable": True},
        "updated_at": {"type": "string", "format": "date-time", "nullable": True},
    },
}


BUSINESS_SERVICE_SCHEMA = {
    "type": "object",
    "required": ["group_id", "slug", "name"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "integer", "readOnly": True},

        "group_id": {"type": "integer", "minimum": 1},
        "group_slug": {"type": "string", "nullable": True, "readOnly": True},
        "group_name": {"type": "string", "nullable": True, "readOnly": True},

        "owner_team_id": {"type": "integer", "minimum": 1, "nullable": True},
        "owner_team_slug": {"type": "string", "nullable": True, "readOnly": True},
        "owner_team_name": {"type": "string", "nullable": True, "readOnly": True},

        "slug": {"type": "string", "minLength": 1, "maxLength": 64},
        "name": {"type": "string", "minLength": 1, "maxLength": 255},
        "description": {"type": "string", "nullable": True, "maxLength": 5000},

        "status": {
            "type": "string",
            "enum": BUSINESS_SERVICE_STATUSES,
            "readOnly": True,
        },
        "status_source": {"type": "string", "readOnly": True},
        "status_message": {"type": "string", "nullable": True, "readOnly": True},
        "status_updated_at": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
            "readOnly": True,
        },

        "manual_status": {
            "type": "string",
            "nullable": True,
            "enum": [
                "operational",
                "degraded",
                "partial_outage",
                "major_outage",
                "maintenance",
            ],
            "description": "Active manual status override value, if one is configured.",
        },
        "manual_status_message": {
            "type": "string",
            "nullable": True,
            "description": "Operator-provided message for the manual status override.",
        },
        "manual_status_until": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
            "description": "UTC expiration time for the manual status override.",
        },
        "manual_status_set_by_id": {
            "type": "integer",
            "nullable": True,
            "description": "User ID that set the manual status override.",
        },
        "manual_status_set_at": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
            "description": "UTC time when the manual status override was set.",
        },
        "manual_status_active": {
            "type": "boolean",
            "description": "Whether the manual status override is currently active.",
        },

        "criticality": {
            "type": "string",
            "enum": BUSINESS_SERVICE_CRITICALITIES,
            "default": "important",
        },
        "tier": {
            "type": "string",
            "enum": BUSINESS_SERVICE_TIERS,
            "default": "tier_2",
        },

        "public": {"type": "boolean", "default": True},
        "public_name": {"type": "string", "nullable": True, "maxLength": 255},
        "public_description": {"type": "string", "nullable": True, "maxLength": 5000},
        "public_order": {"type": "integer", "minimum": 0, "default": 100},

        "labels": {"type": "object", "additionalProperties": True, "default": {}},
        "metadata": {"type": "object", "additionalProperties": True, "default": {}},

        "enabled": {"type": "boolean", "default": True},

        "components_count": {"type": "integer", "readOnly": True},
        "components": {
            "type": "array",
            "readOnly": True,
            "items": BUSINESS_SERVICE_COMPONENT_SCHEMA,
        },
        "status_history": {
            "type": "array",
            "readOnly": True,
            "items": BUSINESS_SERVICE_STATUS_HISTORY_SCHEMA,
        },

        "created_at": {"type": "string", "format": "date-time", "nullable": True, "readOnly": True},
        "updated_at": {"type": "string", "format": "date-time", "nullable": True, "readOnly": True},
    },
}

BUSINESS_SERVICE_MANUAL_STATUS_INPUT_SCHEMA = {
    "type": "object",
    "required": ["status"],
    "properties": {
        "status": {
            "type": "string",
            "enum": [
                "operational",
                "degraded",
                "partial_outage",
                "major_outage",
                "maintenance",
            ],
            "description": "Manual business service status.",
        },
        "message": {
            "type": "string",
            "nullable": True,
            "maxLength": 2000,
            "description": "Optional message explaining the manual override.",
        },
        "until": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
            "description": "Optional UTC expiration time. If omitted, the override remains active until cleared.",
        },
    },
}

BUSINESS_SERVICE_COMPONENT_INPUT_SCHEMA = {
    "type": "object",
    "required": ["service_id"],
    "additionalProperties": False,
    "properties": {
        "service_id": {"type": "integer", "minimum": 1},
        "component_type": {
            "type": "string",
            "enum": ["technical_service"],
            "default": "technical_service",
        },
        "criticality": {
            "type": "string",
            "enum": BUSINESS_SERVICE_COMPONENT_CRITICALITIES,
            "default": "required",
        },
        "impact_weight": {"type": "integer", "minimum": 0, "maximum": 100, "default": 100},
        "position": {"type": "integer", "minimum": 0, "default": 0},
        "status_rule": {"type": "string", "enum": ["inherit"], "default": "inherit"},
        "description": {"type": "string", "nullable": True, "maxLength": 5000},
        "enabled": {"type": "boolean", "default": True},
    },
}


def tags():
    """Return OpenAPI tags."""
    return [
        {
            "name": "business-services",
            "description": (
                "Business-facing services used for status pages, business impact "
                "and customer-facing availability views."
            ),
        }
    ]


def paths():
    """Return OpenAPI paths for business service endpoints."""
    return {
        "/api/business-services": {
            "get": {
                "tags": ["business-services"],
                "summary": "List business services",
                "operationId": "listBusinessServices",
                "parameters": [
                    query_param("group_id", "Filter by group id.", {"type": "integer", "minimum": 1}),
                    query_param("public", "Return public business services only.", {"type": "boolean"}),
                ],
                "responses": {
                    "200": response(
                        "Business services.",
                        {"type": "array", "items": BUSINESS_SERVICE_SCHEMA},
                    ),
                    "401": response("Authentication required.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["business-services"],
                "summary": "Create business service",
                "operationId": "createBusinessService",
                "requestBody": json_body("Business service properties.", BUSINESS_SERVICE_SCHEMA),
                "responses": {
                    "201": response("Business service created.", BUSINESS_SERVICE_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "401": response("Authentication required.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                },
            },
        },
        "/api/business-services/{business_service_id}": {
            "get": {
                "tags": ["business-services"],
                "summary": "Get business service details",
                "operationId": "getBusinessService",
                "parameters": [path_param("business_service_id", "Business service id.")],
                "responses": {
                    "200": response("Business service details.", BUSINESS_SERVICE_SCHEMA),
                    "401": response("Authentication required.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Business service not found.", ERROR_SCHEMA),
                },
            },
            "put": {
                "tags": ["business-services"],
                "summary": "Update business service",
                "operationId": "updateBusinessService",
                "parameters": [path_param("business_service_id", "Business service id.")],
                "requestBody": json_body("Updated business service properties.", BUSINESS_SERVICE_SCHEMA),
                "responses": {
                    "200": response("Business service updated.", BUSINESS_SERVICE_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "401": response("Authentication required.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Business service not found.", ERROR_SCHEMA),
                },
            },
            "delete": {
                "tags": ["business-services"],
                "summary": "Delete business service",
                "operationId": "deleteBusinessService",
                "parameters": [path_param("business_service_id", "Business service id.")],
                "responses": {
                    "204": {"description": "Business service deleted."},
                    "401": response("Authentication required.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Business service not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/business-services/{business_service_id}/components": {
            "get": {
                "tags": ["business-services"],
                "summary": "List business service components",
                "operationId": "listBusinessServiceComponents",
                "parameters": [path_param("business_service_id", "Business service id.")],
                "responses": {
                    "200": response(
                        "Business service components.",
                        {"type": "array", "items": BUSINESS_SERVICE_COMPONENT_SCHEMA},
                    ),
                    "401": response("Authentication required.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Business service not found.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["business-services"],
                "summary": "Create business service component",
                "operationId": "createBusinessServiceComponent",
                "parameters": [path_param("business_service_id", "Business service id.")],
                "requestBody": json_body(
                    "Business service component properties.",
                    BUSINESS_SERVICE_COMPONENT_INPUT_SCHEMA,
                ),
                "responses": {
                    "201": response(
                        "Business service component created.",
                        BUSINESS_SERVICE_COMPONENT_SCHEMA,
                    ),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "401": response("Authentication required.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Business service not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/business-services/components/{component_id}": {
            "put": {
                "tags": ["business-services"],
                "summary": "Update business service component",
                "operationId": "updateBusinessServiceComponent",
                "parameters": [path_param("component_id", "Business service component id.")],
                "requestBody": json_body(
                    "Updated business service component properties.",
                    BUSINESS_SERVICE_COMPONENT_INPUT_SCHEMA,
                ),
                "responses": {
                    "200": response(
                        "Business service component updated.",
                        BUSINESS_SERVICE_COMPONENT_SCHEMA,
                    ),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "401": response("Authentication required.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Business service component not found.", ERROR_SCHEMA),
                },
            },
            "delete": {
                "tags": ["business-services"],
                "summary": "Delete business service component",
                "operationId": "deleteBusinessServiceComponent",
                "parameters": [path_param("component_id", "Business service component id.")],
                "responses": {
                    "204": {"description": "Business service component deleted."},
                    "401": response("Authentication required.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Business service component not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/business-services/{business_service_id}/recalculate": {
            "post": {
                "tags": ["business-services"],
                "summary": "Recalculate business service status",
                "operationId": "recalculateBusinessService",
                "parameters": [path_param("business_service_id", "Business service id.")],
                "responses": {
                    "200": response("Business service recalculated.", BUSINESS_SERVICE_SCHEMA),
                    "401": response("Authentication required.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Business service not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/business-services/{business_service_id}/manual-status": {
            "post": {
                "tags": ["business-services"],
                "summary": "Set business service manual status override",
                "description": (
                    "Set a manual status override for a business service. "
                    "Manual status has priority over calculated status until it expires or is cleared."
                ),
                "parameters": [
                    path_param("business_service_id", "Business service ID"),
                ],
                "requestBody": json_body(
                    "Manual status override payload.",
                    BUSINESS_SERVICE_MANUAL_STATUS_INPUT_SCHEMA,
                ),
                "responses": {
                    "200": response("Manual status override set", BUSINESS_SERVICE_SCHEMA),
                    "400": response("Invalid manual status payload", ERROR_SCHEMA),
                    "401": response("Authentication is required", ERROR_SCHEMA),
                    "403": response("Access denied", ERROR_SCHEMA),
                    "404": response("Business service not found", ERROR_SCHEMA),
                },
            },
            "delete": {
                "tags": ["business-services"],
                "summary": "Clear business service manual status override",
                "description": "Clear the manual status override and recalculate the business service status.",
                "parameters": [
                    path_param("business_service_id", "Business service ID"),
                ],
                "responses": {
                    "200": response("Manual status override cleared", BUSINESS_SERVICE_SCHEMA),
                    "401": response("Authentication is required", ERROR_SCHEMA),
                    "403": response("Access denied", ERROR_SCHEMA),
                    "404": response("Business service not found", ERROR_SCHEMA),
                },
            },
        },
    }
