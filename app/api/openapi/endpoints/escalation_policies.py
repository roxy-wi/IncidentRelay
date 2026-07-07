from app.api.openapi.common import response, path_param, json_body, query_param


PERMISSIONS_SCHEMA = {
    "type": "object",
    "readOnly": True,
    "properties": {
        "can_read": {"type": "boolean"},
        "can_write": {"type": "boolean"},
        "can_delete": {"type": "boolean"},
        "can_respond": {"type": "boolean"},
    },
}


ESCALATION_POLICY_RULE_SCHEMA = {
    "type": "object",
    "required": ["position", "delay_seconds", "target_type", "target_id"],
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "policy_id": {"type": "integer", "readOnly": True},
        "position": {
            "type": "integer",
            "minimum": 1,
            "description": "Rule order inside the policy. Lower values run first.",
            "example": 1,
        },
        "delay_seconds": {
            "type": "integer",
            "minimum": 0,
            "description": "Delay before moving from this rule to the next rule.",
            "example": 300,
        },
        "target_type": {
            "type": "string",
            "enum": ["rotation", "user"],
            "description": "Escalation target type.",
            "example": "rotation",
        },
        "target_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Rotation id when target_type=rotation, user id when target_type=user.",
            "example": 10,
        },
        "target_name": {
            "type": "string",
            "nullable": True,
            "readOnly": True,
            "description": "Human-readable target name.",
            "example": "Primary rotation",
        },
        "enabled": {
            "type": "boolean",
            "default": True,
            "description": "Disabled rules are skipped.",
        },
        "created_at": {"type": "string", "format": "date-time", "readOnly": True},
        "updated_at": {"type": "string", "format": "date-time", "readOnly": True},
    },
}


ESCALATION_POLICY_SCHEMA = {
    "type": "object",
    "required": ["team_id", "name"],
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "team_id": {"type": "integer", "minimum": 1},
        "team_name": {"type": "string", "nullable": True, "readOnly": True},
        "team_slug": {"type": "string", "nullable": True, "readOnly": True},
        "group_id": {"type": "integer", "nullable": True, "readOnly": True},
        "group_slug": {"type": "string", "nullable": True, "readOnly": True},
        "name": {"type": "string", "minLength": 2, "maxLength": 128, "example": "Critical escalation"},
        "description": {"type": "string", "nullable": True, "example": "Critical alerts chain"},
        "enabled": {"type": "boolean", "default": True},
        "repeat_count": {
            "type": "integer",
            "minimum": 0,
            "default": 0,
            "description": (
                "Number of additional full rule-chain repeats after the first pass. "
                "0 means run the policy once."
            ),
            "example": 1,
        },
        "rules": {
            "type": "array",
            "readOnly": True,
            "items": ESCALATION_POLICY_RULE_SCHEMA,
        },
        "permissions": PERMISSIONS_SCHEMA,
        "created_at": {"type": "string", "format": "date-time", "readOnly": True},
        "updated_at": {"type": "string", "format": "date-time", "readOnly": True},
    },
}


ESCALATION_POLICY_LIST_SCHEMA = {
    "type": "array",
    "items": ESCALATION_POLICY_SCHEMA,
}


def tags():
    """Return OpenAPI tags."""
    return [
        {
            "name": "escalation-policies",
            "description": (
                "Escalation policies define ordered alert escalation rules. "
                "Routes can use either a direct rotation or an escalation policy."
            ),
        }
    ]


def paths():
    """Return OpenAPI paths for escalation policy endpoints."""
    return {
        "/api/escalation-policies": {
            "get": {
                "tags": ["escalation-policies"],
                "summary": "List escalation policies",
                "description": "Returns escalation policies. Optional team_id filters policies by team.",
                "operationId": "listEscalationPolicies",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    query_param(
                        "team_id",
                        "Filter policies by team id.",
                        {"type": "integer", "minimum": 1},
                    )
                ],
                "responses": {
                    "200": response("List of escalation policies.", ESCALATION_POLICY_LIST_SCHEMA),
                    "401": response("Authentication required."),
                    "403": response("Permission denied."),
                },
            },
            "post": {
                "tags": ["escalation-policies"],
                "summary": "Create escalation policy",
                "description": (
                    "Creates an escalation policy for a team. "
                    "Rules are created separately."
                ),
                "operationId": "createEscalationPolicy",
                "security": [{"bearerAuth": []}],
                "requestBody": json_body("Escalation policy properties.", ESCALATION_POLICY_SCHEMA),
                "responses": {
                    "201": response("Escalation policy created.", ESCALATION_POLICY_SCHEMA),
                    "400": response("Validation error."),
                    "401": response("Authentication required."),
                    "403": response("Permission denied."),
                    "409": response("Conflict."),
                },
            },
        },
        "/api/escalation-policies/{policy_id}": {
            "get": {
                "tags": ["escalation-policies"],
                "summary": "Get escalation policy",
                "description": "Returns one escalation policy, including its rules.",
                "operationId": "getEscalationPolicy",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("policy_id", "Escalation policy id.")],
                "responses": {
                    "200": response("Escalation policy details.", ESCALATION_POLICY_SCHEMA),
                    "401": response("Authentication required."),
                    "403": response("Permission denied."),
                    "404": response("Escalation policy not found."),
                },
            },
            "put": {
                "tags": ["escalation-policies"],
                "summary": "Update escalation policy",
                "description": "Updates policy metadata and enabled/repeat settings.",
                "operationId": "updateEscalationPolicy",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("policy_id", "Escalation policy id.")],
                "requestBody": json_body("Updated escalation policy properties.", ESCALATION_POLICY_SCHEMA),
                "responses": {
                    "200": response("Escalation policy updated.", ESCALATION_POLICY_SCHEMA),
                    "400": response("Validation error."),
                    "401": response("Authentication required."),
                    "403": response("Permission denied."),
                    "404": response("Escalation policy not found."),
                    "409": response("Conflict."),
                },
            },
            "delete": {
                "tags": ["escalation-policies"],
                "summary": "Delete escalation policy",
                "description": "Deletes or disables an escalation policy. Existing alerts keep stored policy state.",
                "operationId": "deleteEscalationPolicy",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("policy_id", "Escalation policy id.")],
                "responses": {
                    "200": response("Escalation policy deleted or disabled."),
                    "401": response("Authentication required."),
                    "403": response("Permission denied."),
                    "404": response("Escalation policy not found."),
                },
            },
        },
        "/api/escalation-policies/{policy_id}/rules": {
            "post": {
                "tags": ["escalation-policies"],
                "summary": "Create escalation policy rule",
                "description": (
                    "Creates a rule inside an escalation policy. "
                    "Rules are evaluated by position in ascending order."
                ),
                "operationId": "createEscalationPolicyRule",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("policy_id", "Escalation policy id.")],
                "requestBody": json_body("Escalation policy rule properties.", ESCALATION_POLICY_RULE_SCHEMA),
                "responses": {
                    "201": response("Escalation policy rule created.", ESCALATION_POLICY_RULE_SCHEMA),
                    "400": response("Validation error or target team mismatch."),
                    "401": response("Authentication required."),
                    "403": response("Permission denied."),
                    "404": response("Escalation policy or target not found."),
                    "409": response("Conflict."),
                },
            }
        },
        "/api/escalation-policies/rules/{rule_id}": {
            "put": {
                "tags": ["escalation-policies"],
                "summary": "Update escalation policy rule",
                "description": "Updates a policy rule target, position, delay and enabled flag.",
                "operationId": "updateEscalationPolicyRule",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("rule_id", "Escalation policy rule id.")],
                "requestBody": json_body("Updated escalation policy rule properties.", ESCALATION_POLICY_RULE_SCHEMA),
                "responses": {
                    "200": response("Escalation policy rule updated.", ESCALATION_POLICY_RULE_SCHEMA),
                    "400": response("Validation error or target team mismatch."),
                    "401": response("Authentication required."),
                    "403": response("Permission denied."),
                    "404": response("Escalation policy rule or target not found."),
                    "409": response("Conflict."),
                },
            },
            "delete": {
                "tags": ["escalation-policies"],
                "summary": "Delete escalation policy rule",
                "description": "Deletes one escalation policy rule.",
                "operationId": "deleteEscalationPolicyRule",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("rule_id", "Escalation policy rule id.")],
                "responses": {
                    "200": response("Escalation policy rule deleted."),
                    "401": response("Authentication required."),
                    "403": response("Permission denied."),
                    "404": response("Escalation policy rule not found."),
                },
            },
        },
    }
