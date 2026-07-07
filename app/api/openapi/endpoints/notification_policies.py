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


CHANNEL_REFERENCE_SCHEMA = {
    "type": "object",
    "readOnly": True,
    "properties": {
        "id": {"type": "integer"},
        "team_id": {"type": "integer"},
        "name": {"type": "string"},
        "channel_type": {"type": "string"},
        "enabled": {"type": "boolean"},
    },
}


NOTIFICATION_POLICY_RULE_SCHEMA = {
    "type": "object",
    "required": ["name", "event_types", "channel_ids"],
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "policy_id": {"type": "integer", "readOnly": True},
        "name": {
            "type": "string",
            "minLength": 2,
            "maxLength": 128,
            "example": "Critical production alerts",
        },
        "description": {
            "type": "string",
            "nullable": True,
            "example": "Send critical alerts to Mattermost and Telegram.",
        },
        "position": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "description": "Rule evaluation order. Lower positions run first.",
            "example": 1,
        },
        "event_types": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {
                "type": "string",
                "enum": [
                    "notification",
                    "reminder",
                    "escalation",
                ],
            },
            "default": [
                "notification",
                "reminder",
                "escalation",
            ],
        },
        "matchers": {
            "type": "object",
            "additionalProperties": True,
            "default": {},
            "description": (
                "Alert matcher object. An empty object matches every alert. "
                "The format is shared with service match rules."
            ),
            "example": {
                "severity": "critical",
                "labels": {
                    "environment": "production",
                },
            },
        },
        "channel_ids": {
            "type": "array",
            "uniqueItems": True,
            "items": {
                "type": "integer",
                "minimum": 1,
            },
            "description": (
                "Notification channels selected by this rule. "
                "Enabled rules require at least one channel."
            ),
            "example": [4, 7],
        },
        "channels": {
            "type": "array",
            "readOnly": True,
            "items": CHANNEL_REFERENCE_SCHEMA,
        },
        "continue_matching": {
            "type": "boolean",
            "default": False,
            "description": (
                "Continue evaluating following rules after this rule matches."
            ),
        },
        "enabled": {
            "type": "boolean",
            "default": True,
            "description": "Disabled rules are skipped.",
        },
        "created_at": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
            "readOnly": True,
        },
        "updated_at": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
            "readOnly": True,
        },
    },
}


NOTIFICATION_POLICY_SCHEMA = {
    "type": "object",
    "required": ["team_id", "name"],
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "team_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Team that owns the policy.",
        },
        "team_name": {
            "type": "string",
            "nullable": True,
            "readOnly": True,
        },
        "team_slug": {
            "type": "string",
            "nullable": True,
            "readOnly": True,
        },
        "name": {
            "type": "string",
            "minLength": 2,
            "maxLength": 128,
            "example": "Production notifications",
        },
        "description": {
            "type": "string",
            "nullable": True,
            "example": "Shared notification rules for production services.",
        },
        "enabled": {
            "type": "boolean",
            "default": True,
            "description": (
                "Disabled policies cannot be assigned to new services."
            ),
        },
        "rules_count": {
            "type": "integer",
            "minimum": 0,
            "readOnly": True,
        },
        "services_count": {
            "type": "integer",
            "minimum": 0,
            "readOnly": True,
        },
        "rules": {
            "type": "array",
            "readOnly": True,
            "items": NOTIFICATION_POLICY_RULE_SCHEMA,
        },
        "permissions": PERMISSIONS_SCHEMA,
        "created_at": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
            "readOnly": True,
        },
        "updated_at": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
            "readOnly": True,
        },
    },
}


NOTIFICATION_POLICY_LIST_SCHEMA = {
    "type": "array",
    "items": NOTIFICATION_POLICY_SCHEMA,
}


NOTIFICATION_POLICY_RULE_LIST_SCHEMA = {
    "type": "array",
    "items": NOTIFICATION_POLICY_RULE_SCHEMA,
}


RULE_ORDER_SCHEMA = {
    "type": "object",
    "required": ["rule_ids"],
    "properties": {
        "rule_ids": {
            "type": "array",
            "uniqueItems": True,
            "items": {
                "type": "integer",
                "minimum": 1,
            },
            "description": (
                "Complete ordered list of all active rule ids in the policy."
            ),
            "example": [12, 8, 15],
        },
    },
}


DELETE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "deleted": {"type": "boolean", "example": True},
        "id": {"type": "integer", "example": 1},
    },
}


def tags():
    """Return OpenAPI tags."""
    return [
        {
            "name": "notification-policies",
            "description": (
                "Service notification policies select shared notification "
                "channels according to alert attributes and event type."
            ),
        }
    ]


def paths():
    """Return OpenAPI paths for notification policy endpoints."""
    return {
        "/api/notification-policies": {
            "get": {
                "tags": ["notification-policies"],
                "summary": "List notification policies",
                "description": (
                    "Returns notification policies visible to the current "
                    "user. Policies can be filtered by team and enabled state."
                ),
                "operationId": "listNotificationPolicies",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    query_param(
                        "team_id",
                        "Filter policies by team id.",
                        {"type": "integer", "minimum": 1},
                    ),
                    query_param(
                        "enabled_only",
                        "Set to 1 to return only enabled policies.",
                        {
                            "type": "integer",
                            "enum": [0, 1],
                            "default": 0,
                        },
                    ),
                ],
                "responses": {
                    "200": response(
                        "List of notification policies.",
                        NOTIFICATION_POLICY_LIST_SCHEMA,
                    ),
                    "401": response("Authentication required."),
                    "403": response("Permission denied."),
                },
            },
            "post": {
                "tags": ["notification-policies"],
                "summary": "Create notification policy",
                "description": (
                    "Creates a reusable notification policy for a team. "
                    "Rules are created separately."
                ),
                "operationId": "createNotificationPolicy",
                "security": [{"bearerAuth": []}],
                "requestBody": json_body(
                    "Notification policy properties.",
                    NOTIFICATION_POLICY_SCHEMA,
                ),
                "responses": {
                    "201": response(
                        "Notification policy created.",
                        NOTIFICATION_POLICY_SCHEMA,
                    ),
                    "400": response("Validation error."),
                    "401": response("Authentication required."),
                    "403": response("Permission denied."),
                    "409": response(
                        "A policy with the same name already exists."
                    ),
                },
            },
        },
        "/api/notification-policies/{policy_id}": {
            "get": {
                "tags": ["notification-policies"],
                "summary": "Get notification policy",
                "description": (
                    "Returns one notification policy including its ordered "
                    "rules and selected channels."
                ),
                "operationId": "getNotificationPolicy",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("policy_id", "Notification policy id.")
                ],
                "responses": {
                    "200": response(
                        "Notification policy details.",
                        NOTIFICATION_POLICY_SCHEMA,
                    ),
                    "401": response("Authentication required."),
                    "403": response("Permission denied."),
                    "404": response("Notification policy not found."),
                },
            },
            "put": {
                "tags": ["notification-policies"],
                "summary": "Update notification policy",
                "description": (
                    "Updates policy name, description or enabled state."
                ),
                "operationId": "updateNotificationPolicy",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("policy_id", "Notification policy id.")
                ],
                "requestBody": json_body(
                    "Updated notification policy properties.",
                    NOTIFICATION_POLICY_SCHEMA,
                ),
                "responses": {
                    "200": response(
                        "Notification policy updated.",
                        NOTIFICATION_POLICY_SCHEMA,
                    ),
                    "400": response("Validation error."),
                    "401": response("Authentication required."),
                    "403": response("Permission denied."),
                    "404": response("Notification policy not found."),
                    "409": response(
                        "A policy with the same name already exists."
                    ),
                },
            },
            "delete": {
                "tags": ["notification-policies"],
                "summary": "Delete notification policy",
                "description": (
                    "Soft-deletes a notification policy. A policy assigned "
                    "to an active service cannot be deleted."
                ),
                "operationId": "deleteNotificationPolicy",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("policy_id", "Notification policy id.")
                ],
                "responses": {
                    "200": response(
                        "Notification policy deleted.",
                        DELETE_RESPONSE_SCHEMA,
                    ),
                    "401": response("Authentication required."),
                    "403": response("Permission denied."),
                    "404": response("Notification policy not found."),
                    "409": response(
                        "Notification policy is assigned to a service."
                    ),
                },
            },
        },
        "/api/notification-policies/{policy_id}/rules": {
            "post": {
                "tags": ["notification-policies"],
                "summary": "Create notification policy rule",
                "description": (
                    "Creates an ordered rule inside a notification policy."
                ),
                "operationId": "createNotificationPolicyRule",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("policy_id", "Notification policy id.")
                ],
                "requestBody": json_body(
                    "Notification policy rule properties.",
                    NOTIFICATION_POLICY_RULE_SCHEMA,
                ),
                "responses": {
                    "201": response(
                        "Notification policy rule created.",
                        NOTIFICATION_POLICY_RULE_SCHEMA,
                    ),
                    "400": response(
                        "Validation error or channel team mismatch."
                    ),
                    "401": response("Authentication required."),
                    "403": response("Permission denied."),
                    "404": response(
                        "Notification policy or channel not found."
                    ),
                },
            },
        },
        "/api/notification-policies/{policy_id}/rules/{rule_id}": {
            "put": {
                "tags": ["notification-policies"],
                "summary": "Update notification policy rule",
                "description": (
                    "Updates rule events, matchers, channels, position and "
                    "matching behavior."
                ),
                "operationId": "updateNotificationPolicyRule",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("policy_id", "Notification policy id."),
                    path_param("rule_id", "Notification policy rule id."),
                ],
                "requestBody": json_body(
                    "Updated notification policy rule properties.",
                    NOTIFICATION_POLICY_RULE_SCHEMA,
                ),
                "responses": {
                    "200": response(
                        "Notification policy rule updated.",
                        NOTIFICATION_POLICY_RULE_SCHEMA,
                    ),
                    "400": response(
                        "Validation error or channel team mismatch."
                    ),
                    "401": response("Authentication required."),
                    "403": response("Permission denied."),
                    "404": response(
                        "Notification policy, rule or channel not found."
                    ),
                },
            },
            "delete": {
                "tags": ["notification-policies"],
                "summary": "Delete notification policy rule",
                "description": (
                    "Soft-deletes one rule and normalizes positions of the "
                    "remaining rules."
                ),
                "operationId": "deleteNotificationPolicyRule",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("policy_id", "Notification policy id."),
                    path_param("rule_id", "Notification policy rule id."),
                ],
                "responses": {
                    "200": response(
                        "Notification policy rule deleted.",
                        DELETE_RESPONSE_SCHEMA,
                    ),
                    "401": response("Authentication required."),
                    "403": response("Permission denied."),
                    "404": response(
                        "Notification policy or rule not found."
                    ),
                },
            },
        },
        "/api/notification-policies/{policy_id}/rules/order": {
            "put": {
                "tags": ["notification-policies"],
                "summary": "Reorder notification policy rules",
                "description": (
                    "Replaces the complete ordering of all active rules in "
                    "the notification policy."
                ),
                "operationId": "reorderNotificationPolicyRules",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("policy_id", "Notification policy id.")
                ],
                "requestBody": json_body(
                    "Complete notification policy rule order.",
                    RULE_ORDER_SCHEMA,
                ),
                "responses": {
                    "200": response(
                        "Notification policy rules reordered.",
                        NOTIFICATION_POLICY_RULE_LIST_SCHEMA,
                    ),
                    "400": response(
                        "The order does not contain every active rule once."
                    ),
                    "401": response("Authentication required."),
                    "403": response("Permission denied."),
                    "404": response("Notification policy not found."),
                },
            },
        },
    }
