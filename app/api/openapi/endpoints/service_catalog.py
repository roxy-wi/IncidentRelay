"""OpenAPI paths for Service Standards, Readiness and Service Timeline.

This module intentionally keeps these newer service-catalog endpoints outside
`services.py` to avoid growing the already large service endpoint definition.
All paths still use the existing `services` Swagger tag.
"""

from app.api.schemas.limits import (
    DESCRIPTION_MAX_LENGTH,
    NAME_MAX_LENGTH,
    NAME_MIN_LENGTH,
    SLUG_MAX_LENGTH,
    SLUG_MIN_LENGTH,
)


SERVICE_KINDS = ["technical", "business"]
SERVICE_LIFECYCLES = [
    "experimental",
    "development",
    "production",
    "deprecated",
    "retired",
]
SERVICE_TYPES = [
    "api",
    "web",
    "database",
    "queue",
    "cache",
    "worker",
    "cron",
    "network",
    "storage",
    "infrastructure",
    "external",
    "other",
]
SERVICE_ENVIRONMENTS = [
    "production",
    "staging",
    "development",
    "testing",
    "shared",
]
SERVICE_CRITICALITIES = ["low", "medium", "high", "critical"]
SERVICE_TIERS = ["tier_1", "tier_2", "tier_3", "tier_4"]

STANDARD_CHECK_TYPES = [
    "field_present",
    "field_equals",
    "owner_exists",
    "active_rotation_exists",
    "escalation_policy_exists",
    "notification_policy_exists",
    "service_channel_exists",
    "route_exists",
    "match_rule_exists",
    "runbook_exists",
    "link_type_exists",
    "dependency_exists",
    "dependency_cycle_absent",
    "metadata_value",
]
STANDARD_CHECK_SEVERITIES = ["info", "warning", "critical"]
READINESS_STATUSES = ["ready", "warning", "not_ready", "not_applicable", "unknown"]
CHECK_RESULT_STATUSES = ["passed", "failed", "skipped", "not_applicable"]
TIMELINE_CATEGORIES = [
    "configuration",
    "routing",
    "readiness",
    "status",
    "alerting",
    "sli_slo",
]


def path_param(name, description):
    return {
        "name": name,
        "in": "path",
        "required": True,
        "description": description,
        "schema": {"type": "integer", "minimum": 1},
    }


def query_param(name, description, schema=None, required=False):
    return {
        "name": name,
        "in": "query",
        "required": required,
        "description": description,
        "schema": schema or {"type": "string"},
    }


def json_body(description, schema, required=True):
    return {
        "required": required,
        "description": description,
        "content": {"application/json": {"schema": schema}},
    }


def response(description, schema=None):
    item = {"description": description}

    if schema:
        item["content"] = {"application/json": {"schema": schema}}

    return item


ERROR_SCHEMA = {
    "type": "object",
    "properties": {
        "error": {"type": "string", "example": "validation_error"},
        "message": {"type": "string", "nullable": True},
        "details": {"type": "array", "items": {"type": "object"}},
    },
}

DELETE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "deleted": {"type": "boolean", "example": True},
        "id": {"type": "integer", "example": 1},
    },
}

USER_SHORT_SCHEMA = {
    "type": "object",
    "nullable": True,
    "properties": {
        "id": {"type": "integer"},
        "username": {"type": "string", "nullable": True},
        "display_name": {"type": "string", "nullable": True},
        "email": {"type": "string", "nullable": True},
    },
}

PERMISSIONS_SCHEMA = {
    "type": "object",
    "additionalProperties": True,
    "description": "RBAC flags attached by serializers, for example can_read/can_write.",
}

SERVICE_STANDARD_APPLIES_TO_SCHEMA = {
    "type": "object",
    "description": (
        "Selector deciding which services the standard applies to. Empty object "
        "means all services in the group."
    ),
    "additionalProperties": True,
    "properties": {
        "kinds": {"type": "array", "items": {"type": "string", "enum": SERVICE_KINDS}},
        "lifecycles": {"type": "array", "items": {"type": "string", "enum": SERVICE_LIFECYCLES}},
        "tiers": {"type": "array", "items": {"type": "string", "enum": SERVICE_TIERS}},
        "criticalities": {"type": "array", "items": {"type": "string", "enum": SERVICE_CRITICALITIES}},
        "environments": {"type": "array", "items": {"type": "string", "enum": SERVICE_ENVIRONMENTS}},
        "service_types": {"type": "array", "items": {"type": "string", "enum": SERVICE_TYPES}},
    },
    "example": {
        "kinds": ["technical"],
        "lifecycles": ["production"],
        "tiers": ["tier_1", "tier_2"],
        "criticalities": ["critical", "high"],
    },
}

SERVICE_STANDARD_CREATE_SCHEMA = {
    "type": "object",
    "required": ["group_id", "slug", "name"],
    "additionalProperties": False,
    "properties": {
        "group_id": {"type": "integer", "minimum": 1},
        "slug": {
            "type": "string",
            "minLength": SLUG_MIN_LENGTH,
            "maxLength": SLUG_MAX_LENGTH,
            "pattern": "^[a-z0-9][a-z0-9-]*$",
            "example": "basic-operational-readiness",
        },
        "name": {
            "type": "string",
            "minLength": NAME_MIN_LENGTH,
            "maxLength": NAME_MAX_LENGTH,
            "example": "Basic operational readiness",
        },
        "description": {
            "type": "string",
            "nullable": True,
            "maxLength": DESCRIPTION_MAX_LENGTH,
        },
        "applies_to": SERVICE_STANDARD_APPLIES_TO_SCHEMA,
        "enabled": {"type": "boolean", "default": True},
    },
}

SERVICE_STANDARD_UPDATE_SCHEMA = {
    **SERVICE_STANDARD_CREATE_SCHEMA,
    "required": ["slug", "name"],
    "properties": {
        key: value
        for key, value in SERVICE_STANDARD_CREATE_SCHEMA["properties"].items()
        if key != "group_id"
    },
}

SERVICE_STANDARD_CHECK_INPUT_SCHEMA = {
    "type": "object",
    "required": ["slug", "name", "check_type"],
    "additionalProperties": False,
    "properties": {
        "slug": {
            "type": "string",
            "minLength": SLUG_MIN_LENGTH,
            "maxLength": SLUG_MAX_LENGTH,
            "pattern": "^[a-z0-9][a-z0-9-]*$",
            "example": "runbook-exists",
        },
        "name": {
            "type": "string",
            "minLength": NAME_MIN_LENGTH,
            "maxLength": NAME_MAX_LENGTH,
            "example": "Runbook exists",
        },
        "description": {
            "type": "string",
            "nullable": True,
            "maxLength": DESCRIPTION_MAX_LENGTH,
        },
        "check_type": {"type": "string", "enum": STANDARD_CHECK_TYPES},
        "configuration": {
            "type": "object",
            "additionalProperties": True,
            "default": {},
            "example": {"minimum": 1},
        },
        "weight": {"type": "integer", "minimum": 1, "maximum": 100, "default": 1},
        "severity": {"type": "string", "enum": STANDARD_CHECK_SEVERITIES, "default": "warning"},
        "required": {"type": "boolean", "default": True},
        "enabled": {"type": "boolean", "default": True},
        "position": {"type": "integer", "minimum": 0, "default": 0},
    },
}

SERVICE_STANDARD_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "uid": {"type": "string", "format": "uuid", "readOnly": True},
        "standard_id": {"type": "integer", "readOnly": True},
        **SERVICE_STANDARD_CHECK_INPUT_SCHEMA["properties"],
        "created_at": {"type": "string", "format": "date-time", "nullable": True},
        "updated_at": {"type": "string", "format": "date-time", "nullable": True},
    },
}

SERVICE_STANDARD_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "uid": {"type": "string", "format": "uuid", "readOnly": True},
        "group_id": {"type": "integer"},
        "group_slug": {"type": "string", "nullable": True},
        "group_name": {"type": "string", "nullable": True},
        "slug": SERVICE_STANDARD_CREATE_SCHEMA["properties"]["slug"],
        "name": SERVICE_STANDARD_CREATE_SCHEMA["properties"]["name"],
        "description": SERVICE_STANDARD_CREATE_SCHEMA["properties"]["description"],
        "applies_to": SERVICE_STANDARD_APPLIES_TO_SCHEMA,
        "enabled": {"type": "boolean"},
        "created_by": USER_SHORT_SCHEMA,
        "created_at": {"type": "string", "format": "date-time", "nullable": True},
        "updated_at": {"type": "string", "format": "date-time", "nullable": True},
        "checks": {"type": "array", "items": SERVICE_STANDARD_CHECK_SCHEMA},
        "checks_count": {"type": "integer", "minimum": 0},
        "permissions": PERMISSIONS_SCHEMA,
    },
}

SERVICE_STANDARD_PRESET_APPLY_SCHEMA = {
    "type": "object",
    "required": ["group_id"],
    "additionalProperties": False,
    "properties": {
        "group_id": {"type": "integer", "minimum": 1},
    },
}

READINESS_STATE_SCHEMA = {
    "type": "object",
    "nullable": True,
    "properties": {
        "status": {"type": "string", "enum": READINESS_STATUSES},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "standards_count": {"type": "integer", "minimum": 0},
        "checks_count": {"type": "integer", "minimum": 0},
        "failed_count": {"type": "integer", "minimum": 0},
        "failed_required_count": {"type": "integer", "minimum": 0},
        "failed_critical_count": {"type": "integer", "minimum": 0},
        "batch_uid": {"type": "string", "format": "uuid", "nullable": True},
        "evaluated_at": {"type": "string", "format": "date-time", "nullable": True},
    },
}

READINESS_CHECK_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "check_id": {"type": "integer", "nullable": True},
        "check_uid": {"type": "string", "format": "uuid", "nullable": True},
        "check_slug": {"type": "string", "nullable": True},
        "check_name": {"type": "string", "nullable": True},
        "check_type": {"type": "string", "enum": STANDARD_CHECK_TYPES},
        "status": {"type": "string", "enum": CHECK_RESULT_STATUSES},
        "weight": {"type": "integer", "minimum": 0},
        "severity": {"type": "string", "enum": STANDARD_CHECK_SEVERITIES},
        "required": {"type": "boolean"},
        "message": {"type": "string", "nullable": True},
        "details": {"type": "object", "additionalProperties": True},
        "evaluated_at": {"type": "string", "format": "date-time", "nullable": True},
    },
}

READINESS_EVALUATION_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "uid": {"type": "string", "format": "uuid"},
        "batch_uid": {"type": "string", "format": "uuid"},
        "service_id": {"type": "integer"},
        "standard": {
            "type": "object",
            "nullable": True,
            "properties": {
                "id": {"type": "integer"},
                "uid": {"type": "string", "format": "uuid"},
                "slug": {"type": "string"},
                "name": {"type": "string"},
                "enabled": {"type": "boolean"},
            },
        },
        "status": {"type": "string", "enum": READINESS_STATUSES},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "passed_weight": {"type": "integer", "minimum": 0},
        "total_weight": {"type": "integer", "minimum": 0},
        "checks_count": {"type": "integer", "minimum": 0},
        "failed_count": {"type": "integer", "minimum": 0},
        "failed_required_count": {"type": "integer", "minimum": 0},
        "failed_critical_count": {"type": "integer", "minimum": 0},
        "trigger": {"type": "string", "nullable": True},
        "actor_user_id": {"type": "integer", "nullable": True},
        "evaluated_at": {"type": "string", "format": "date-time", "nullable": True},
        "results": {"type": "array", "items": READINESS_CHECK_RESULT_SCHEMA},
    },
}

SERVICE_READINESS_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "state": READINESS_STATE_SCHEMA,
        "evaluations": {"type": "array", "items": READINESS_EVALUATION_SCHEMA},
    },
}

TIMELINE_ACTOR_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "nullable": True, "example": "user"},
        "user_id": {"type": "integer", "nullable": True},
        "display_name": {"type": "string", "nullable": True},
        "email": {"type": "string", "nullable": True},
        "label": {"type": "string", "nullable": True},
    },
}

SERVICE_TIMELINE_EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "uid": {"type": "string", "format": "uuid"},
        "service_id": {"type": "integer"},
        "group_id": {"type": "integer", "nullable": True},
        "team_id": {"type": "integer", "nullable": True},
        "category": {"type": "string", "enum": TIMELINE_CATEGORIES},
        "event_type": {"type": "string", "example": "service_runbook.created"},
        "title": {"type": "string"},
        "summary": {"type": "string", "nullable": True},
        "source": {"type": "string", "example": "incidentrelay"},
        "source_ref": {"type": "string", "nullable": True},
        "dedup_key": {"type": "string", "nullable": True},
        "external_url": {"type": "string", "nullable": True},
        "actor": TIMELINE_ACTOR_SCHEMA,
        "severity": {"type": "string", "nullable": True},
        "status": {"type": "string", "nullable": True},
        "occurred_at": {"type": "string", "format": "date-time", "nullable": True},
        "recorded_at": {"type": "string", "format": "date-time", "nullable": True},
        "schema_version": {"type": "integer"},
        "payload": {"type": "object", "additionalProperties": True},
    },
}

TIMELINE_CURSOR_SCHEMA = {
    "type": "object",
    "nullable": True,
    "properties": {
        "before": {"type": "string", "format": "date-time"},
        "before_id": {"type": "integer"},
    },
}

SERVICE_TIMELINE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": SERVICE_TIMELINE_EVENT_SCHEMA},
        "next_cursor": TIMELINE_CURSOR_SCHEMA,
    },
}

STANDARD_QUERY_PARAMS = [
    query_param("group_id", "Filter standards by group id.", {"type": "integer", "minimum": 1}),
    query_param(
        "include_disabled",
        "Include disabled standards. Accepts 1 for true.",
        {"type": "string", "enum": ["0", "1"], "default": "0"},
    ),
]

STANDARD_CHECK_QUERY_PARAMS = [
    query_param(
        "include_disabled",
        "Include disabled checks. Accepts 1 for true.",
        {"type": "string", "enum": ["0", "1"], "default": "0"},
    ),
]

TIMELINE_QUERY_PARAMS = [
    query_param("limit", "Maximum returned events.", {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}),
    query_param("category", "Filter by event category.", {"type": "string"}),
    query_param("event_type", "Filter by exact event type.", {"type": "string", "example": "readiness.score_changed"}),
    query_param("before", "Cursor timestamp from next_cursor.before.", {"type": "string", "format": "date-time"}),
    query_param("before_id", "Cursor id from next_cursor.before_id.", {"type": "integer", "minimum": 1}),
]


# ---------------------------------------------------------------------------
# SLI / SLO schemas
# ---------------------------------------------------------------------------

SERVICE_SLI_TYPES = [
    "alert_ack_latency",
    "alert_resolve_latency",
    "incident_availability",
    "incident_count",
]

SERVICE_SLI_SOURCES = [
    "incidentrelay_alert_groups",
    "incidentrelay_service_status",
]

SERVICE_SLO_COMPARISONS = [
    "percent_good_gte",
    "value_gte",
    "value_lte",
]

SERVICE_SLO_STATUSES = [
    "met",
    "at_risk",
    "breached",
    "no_data",
]

SERVICE_SLI_INPUT_SCHEMA = {
    "type": "object",
    "required": ["slug", "name", "sli_type"],
    "additionalProperties": False,
    "properties": {
        "slug": {
            "type": "string",
            "minLength": SLUG_MIN_LENGTH,
            "maxLength": SLUG_MAX_LENGTH,
            "pattern": "^[a-z0-9][a-z0-9-]*$",
            "example": "critical-ack-latency",
        },
        "name": {
            "type": "string",
            "minLength": NAME_MIN_LENGTH,
            "maxLength": NAME_MAX_LENGTH,
            "example": "Critical alert acknowledgement latency",
        },
        "description": {
            "type": "string",
            "nullable": True,
            "maxLength": DESCRIPTION_MAX_LENGTH,
        },
        "sli_type": {
            "type": "string",
            "enum": SERVICE_SLI_TYPES,
            "description": "What is measured for this service.",
            "example": "alert_ack_latency",
        },
        "source": {
            "type": "string",
            "enum": SERVICE_SLI_SOURCES,
            "default": "incidentrelay_alert_groups",
            "description": "Data source used by the SLI evaluator.",
        },
        "configuration": {
            "type": "object",
            "additionalProperties": True,
            "default": {},
            "description": "Reserved for source-specific filters and future external providers.",
        },
        "severity": {
            "type": "string",
            "nullable": True,
            "enum": ["critical", "high", "warning", "info"],
            "description": "Optional alert severity filter for IncidentRelay alert-group based SLIs.",
            "example": "critical",
        },
        "priority": {
            "type": "string",
            "nullable": True,
            "description": "Optional priority filter placeholder for future priority-aware SLIs.",
            "example": "p1",
        },
        "enabled": {"type": "boolean", "default": True},
    },
}

SERVICE_SLI_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "service_id": {"type": "integer"},
        "service_name": {"type": "string", "nullable": True},
        "service_slug": {"type": "string", "nullable": True},
        "team_id": {"type": "integer", "nullable": True},
        "team_name": {"type": "string", "nullable": True},
        "team_slug": {"type": "string", "nullable": True},
        **SERVICE_SLI_INPUT_SCHEMA["properties"],
        "created_at": {"type": "string", "format": "date-time", "nullable": True},
        "updated_at": {"type": "string", "format": "date-time", "nullable": True},
        "permissions": PERMISSIONS_SCHEMA,
    },
}

SERVICE_SLO_INPUT_SCHEMA = {
    "type": "object",
    "required": ["sli_id", "name", "comparison"],
    "additionalProperties": False,
    "properties": {
        "sli_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Service SLI that this SLO targets. It must belong to the same service.",
        },
        "name": {
            "type": "string",
            "minLength": NAME_MIN_LENGTH,
            "maxLength": NAME_MAX_LENGTH,
            "example": "95% critical alerts acknowledged within 15 minutes",
        },
        "description": {
            "type": "string",
            "nullable": True,
            "maxLength": DESCRIPTION_MAX_LENGTH,
        },
        "comparison": {
            "type": "string",
            "enum": SERVICE_SLO_COMPARISONS,
            "default": "percent_good_gte",
            "description": (
                "percent_good_gte for latency/availability, value_lte for incident count, "
                "value_gte reserved for future gauges."
            ),
        },
        "target_percent_basis_points": {
            "type": "integer",
            "nullable": True,
            "minimum": 0,
            "maximum": 10000,
            "description": "Target percent in basis points: 9500 = 95%, 9990 = 99.9%.",
            "example": 9500,
        },
        "threshold_seconds": {
            "type": "integer",
            "nullable": True,
            "minimum": 1,
            "description": "Latency threshold in seconds for alert_ack_latency and alert_resolve_latency.",
            "example": 900,
        },
        "threshold_count": {
            "type": "integer",
            "nullable": True,
            "minimum": 0,
            "description": "Maximum allowed incident count for incident_count SLOs.",
            "example": 3,
        },
        "window_days": {
            "type": "integer",
            "minimum": 1,
            "maximum": 365,
            "default": 30,
            "description": "Rolling evaluation window in days.",
        },
        "exclude_maintenance": {
            "type": "boolean",
            "default": True,
            "description": "Exclude maintenance windows from incident availability downtime accounting.",
        },
        "include_open_alerts": {
            "type": "boolean",
            "default": True,
            "description": "Treat open alerts within threshold as pending for latency SLIs.",
        },
        "enabled": {"type": "boolean", "default": True},
    },
    "examples": {
        "ack_latency": {
            "summary": "95% critical alerts acknowledged within 15 minutes",
            "value": {
                "sli_id": 10,
                "name": "95% critical alerts acknowledged within 15 minutes",
                "comparison": "percent_good_gte",
                "target_percent_basis_points": 9500,
                "threshold_seconds": 900,
                "window_days": 30,
            },
        },
        "incident_count": {
            "summary": "No more than 3 critical incidents in 30 days",
            "value": {
                "sli_id": 11,
                "name": "No more than 3 critical incidents in 30 days",
                "comparison": "value_lte",
                "threshold_count": 3,
                "window_days": 30,
            },
        },
    },
}

SERVICE_SLO_EVALUATION_SCHEMA = {
    "type": "object",
    "properties": {
        "slo_id": {"type": "integer"},
        "sli_id": {"type": "integer"},
        "sli_type": {"type": "string", "enum": SERVICE_SLI_TYPES},
        "status": {"type": "string", "enum": SERVICE_SLO_STATUSES},
        "window": {
            "type": "object",
            "properties": {
                "days": {"type": "integer"},
                "since": {"type": "string", "format": "date-time"},
                "until": {"type": "string", "format": "date-time"},
            },
        },
        "comparison": {"type": "string", "enum": SERVICE_SLO_COMPARISONS},
        "target_percent_basis_points": {"type": "integer", "nullable": True},
        "target_percent": {"type": "number", "nullable": True},
        "threshold_seconds": {"type": "integer", "nullable": True},
        "threshold_count": {"type": "integer", "nullable": True},
        "value_basis_points": {"type": "integer", "nullable": True},
        "value_percent": {"type": "number", "nullable": True},
        "value_count": {"type": "integer", "nullable": True},
        "good_count": {"type": "integer"},
        "total_count": {"type": "integer"},
        "bad_count": {"type": "integer"},
        "pending_count": {"type": "integer"},
        "downtime_seconds": {"type": "integer", "nullable": True},
        "budget_seconds": {"type": "integer", "nullable": True},
        "budget_consumed_seconds": {"type": "integer", "nullable": True},
        "budget_remaining_seconds": {"type": "integer", "nullable": True},
        "message": {"type": "string", "nullable": True},
        "details": {"type": "object", "additionalProperties": True},
        "measurement_id": {"type": "integer", "nullable": True},
    },
}

SERVICE_SLO_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "service_id": {"type": "integer"},
        "service_name": {"type": "string", "nullable": True},
        "service_slug": {"type": "string", "nullable": True},
        "team_id": {"type": "integer", "nullable": True},
        "team_name": {"type": "string", "nullable": True},
        "team_slug": {"type": "string", "nullable": True},
        "sli_name": {"type": "string", "nullable": True},
        "sli_slug": {"type": "string", "nullable": True},
        "sli_type": {"type": "string", "nullable": True, "enum": SERVICE_SLI_TYPES},
        **SERVICE_SLO_INPUT_SCHEMA["properties"],
        "created_at": {"type": "string", "format": "date-time", "nullable": True},
        "updated_at": {"type": "string", "format": "date-time", "nullable": True},
        "evaluation": SERVICE_SLO_EVALUATION_SCHEMA,
        "permissions": PERMISSIONS_SCHEMA,
    },
}

SERVICE_SLI_SLO_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "slis": {"type": "array", "items": SERVICE_SLI_SCHEMA},
        "slos": {"type": "array", "items": SERVICE_SLO_SCHEMA},
    },
}

SERVICE_SLI_SLO_ANALYTICS_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "service_id": {"type": "integer"},
        "service_name": {"type": "string"},
        "service_slug": {"type": "string"},
        "service_status": {"type": "string"},
        "service_criticality": {"type": "string"},
        "team_id": {"type": "integer", "nullable": True},
        "team_name": {"type": "string", "nullable": True},
        "team_slug": {"type": "string", "nullable": True},
        "sli_id": {"type": "integer"},
        "sli_name": {"type": "string"},
        "sli_slug": {"type": "string"},
        "sli_type": {"type": "string", "enum": SERVICE_SLI_TYPES},
        "sli_source": {"type": "string", "enum": SERVICE_SLI_SOURCES},
        "sli_severity": {"type": "string", "nullable": True},
        "sli_priority": {"type": "string", "nullable": True},
        "slo_id": {"type": "integer"},
        "slo_name": {"type": "string"},
        "slo_description": {"type": "string", "nullable": True},
        "comparison": {"type": "string", "enum": SERVICE_SLO_COMPARISONS},
        "target_percent_basis_points": {"type": "integer", "nullable": True},
        "threshold_seconds": {"type": "integer", "nullable": True},
        "threshold_count": {"type": "integer", "nullable": True},
        "window_days": {"type": "integer"},
        "exclude_maintenance": {"type": "boolean"},
        "include_open_alerts": {"type": "boolean"},
        "enabled": {"type": "boolean"},
        "status": {"type": "string", "enum": SERVICE_SLO_STATUSES},
        "evaluation": SERVICE_SLO_EVALUATION_SCHEMA,
    },
}

SERVICE_SLI_SLO_ANALYTICS_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "window": {
            "type": "object",
            "properties": {"days": {"type": "integer"}},
        },
        "summary": {
            "type": "object",
            "properties": {
                "total": {"type": "integer"},
                "met": {"type": "integer"},
                "at_risk": {"type": "integer"},
                "breached": {"type": "integer"},
                "no_data": {"type": "integer"},
                "disabled": {"type": "integer"},
                "services": {"type": "integer"},
            },
        },
        "items": {"type": "array", "items": SERVICE_SLI_SLO_ANALYTICS_ITEM_SCHEMA},
    },
}

SLI_SLO_SCOPE_QUERY_PARAMS = [
    query_param("team_id", "Filter by team id.", {"type": "integer", "minimum": 1}),
    query_param("service_id", "Filter by service id.", {"type": "integer", "minimum": 1}),
    query_param(
        "include_disabled",
        "Include disabled SLI/SLO records. Accepts 1 for true.",
        {"type": "string", "enum": ["0", "1"], "default": "0"},
    ),
]


def tags():
    """Do not duplicate the existing services tag from services.py."""
    return []


def paths():
    return {
        "/api/services/standards": {
            "get": {
                "tags": ["services"],
                "summary": "List service standards",
                "description": "Returns service readiness standards visible to the current principal.",
                "operationId": "listServiceStandards",
                "parameters": STANDARD_QUERY_PARAMS,
                "responses": {
                    "200": response("List of service standards.", {"type": "array", "items": SERVICE_STANDARD_SCHEMA}),
                    "403": response("Access denied.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["services"],
                "summary": "Create service standard",
                "description": "Creates a readiness standard in a group. Group write access is required.",
                "operationId": "createServiceStandard",
                "requestBody": json_body("Service standard properties.", SERVICE_STANDARD_CREATE_SCHEMA),
                "responses": {
                    "201": response("Service standard created.", SERVICE_STANDARD_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/standards/presets/basic-operational": {
            "post": {
                "tags": ["services"],
                "summary": "Apply basic operational readiness preset",
                "description": (
                    "Creates or restores the built-in basic operational readiness standard "
                    "for a group and reconciles readiness for that group."
                ),
                "operationId": "applyBasicOperationalServiceStandard",
                "requestBody": json_body("Preset target group.", SERVICE_STANDARD_PRESET_APPLY_SCHEMA),
                "responses": {
                    "200": response("Preset standard created or restored.", SERVICE_STANDARD_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Group not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/standards/{standard_id}": {
            "get": {
                "tags": ["services"],
                "summary": "Get service standard",
                "description": "Returns one service standard with checks.",
                "operationId": "getServiceStandard",
                "parameters": [
                    path_param("standard_id", "Service standard id."),
                    *STANDARD_CHECK_QUERY_PARAMS,
                ],
                "responses": {
                    "200": response("Service standard.", SERVICE_STANDARD_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service standard not found.", ERROR_SCHEMA),
                },
            },
            "put": {
                "tags": ["services"],
                "summary": "Update service standard",
                "description": "Updates a readiness standard and reconciles group readiness.",
                "operationId": "updateServiceStandard",
                "parameters": [path_param("standard_id", "Service standard id.")],
                "requestBody": json_body("Updated service standard.", SERVICE_STANDARD_UPDATE_SCHEMA),
                "responses": {
                    "200": response("Service standard updated.", SERVICE_STANDARD_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service standard not found.", ERROR_SCHEMA),
                },
            },
            "delete": {
                "tags": ["services"],
                "summary": "Delete service standard",
                "description": "Soft-deletes a standard and reconciles group readiness.",
                "operationId": "deleteServiceStandard",
                "parameters": [path_param("standard_id", "Service standard id.")],
                "responses": {
                    "200": response("Service standard deleted.", DELETE_RESPONSE_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service standard not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/standards/{standard_id}/checks": {
            "get": {
                "tags": ["services"],
                "summary": "List service standard checks",
                "description": "Returns checks configured for one readiness standard.",
                "operationId": "listServiceStandardChecks",
                "parameters": [
                    path_param("standard_id", "Service standard id."),
                    *STANDARD_CHECK_QUERY_PARAMS,
                ],
                "responses": {
                    "200": response("List of standard checks.", {"type": "array", "items": SERVICE_STANDARD_CHECK_SCHEMA}),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service standard not found.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["services"],
                "summary": "Create service standard check",
                "description": "Creates a check under a readiness standard and reconciles group readiness.",
                "operationId": "createServiceStandardCheck",
                "parameters": [path_param("standard_id", "Service standard id.")],
                "requestBody": json_body("Standard check properties.", SERVICE_STANDARD_CHECK_INPUT_SCHEMA),
                "responses": {
                    "201": response("Standard check created.", SERVICE_STANDARD_CHECK_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service standard not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/standards/{standard_id}/checks/{check_id}": {
            "get": {
                "tags": ["services"],
                "summary": "Get service standard check",
                "description": "Returns one check from a readiness standard.",
                "operationId": "getServiceStandardCheck",
                "parameters": [
                    path_param("standard_id", "Service standard id."),
                    path_param("check_id", "Service standard check id."),
                ],
                "responses": {
                    "200": response("Standard check.", SERVICE_STANDARD_CHECK_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Standard check not found.", ERROR_SCHEMA),
                },
            },
            "put": {
                "tags": ["services"],
                "summary": "Update service standard check",
                "description": "Updates a readiness check and reconciles group readiness.",
                "operationId": "updateServiceStandardCheck",
                "parameters": [
                    path_param("standard_id", "Service standard id."),
                    path_param("check_id", "Service standard check id."),
                ],
                "requestBody": json_body("Updated standard check.", SERVICE_STANDARD_CHECK_INPUT_SCHEMA),
                "responses": {
                    "200": response("Standard check updated.", SERVICE_STANDARD_CHECK_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Standard check not found.", ERROR_SCHEMA),
                },
            },
            "delete": {
                "tags": ["services"],
                "summary": "Delete service standard check",
                "description": "Soft-deletes a readiness check and reconciles group readiness.",
                "operationId": "deleteServiceStandardCheck",
                "parameters": [
                    path_param("standard_id", "Service standard id."),
                    path_param("check_id", "Service standard check id."),
                ],
                "responses": {
                    "200": response("Standard check deleted.", DELETE_RESPONSE_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Standard check not found.", ERROR_SCHEMA),
                },
            },
        },

        "/api/services/{service_id}/slis": {
            "get": {
                "tags": ["services"],
                "summary": "List service SLIs",
                "description": "Returns Service Level Indicators configured for one service.",
                "operationId": "listServiceSlis",
                "parameters": [
                    path_param("service_id", "Service id."),
                    query_param("include_disabled", "Include disabled SLIs. Accepts 1 for true.", {"type": "string", "enum": ["0", "1"], "default": "1"}),
                ],
                "responses": {
                    "200": response("List of service SLIs.", {"type": "array", "items": SERVICE_SLI_SCHEMA}),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["services"],
                "summary": "Create service SLI",
                "description": "Creates a Service Level Indicator for a service.",
                "operationId": "createServiceSli",
                "parameters": [path_param("service_id", "Service id.")],
                "requestBody": json_body("Service SLI properties.", SERVICE_SLI_INPUT_SCHEMA),
                "responses": {
                    "201": response("Service SLI created.", SERVICE_SLI_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/slis/{sli_id}": {
            "put": {
                "tags": ["services"],
                "summary": "Update service SLI",
                "description": "Updates a Service Level Indicator.",
                "operationId": "updateServiceSli",
                "parameters": [path_param("sli_id", "Service SLI id.")],
                "requestBody": json_body("Updated Service SLI properties.", SERVICE_SLI_INPUT_SCHEMA),
                "responses": {
                    "200": response("Service SLI updated.", SERVICE_SLI_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service SLI not found.", ERROR_SCHEMA),
                },
            },
            "delete": {
                "tags": ["services"],
                "summary": "Delete service SLI",
                "description": "Soft-deletes a Service Level Indicator and all active SLOs attached to it are ignored by default list calls.",
                "operationId": "deleteServiceSli",
                "parameters": [path_param("sli_id", "Service SLI id.")],
                "responses": {
                    "200": response("Service SLI deleted.", SERVICE_SLI_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service SLI not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/{service_id}/slos": {
            "get": {
                "tags": ["services"],
                "summary": "List service SLOs",
                "description": "Returns Service Level Objectives for one service. Each SLO includes its current evaluation.",
                "operationId": "listServiceSlos",
                "parameters": [
                    path_param("service_id", "Service id."),
                    query_param("include_disabled", "Include disabled SLOs. Accepts 1 for true.", {"type": "string", "enum": ["0", "1"], "default": "1"}),
                    query_param("days", "Compatibility parameter. Each SLO uses its own window_days value.", {"type": "integer", "minimum": 1, "maximum": 365}),
                ],
                "responses": {
                    "200": response("List of service SLOs.", {"type": "array", "items": SERVICE_SLO_SCHEMA}),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["services"],
                "summary": "Create service SLO",
                "description": "Creates a Service Level Objective for an SLI on the same service and returns the first evaluation.",
                "operationId": "createServiceSlo",
                "parameters": [path_param("service_id", "Service id.")],
                "requestBody": json_body("Service SLO properties.", SERVICE_SLO_INPUT_SCHEMA),
                "responses": {
                    "201": response("Service SLO created.", SERVICE_SLO_SCHEMA),
                    "400": response("Validation error or SLI/SLO shape mismatch.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service or SLI not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/slos/{slo_id}": {
            "put": {
                "tags": ["services"],
                "summary": "Update service SLO",
                "description": "Updates a Service Level Objective and returns the refreshed evaluation.",
                "operationId": "updateServiceSlo",
                "parameters": [path_param("slo_id", "Service SLO id.")],
                "requestBody": json_body("Updated Service SLO properties.", SERVICE_SLO_INPUT_SCHEMA),
                "responses": {
                    "200": response("Service SLO updated.", SERVICE_SLO_SCHEMA),
                    "400": response("Validation error or SLI/SLO shape mismatch.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service SLO not found.", ERROR_SCHEMA),
                },
            },
            "delete": {
                "tags": ["services"],
                "summary": "Delete service SLO",
                "description": "Soft-deletes a Service Level Objective.",
                "operationId": "deleteServiceSlo",
                "parameters": [path_param("slo_id", "Service SLO id.")],
                "responses": {
                    "200": response("Service SLO deleted.", SERVICE_SLO_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service SLO not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/sli-slo": {
            "get": {
                "tags": ["services"],
                "summary": "List SLI/SLO for readable services",
                "description": "Returns all SLIs and SLOs for services readable in the current scope. Use team_id or service_id to narrow the result.",
                "operationId": "listServiceSliSlo",
                "parameters": SLI_SLO_SCOPE_QUERY_PARAMS,
                "responses": {
                    "200": response("SLI/SLO payload.", SERVICE_SLI_SLO_RESPONSE_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/sli-slo/analytics": {
            "get": {
                "tags": ["services"],
                "summary": "Get SLI/SLO analytics",
                "description": "Returns latest SLO health summary and evaluation rows for services readable in the current scope.",
                "operationId": "getServiceSliSloAnalytics",
                "parameters": [
                    *SLI_SLO_SCOPE_QUERY_PARAMS,
                    query_param("days", "Analytics display window. Each SLO evaluation still uses its own window_days value.", {"type": "integer", "minimum": 1, "maximum": 365, "default": 30}),
                ],
                "responses": {
                    "200": response("SLI/SLO analytics payload.", SERVICE_SLI_SLO_ANALYTICS_RESPONSE_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/{service_id}/readiness": {
            "get": {
                "tags": ["services"],
                "summary": "Get service readiness",
                "description": "Returns the current readiness state, standard evaluations and check results for one service.",
                "operationId": "getServiceReadiness",
                "parameters": [path_param("service_id", "Service id.")],
                "responses": {
                    "200": response("Service readiness payload.", SERVICE_READINESS_RESPONSE_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/{service_id}/readiness/evaluate": {
            "post": {
                "tags": ["services"],
                "summary": "Evaluate service readiness",
                "description": "Runs readiness evaluation for one service and returns the refreshed readiness payload.",
                "operationId": "evaluateServiceReadiness",
                "parameters": [path_param("service_id", "Service id.")],
                "responses": {
                    "200": response("Service readiness payload.", SERVICE_READINESS_RESPONSE_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/{service_id}/timeline": {
            "get": {
                "tags": ["services"],
                "summary": "List service timeline events",
                "description": "Returns service catalog timeline events with optional category/event filters and cursor pagination.",
                "operationId": "listServiceTimelineEvents",
                "parameters": [
                    path_param("service_id", "Service id."),
                    *TIMELINE_QUERY_PARAMS,
                ],
                "responses": {
                    "200": response("Service timeline events.", SERVICE_TIMELINE_RESPONSE_SCHEMA),
                    "400": response("Invalid cursor.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
        },
    }
