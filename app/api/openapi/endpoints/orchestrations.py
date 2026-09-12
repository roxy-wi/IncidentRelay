"""OpenAPI documentation for Event Orchestration control-plane APIs."""

from app.api.openapi.common import ERROR_SCHEMA, json_body, path_param, query_param, response
from app.services.integrations.normalizers.registry import SUPPORTED_NORMALIZER_SOURCES
from app.services.alerts.event_history import ALERT_EVENT_HISTORY_LEVELS
from app.services.orchestration.actions import (
    EVENT_ACTIONS,
    FAILURE_MODES,
    PROCESS_DISPOSITIONS,
    SUPPORTED_ACTION_TYPES,
    TRACE_LEVELS,
)
from app.services.orchestration.conditions import SUPPORTED_OPERATORS


ORCHESTRATION_MODES = ["active", "shadow", "disabled"]
ORCHESTRATION_COMPATIBILITY_MODES = ["legacy", "hybrid", "orchestration"]
ORCHESTRATION_SCOPES = ["global", "service"]
ORCHESTRATION_VERSION_STATUSES = ["draft", "published", "archived"]
ORCHESTRATION_PROCESSING_MODES = [
    "continue",
    "stop",
    "evaluate_children",
    "children_then_continue",
]

ACTOR_SCHEMA = {
    "type": "object",
    "nullable": True,
    "properties": {
        "id": {"type": "integer", "minimum": 1},
        "username": {"type": "string"},
        "display_name": {"type": "string", "nullable": True},
        "label": {"type": "string"},
    },
    "additionalProperties": False,
}

PERMISSION_MAP_SCHEMA = {
    "type": "object",
    "properties": {
        key: {"type": "boolean"}
        for key in (
            "view",
            "create",
            "edit",
            "publish",
            "delete",
            "simulate",
            "replay",
            "view_executions",
            "manage_actions",
        )
    },
    "additionalProperties": False,
}

CONDITION_SCHEMA = {
    "type": "object",
    "required": ["field", "operator"],
    "properties": {
        "field": {
            "type": "string",
            "description": (
                "Field reference such as event.severity, labels.environment, "
                "variables.region, raw.payload or route.id."
            ),
            "example": "labels.environment",
        },
        "operator": {
            "type": "string",
            "enum": sorted(SUPPORTED_OPERATORS),
            "example": "equals",
        },
        "value": {
            "description": (
                "Expected JSON value. Operators such as exists, not_exists, "
                "is_true and is_false do not require it."
            ),
            "nullable": True,
        },
    },
    "additionalProperties": False,
}

CONDITION_GROUP_SCHEMA = {
    "type": "object",
    "minProperties": 1,
    "maxProperties": 1,
    "properties": {
        "all": {
            "type": "array",
            "items": {"$ref": "#/components/schemas/OrchestrationConditionTree"},
            "description": "All child nodes must match (logical AND).",
        },
        "any": {
            "type": "array",
            "items": {"$ref": "#/components/schemas/OrchestrationConditionTree"},
            "description": "At least one child node must match (logical OR).",
        },
        "none": {
            "type": "array",
            "items": {"$ref": "#/components/schemas/OrchestrationConditionTree"},
            "description": "No child node may match (logical NOT).",
        },
    },
    "additionalProperties": False,
}

ACTION_SCHEMA = {
    "type": "object",
    "required": ["type"],
    "properties": {
        "type": {
            "type": "string",
            "enum": sorted(SUPPORTED_ACTION_TYPES),
            "description": "Deterministic built-in action type.",
            "example": "set_severity",
        },
        "value": {
            "nullable": True,
            "description": "Literal value used by set/extraction actions.",
        },
        "template": {
            "type": "string",
            "description": "Restricted template rendered from orchestration context.",
        },
        "field": {"type": "string"},
        "source": {"type": "string"},
        "name": {"type": "string"},
        "pattern": {"type": "string"},
        "group": {"type": "integer", "minimum": 0},
        "path": {"type": "string"},
        "separator": {"type": "string"},
        "index": {"type": "integer"},
        "route_id": {"type": "integer", "minimum": 1},
        "team_id": {"type": "integer", "minimum": 1},
        "service_id": {"type": "integer", "minimum": 1},
        "escalation_policy_id": {"type": "integer", "minimum": 1},
        "notification_policy_id": {"type": "integer", "minimum": 1},
        "priority_policy_id": {"type": "integer", "minimum": 1},
        "action_id": {"type": "integer", "minimum": 1},
        "event_action": {"type": "string", "enum": sorted(EVENT_ACTIONS)},
        "level": {
            "type": "string",
            "enum": sorted(TRACE_LEVELS | ALERT_EVENT_HISTORY_LEVELS),
            "description": (
                "Level for set_trace_level or set_alert_event_history. "
                "Trace supports full/compact/disabled; alert event history "
                "supports full/initial/disabled."
            ),
        },
        "group_key": {"type": "string"},
        "dedup_key": {"type": "string"},
        "window_seconds": {"type": "integer", "minimum": 0, "maximum": 86400},
        "seconds": {"type": "integer", "minimum": 1, "maximum": 604800},
        "reason": {"type": "string", "maxLength": 8192},
        "retrigger": {"type": "string"},
        "failure_mode": {"type": "string", "enum": sorted(FAILURE_MODES)},
        "disposition": {"type": "string", "enum": sorted(PROCESS_DISPOSITIONS)},
    },
    "additionalProperties": True,
    "description": (
        "One safe built-in mutation, routing, extraction, disposition or queued "
        "webhook action. Arbitrary shell, Python and container execution are not supported."
    ),
}

RULE_SCHEMA = {
    "type": "object",
    "required": ["name", "condition_tree", "actions"],
    "properties": {
        "name": {"type": "string", "minLength": 1, "maxLength": 255},
        "description": {"type": "string", "nullable": True, "maxLength": 8192},
        "enabled": {"type": "boolean", "default": True},
        "condition_tree": {"$ref": "#/components/schemas/OrchestrationConditionTree"},
        "actions": {
            "type": "array",
            "maxItems": 128,
            "items": {"$ref": "#/components/schemas/OrchestrationAction"},
        },
        "processing_mode": {
            "type": "string",
            "enum": ORCHESTRATION_PROCESSING_MODES,
            "default": "continue",
        },
        "children": {
            "type": "array",
            "items": {"$ref": "#/components/schemas/OrchestrationRule"},
        },
    },
    "additionalProperties": False,
}

DEFINITION_SCHEMA = {
    "type": "object",
    "required": ["schema_version", "rules"],
    "properties": {
        "schema_version": {"type": "integer", "enum": [1], "default": 1},
        "rules": {
            "type": "array",
            "maxItems": 512,
            "items": {"$ref": "#/components/schemas/OrchestrationRule"},
        },
    },
    "additionalProperties": False,
}

VERSION_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "orchestration_id": {"type": "integer"},
        "version_number": {"type": "integer", "minimum": 1},
        "status": {"type": "string", "enum": ORCHESTRATION_VERSION_STATUSES},
        "definition_hash": {"type": "string", "nullable": True},
        "definition": {"$ref": "#/components/schemas/OrchestrationDefinition"},
        "comment": {"type": "string", "nullable": True},
        "created_by_id": {"type": "integer", "nullable": True},
        "created_by": {"$ref": "#/components/schemas/OrchestrationActor"},
        "updated_by_id": {"type": "integer", "nullable": True},
        "updated_by": {"$ref": "#/components/schemas/OrchestrationActor"},
        "published_by_id": {"type": "integer", "nullable": True},
        "published_by": {"$ref": "#/components/schemas/OrchestrationActor"},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
        "published_at": {"type": "string", "format": "date-time", "nullable": True},
    },
    "additionalProperties": False,
}

ORCHESTRATION_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "uid": {"type": "string", "format": "uuid"},
        "group_id": {"type": "integer"},
        "name": {"type": "string"},
        "description": {"type": "string", "nullable": True},
        "scope": {"type": "string", "enum": ORCHESTRATION_SCOPES},
        "service_id": {"type": "integer", "nullable": True},
        "enabled": {"type": "boolean"},
        "mode": {"type": "string", "enum": ORCHESTRATION_MODES},
        "compatibility_mode": {
            "type": "string",
            "enum": ORCHESTRATION_COMPATIBILITY_MODES,
        },
        "active_version_id": {"type": "integer", "nullable": True},
        "active_version": {"$ref": "#/components/schemas/OrchestrationVersion"},
        "active_definition": {"$ref": "#/components/schemas/OrchestrationDefinition"},
        "draft": {"$ref": "#/components/schemas/OrchestrationVersion"},
        "created_by_id": {"type": "integer", "nullable": True},
        "created_by": {"$ref": "#/components/schemas/OrchestrationActor"},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
        "permissions": {"$ref": "#/components/schemas/OrchestrationPermissions"},
    },
    "additionalProperties": False,
}

CREATE_SCHEMA = {
    "type": "object",
    "required": ["group_id", "name"],
    "properties": {
        "group_id": {"type": "integer", "minimum": 1},
        "name": {"type": "string", "minLength": 1, "maxLength": 255},
        "description": {"type": "string", "nullable": True, "maxLength": 8192},
        "scope": {"type": "string", "enum": ORCHESTRATION_SCOPES, "default": "global"},
        "service_id": {"type": "integer", "nullable": True, "minimum": 1},
        "compatibility_mode": {
            "type": "string",
            "enum": ORCHESTRATION_COMPATIBILITY_MODES,
            "default": "legacy",
        },
    },
    "additionalProperties": False,
}

UPDATE_SCHEMA = {
    "type": "object",
    "minProperties": 1,
    "properties": {
        "name": {"type": "string", "minLength": 1, "maxLength": 255},
        "description": {"type": "string", "nullable": True, "maxLength": 8192},
        "scope": {"type": "string", "enum": ORCHESTRATION_SCOPES},
        "service_id": {"type": "integer", "nullable": True, "minimum": 1},
    },
    "additionalProperties": False,
}

DRAFT_SCHEMA = {
    "type": "object",
    "required": ["rules"],
    "properties": {
        "rules": {
            "type": "array",
            "maxItems": 512,
            "items": {"$ref": "#/components/schemas/OrchestrationRule"},
        },
        "comment": {"type": "string", "nullable": True, "maxLength": 8192},
    },
    "additionalProperties": False,
}

PUBLISH_SCHEMA = {
    "type": "object",
    "properties": {
        "comment": {"type": "string", "nullable": True, "maxLength": 8192},
        "confirm_catch_all_drop": {"type": "boolean", "default": False},
    },
    "additionalProperties": False,
}

ROLLBACK_SCHEMA = {
    "type": "object",
    "required": ["version_id"],
    "properties": {
        "version_id": {"type": "integer", "minimum": 1},
        "comment": {"type": "string", "nullable": True, "maxLength": 8192},
        "confirm_catch_all_drop": {"type": "boolean", "default": False},
    },
    "additionalProperties": False,
}

RUNTIME_SCHEMA = {
    "type": "object",
    "required": ["mode"],
    "properties": {
        "mode": {"type": "string", "enum": ORCHESTRATION_MODES},
        "compatibility_mode": {
            "type": "string",
            "enum": ORCHESTRATION_COMPATIBILITY_MODES,
            "default": "legacy",
        },
    },
    "additionalProperties": False,
}

SIMULATION_SCHEMA = {
    "type": "object",
    "properties": {
        "source": {"type": "string", "enum": list(SUPPORTED_NORMALIZER_SOURCES)},
        "payload": {"nullable": True},
        "headers": {"type": "object", "additionalProperties": True, "default": {}},
        "normalized_event": {"type": "object", "additionalProperties": True, "nullable": True},
        "event_index": {"type": "integer", "minimum": 0, "maximum": 1000, "default": 0},
        "version_id": {"type": "integer", "minimum": 1, "nullable": True},
        "compare_with_active": {"type": "boolean", "default": False},
    },
    "additionalProperties": False,
    "description": (
        "Provide exactly one of normalized_event or payload. source is required "
        "when payload is used."
    ),
}

REPLAY_SCHEMA = {
    "type": "object",
    "properties": {
        "alert_ids": {"type": "array", "items": {"type": "integer", "minimum": 1}},
        "execution_ids": {"type": "array", "items": {"type": "integer", "minimum": 1}},
        "version_id": {"type": "integer", "minimum": 1, "nullable": True},
        "compare_with_active": {"type": "boolean", "default": False},
    },
    "additionalProperties": False,
    "description": "At least one alert id or execution id is required.",
}

WEBHOOK_ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "group_id": {"type": "integer"},
        "name": {"type": "string"},
        "description": {"type": "string", "nullable": True},
        "url": {"type": "string", "format": "uri"},
        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
        "body_template": {"type": "string", "nullable": True},
        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 60},
        "retry_count": {"type": "integer", "minimum": 0, "maximum": 10},
        "private_network_policy": {"type": "string", "enum": ["deny", "allowlist"]},
        "enabled": {"type": "boolean"},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
    },
    "additionalProperties": False,
    "description": "Secret headers are intentionally never included in responses.",
}

WEBHOOK_ACTION_WRITE_PROPERTIES = {
    "name": {"type": "string", "minLength": 1, "maxLength": 255},
    "description": {"type": "string", "nullable": True, "maxLength": 8192},
    "url": {"type": "string", "minLength": 1, "maxLength": 4096, "format": "uri"},
    "method": {
        "type": "string",
        "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
        "default": "POST",
    },
    "headers": {
        "type": "object",
        "writeOnly": True,
        "additionalProperties": True,
        "description": "Encrypted secret headers. Never returned by the API.",
    },
    "body_template": {"type": "string", "nullable": True, "maxLength": 65536},
    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 60, "default": 10},
    "retry_count": {"type": "integer", "minimum": 0, "maximum": 10, "default": 2},
    "private_network_policy": {
        "type": "string",
        "enum": ["deny", "allowlist"],
        "default": "deny",
    },
    "enabled": {"type": "boolean", "default": True},
}

WEBHOOK_ACTION_CREATE_SCHEMA = {
    "type": "object",
    "required": ["group_id", "name", "url"],
    "properties": {
        "group_id": {"type": "integer", "minimum": 1},
        **WEBHOOK_ACTION_WRITE_PROPERTIES,
    },
    "additionalProperties": False,
}

WEBHOOK_ACTION_UPDATE_SCHEMA = {
    "type": "object",
    "minProperties": 1,
    "properties": WEBHOOK_ACTION_WRITE_PROPERTIES,
    "additionalProperties": False,
}

GENERIC_OBJECT_SCHEMA = {"type": "object", "additionalProperties": True}


def components():
    """Return reusable orchestration OpenAPI schemas."""
    return {
        "OrchestrationActor": ACTOR_SCHEMA,
        "OrchestrationPermissions": PERMISSION_MAP_SCHEMA,
        "OrchestrationCondition": CONDITION_SCHEMA,
        "OrchestrationConditionGroup": CONDITION_GROUP_SCHEMA,
        "OrchestrationConditionTree": {
            "oneOf": [
                {"$ref": "#/components/schemas/OrchestrationCondition"},
                {"$ref": "#/components/schemas/OrchestrationConditionGroup"},
            ]
        },
        "OrchestrationAction": ACTION_SCHEMA,
        "OrchestrationRule": RULE_SCHEMA,
        "OrchestrationDefinition": DEFINITION_SCHEMA,
        "OrchestrationVersion": VERSION_SCHEMA,
        "EventOrchestration": ORCHESTRATION_SCHEMA,
        "OrchestrationWebhookAction": WEBHOOK_ACTION_SCHEMA,
    }


def tags():
    return [
        {
            "name": "event-orchestrations",
            "description": (
                "Versioned global and service event-processing rules. Group viewers can read; "
                "group editors can create, edit, simulate, replay and publish; destructive and "
                "webhook-action administration remains restricted to global administrators."
            ),
        },
        {
            "name": "orchestration-webhook-actions",
            "description": (
                "Reusable encrypted outbound webhook actions. Secret headers are write-only and "
                "execution is asynchronous with SSRF protections."
            ),
        },
    ]


def _secured(operation):
    operation["security"] = [{"bearerAuth": []}]
    return operation


def _standard_errors(*statuses):
    descriptions = {
        400: "Validation error.",
        401: "Valid JWT or API token is required.",
        403: "The principal lacks the required group orchestration permission.",
        404: "The orchestration, version or related resource was not found.",
        409: "The requested state transition conflicts with the current version state.",
    }
    return {str(status): response(descriptions[status], ERROR_SCHEMA) for status in statuses}


def _orchestration_id_params():
    return [path_param("orchestration_id", "Event orchestration id.")]


def paths():
    """Return all Event Orchestration OpenAPI path definitions."""
    orchestration_ref = {"$ref": "#/components/schemas/EventOrchestration"}
    version_ref = {"$ref": "#/components/schemas/OrchestrationVersion"}
    webhook_ref = {"$ref": "#/components/schemas/OrchestrationWebhookAction"}

    return {
        "/api/event-orchestrations": {
            "get": _secured({
                "tags": ["event-orchestrations"],
                "summary": "List accessible event orchestrations",
                "operationId": "listEventOrchestrations",
                "parameters": [query_param("group_id", "Optional accessible group id.", {"type": "integer", "minimum": 1})],
                "responses": {
                    "200": response("Accessible orchestrations.", {
                        "type": "object",
                        "properties": {
                            "items": {"type": "array", "items": orchestration_ref},
                            "count": {"type": "integer"},
                        },
                    }),
                    **_standard_errors(401, 403),
                },
            }),
            "post": _secured({
                "tags": ["event-orchestrations"],
                "summary": "Create an event orchestration",
                "description": "Creates a disabled orchestration and its initial editable draft.",
                "operationId": "createEventOrchestration",
                "requestBody": json_body("Orchestration metadata and scope.", CREATE_SCHEMA),
                "responses": {
                    "201": response("Orchestration created.", orchestration_ref),
                    **_standard_errors(400, 401, 403, 404, 409),
                },
            }),
        },
        "/api/event-orchestrations/catalog": {
            "get": _secured({
                "tags": ["event-orchestrations"],
                "summary": "Get orchestration editor catalog",
                "description": "Returns accessible teams, services, routes, policies, webhook actions, normalizer sources and effective permissions for one group.",
                "operationId": "getEventOrchestrationCatalog",
                "parameters": [query_param("group_id", "Group id.", {"type": "integer", "minimum": 1}, required=True)],
                "responses": {
                    "200": response("Editor catalog.", GENERIC_OBJECT_SCHEMA),
                    **_standard_errors(400, 401, 403, 404),
                },
            }),
        },
        "/api/event-orchestrations/{orchestration_id}": {
            "get": _secured({
                "tags": ["event-orchestrations"],
                "summary": "Get an event orchestration",
                "operationId": "getEventOrchestration",
                "parameters": _orchestration_id_params(),
                "responses": {"200": response("Orchestration with active and draft definitions.", orchestration_ref), **_standard_errors(401, 403, 404)},
            }),
            "patch": _secured({
                "tags": ["event-orchestrations"],
                "summary": "Update orchestration metadata",
                "operationId": "updateEventOrchestration",
                "parameters": _orchestration_id_params(),
                "requestBody": json_body("Metadata and optional scope change.", UPDATE_SCHEMA),
                "responses": {"200": response("Updated orchestration.", orchestration_ref), **_standard_errors(400, 401, 403, 404, 409)},
            }),
            "delete": _secured({
                "tags": ["event-orchestrations"],
                "summary": "Archive an event orchestration",
                "description": "Global administrator permission is required. The orchestration is disabled and soft-deleted.",
                "operationId": "deleteEventOrchestration",
                "parameters": _orchestration_id_params(),
                "responses": {"200": response("Orchestration archived.", {"type": "object", "properties": {"deleted": {"type": "boolean"}, "id": {"type": "integer"}}}), **_standard_errors(401, 403, 404, 409)},
            }),
        },
        "/api/event-orchestrations/{orchestration_id}/draft": {
            "post": _secured({
                "tags": ["event-orchestrations"],
                "summary": "Get or create an editable draft",
                "operationId": "createEventOrchestrationDraft",
                "parameters": _orchestration_id_params(),
                "responses": {"200": response("Current editable draft.", version_ref), **_standard_errors(401, 403, 404, 409)},
            }),
            "put": _secured({
                "tags": ["event-orchestrations"],
                "summary": "Replace draft rules",
                "description": "Saves the complete ordered rule tree and records the authenticated user as the last editor.",
                "operationId": "saveEventOrchestrationDraft",
                "parameters": _orchestration_id_params(),
                "requestBody": json_body("Complete draft rule set.", DRAFT_SCHEMA),
                "responses": {"200": response("Saved draft with definition and author metadata.", version_ref), **_standard_errors(400, 401, 403, 404, 409)},
            }),
        },
        "/api/event-orchestrations/{orchestration_id}/validate": {
            "post": _secured({
                "tags": ["event-orchestrations"],
                "summary": "Validate the current draft",
                "operationId": "validateEventOrchestrationDraft",
                "parameters": _orchestration_id_params(),
                "responses": {"200": response("Validation result.", GENERIC_OBJECT_SCHEMA), **_standard_errors(400, 401, 403, 404, 409)},
            }),
        },
        "/api/event-orchestrations/{orchestration_id}/publish": {
            "post": _secured({
                "tags": ["event-orchestrations"],
                "summary": "Publish the current draft",
                "description": "Group editors and global administrators can publish. Published definitions are immutable and author metadata is retained.",
                "operationId": "publishEventOrchestrationDraft",
                "parameters": _orchestration_id_params(),
                "requestBody": json_body("Optional publication comment and destructive catch-all confirmation.", PUBLISH_SCHEMA),
                "responses": {"200": response("Published immutable version.", version_ref), **_standard_errors(400, 401, 403, 404, 409)},
            }),
        },
        "/api/event-orchestrations/{orchestration_id}/rollback": {
            "post": _secured({
                "tags": ["event-orchestrations"],
                "summary": "Rollback by publishing a historical definition",
                "description": "Creates a new immutable version; historical published versions are never modified.",
                "operationId": "rollbackEventOrchestration",
                "parameters": _orchestration_id_params(),
                "requestBody": json_body("Historical version to copy and publish.", ROLLBACK_SCHEMA),
                "responses": {"200": response("New published rollback version.", version_ref), **_standard_errors(400, 401, 403, 404, 409)},
            }),
        },
        "/api/event-orchestrations/{orchestration_id}/runtime": {
            "patch": _secured({
                "tags": ["event-orchestrations"],
                "summary": "Update orchestration runtime mode",
                "description": "A published version is required before active or shadow mode can be enabled.",
                "operationId": "updateEventOrchestrationRuntime",
                "parameters": _orchestration_id_params(),
                "requestBody": json_body("Runtime and compatibility modes.", RUNTIME_SCHEMA),
                "responses": {"200": response("Updated orchestration runtime.", orchestration_ref), **_standard_errors(400, 401, 403, 404, 409)},
            }),
        },
        "/api/event-orchestrations/{orchestration_id}/versions": {
            "get": _secured({
                "tags": ["event-orchestrations"],
                "summary": "List orchestration versions",
                "operationId": "listEventOrchestrationVersions",
                "parameters": _orchestration_id_params(),
                "responses": {"200": response("Version history.", {"type": "object", "properties": {"items": {"type": "array", "items": version_ref}}}), **_standard_errors(401, 403, 404)},
            }),
        },
        "/api/event-orchestrations/{orchestration_id}/versions/{version_id}": {
            "get": _secured({
                "tags": ["event-orchestrations"],
                "summary": "Get one orchestration version",
                "operationId": "getEventOrchestrationVersion",
                "parameters": _orchestration_id_params() + [path_param("version_id", "Version row id.")],
                "responses": {"200": response("Version including immutable definition.", version_ref), **_standard_errors(401, 403, 404)},
            }),
        },
        "/api/event-orchestrations/{orchestration_id}/simulate": {
            "post": _secured({
                "tags": ["event-orchestrations"],
                "summary": "Simulate an event against a draft or version",
                "description": "Does not create alerts, mutate production state or execute webhooks.",
                "operationId": "simulateEventOrchestration",
                "parameters": _orchestration_id_params(),
                "requestBody": json_body("Normalized event or raw integration payload.", SIMULATION_SCHEMA),
                "responses": {"200": response("Deterministic simulation and explain trace.", GENERIC_OBJECT_SCHEMA), **_standard_errors(400, 401, 403, 404, 409)},
            }),
        },
        "/api/event-orchestrations/{orchestration_id}/replay": {
            "post": _secured({
                "tags": ["event-orchestrations"],
                "summary": "Replay stored events safely",
                "description": "Re-evaluates stored alerts or executions without applying production side effects.",
                "operationId": "replayEventOrchestration",
                "parameters": _orchestration_id_params(),
                "requestBody": json_body("Stored alert and/or execution ids.", REPLAY_SCHEMA),
                "responses": {"200": response("Replay comparison results.", GENERIC_OBJECT_SCHEMA), **_standard_errors(400, 401, 403, 404, 409)},
            }),
        },
        "/api/event-orchestrations/{orchestration_id}/executions": {
            "get": _secured({
                "tags": ["event-orchestrations"],
                "summary": "List orchestration executions",
                "operationId": "listEventOrchestrationExecutions",
                "parameters": _orchestration_id_params() + [
                    query_param("limit", "Maximum execution rows.", {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}),
                    query_param("include_trace", "Set to 1 to include full explain traces.", {"type": "string", "enum": ["1"]}),
                ],
                "responses": {"200": response("Execution history.", GENERIC_OBJECT_SCHEMA), **_standard_errors(401, 403, 404)},
            }),
        },
        "/api/event-orchestrations/{orchestration_id}/shadow-metrics": {
            "get": _secured({
                "tags": ["event-orchestrations"],
                "summary": "Get shadow comparison metrics",
                "operationId": "getEventOrchestrationShadowMetrics",
                "parameters": _orchestration_id_params() + [query_param("limit", "Optional number of recent executions to aggregate.", {"type": "integer", "minimum": 1})],
                "responses": {"200": response("Shadow decision counters and differences.", GENERIC_OBJECT_SCHEMA), **_standard_errors(401, 403, 404)},
            }),
        },
        "/api/orchestration-webhook-actions": {
            "get": _secured({
                "tags": ["orchestration-webhook-actions"],
                "summary": "List webhook actions for a group",
                "operationId": "listOrchestrationWebhookActions",
                "parameters": [query_param("group_id", "Group id.", {"type": "integer", "minimum": 1}, required=True)],
                "responses": {"200": response("Webhook actions without secret headers.", {"type": "object", "properties": {"items": {"type": "array", "items": webhook_ref}}}), **_standard_errors(400, 401, 403)},
            }),
            "post": _secured({
                "tags": ["orchestration-webhook-actions"],
                "summary": "Create a reusable webhook action",
                "description": "Global administrator permission is required. Secret headers are encrypted and never returned.",
                "operationId": "createOrchestrationWebhookAction",
                "requestBody": json_body("Webhook configuration and write-only secret headers.", WEBHOOK_ACTION_CREATE_SCHEMA),
                "responses": {"201": response("Webhook action created.", webhook_ref), **_standard_errors(400, 401, 403, 409)},
            }),
        },
        "/api/orchestration-webhook-actions/{action_id}": {
            "patch": _secured({
                "tags": ["orchestration-webhook-actions"],
                "summary": "Update a webhook action",
                "operationId": "updateOrchestrationWebhookAction",
                "parameters": [path_param("action_id", "Webhook action id.")],
                "requestBody": json_body("Fields to update. Supplying headers replaces encrypted headers.", WEBHOOK_ACTION_UPDATE_SCHEMA),
                "responses": {"200": response("Updated webhook action without secrets.", webhook_ref), **_standard_errors(400, 401, 403, 404, 409)},
            }),
            "delete": _secured({
                "tags": ["orchestration-webhook-actions"],
                "summary": "Delete a webhook action",
                "operationId": "deleteOrchestrationWebhookAction",
                "parameters": [path_param("action_id", "Webhook action id.")],
                "responses": {"200": response("Webhook action soft-deleted.", {"type": "object", "properties": {"deleted": {"type": "boolean"}, "id": {"type": "integer"}}}), **_standard_errors(401, 403, 404)},
            }),
        },
        "/api/orchestration-webhook-actions/{action_id}/executions": {
            "get": _secured({
                "tags": ["orchestration-webhook-actions"],
                "summary": "List webhook action executions",
                "operationId": "listOrchestrationWebhookActionExecutions",
                "parameters": [
                    path_param("action_id", "Webhook action id."),
                    query_param("limit", "Maximum execution rows.", {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}),
                ],
                "responses": {"200": response("Redacted asynchronous execution results.", GENERIC_OBJECT_SCHEMA), **_standard_errors(401, 403, 404)},
            }),
        },
    }
