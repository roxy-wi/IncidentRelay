from app.api.openapi.common import json_body, path_param, query_param, response
from app.api.openapi.endpoints.service_catalog import (
    READINESS_STATE_SCHEMA,
    SERVICE_READINESS_RESPONSE_SCHEMA,
    SERVICE_TIMELINE_EVENT_SCHEMA,
    SERVICE_SLI_SCHEMA,
    SERVICE_SLO_SCHEMA,
)
from app.api.schemas.limits import (
    DESCRIPTION_MAX_LENGTH,
    NAME_MAX_LENGTH,
    NAME_MIN_LENGTH,
    SLUG_MAX_LENGTH,
    SLUG_MIN_LENGTH,
)


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

SERVICE_CRITICALITIES = [
    "low",
    "medium",
    "high",
    "critical",
]

SERVICE_TIERS = [
    "tier_1",
    "tier_2",
    "tier_3",
    "tier_4",
]

SERVICE_STATUSES = [
    "operational",
    "degraded",
    "partial_outage",
    "major_outage",
    "maintenance",
    "disabled",
    "unknown",
]

SERVICE_STATUS_SOURCES = [
    "manual",
    "alerts",
    "maintenance",
    "system",
]

SERVICE_LINK_TYPES = [
    "dashboard",
    "metrics",
    "logs",
    "traces",
    "repository",
    "documentation",
    "status_page",
    "wiki",
    "other",
]

SERVICE_DEPENDENCY_TYPES = [
    "hard",
    "soft",
    "external",
    "informational",
]

SERVICE_DEPENDENCY_CRITICALITIES = [
    "required",
    "important",
    "optional",
]

SERVICE_IMPACT_REASONS = [
    "none",
    "own_status",
    "alert_group",
    "upstream_dependency",
    "maintenance",
    "disabled",
    "unknown",
]

SERVICE_IMPACT_SORTS = [
    "service",
    "status",
    "effective_status",
    "blast_radius",
    "criticality",
    "tier",
]

SERVICE_ANALYTICS_SORTS = [
    "service",
    "open_alert_groups",
    "critical_open_alert_groups",
    "raw_alerts",
    "dedup_ratio",
    "mtta",
    "mttr",
    "blast_radius",
]


# ---------------------------------------------------------------------------
# Shared OpenAPI helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Core service schemas
# ---------------------------------------------------------------------------

SERVICE_SCHEMA = {
    "type": "object",
    "required": ["team_id", "slug", "name"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "group_id": {
            "type": "integer",
            "readOnly": True,
            "description": "Owner group id inherited from the service team.",
        },
        "team_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Owner team id.",
            "example": 1,
        },
        "team_name": {"type": "string", "nullable": True, "readOnly": True},
        "team_slug": {"type": "string", "nullable": True, "readOnly": True},
        "slug": {
            "type": "string",
            "minLength": SLUG_MIN_LENGTH,
            "maxLength": SLUG_MAX_LENGTH,
            "pattern": "^[a-z0-9][a-z0-9-]*$",
            "description": "Stable service identifier used by API/UI.",
            "example": "rabbitmq-cloud",
        },
        "name": {
            "type": "string",
            "minLength": NAME_MIN_LENGTH,
            "maxLength": NAME_MAX_LENGTH,
            "example": "RabbitMQ Cloud",
        },
        "description": {
            "type": "string",
            "nullable": True,
            "maxLength": DESCRIPTION_MAX_LENGTH,
            "example": "Shared RabbitMQ cluster used by production services.",
        },
        "service_type": {
            "type": "string",
            "enum": SERVICE_TYPES,
            "default": "other",
            "example": "queue",
        },
        "environment": {
            "type": "string",
            "enum": SERVICE_ENVIRONMENTS,
            "default": "production",
        },
        "criticality": {
            "type": "string",
            "enum": SERVICE_CRITICALITIES,
            "default": "medium",
        },
        "tier": {
            "type": "string",
            "enum": SERVICE_TIERS,
            "default": "tier_3",
        },
        "status": {
            "type": "string",
            "enum": SERVICE_STATUSES,
            "default": "operational",
        },
        "status_source": {
            "type": "string",
            "enum": SERVICE_STATUS_SOURCES,
            "default": "manual",
        },
        "status_message": {
            "type": "string",
            "nullable": True,
            "maxLength": DESCRIPTION_MAX_LENGTH,
        },
        "default_rotation_id": {
            "type": "integer",
            "nullable": True,
            "minimum": 1,
            "description": "Default rotation for this service. Must belong to service team.",
        },
        "default_escalation_policy_id": {
            "type": "integer",
            "nullable": True,
            "minimum": 1,
            "description": "Default escalation policy for this service. Must belong to service team.",
        },
        "notification_policy_id": {
            "type": "integer",
            "nullable": True,
            "minimum": 1,
            "description": (
                "Notification policy used when a route selects service policy "
                "delivery. The policy must belong to the service team."
            ),
        },
        "default_rotation_name": {"type": "string", "nullable": True, "readOnly": True},
        "notification_policy_name": {
            "type": "string",
            "nullable": True,
            "readOnly": True,
        },
        "default_escalation_policy_name": {"type": "string", "nullable": True, "readOnly": True},
        "labels": {
            "type": "object",
            "additionalProperties": True,
            "default": {},
            "example": {"system": "messaging", "owner": "infra"},
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
            "example": ["rabbitmq", "production"],
        },
        "metadata": {
            "type": "object",
            "additionalProperties": True,
            "default": {},
        },
        "enabled": {"type": "boolean", "default": True},
        "public": {
            "type": "boolean",
            "default": False,
            "description": "Whether the service can be exposed on status-page style views.",
        },
        "public_name": {
            "type": "string",
            "nullable": True,
            "minLength": NAME_MIN_LENGTH,
            "maxLength": NAME_MAX_LENGTH,
        },
        "public_description": {
            "type": "string",
            "nullable": True,
            "maxLength": DESCRIPTION_MAX_LENGTH,
        },
        "public_order": {
            "type": "integer",
            "minimum": 0,
            "default": 100,
        },
        "permissions": {
            "type": "object",
            "additionalProperties": True,
            "readOnly": True,
        },
    },
}

SERVICE_MATCH_RULE_SCHEMA = {
    "type": "object",
    "required": ["team_id", "service_id", "name", "matchers"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "team_id": {"type": "integer", "minimum": 1},
        "route_id": {
            "type": "integer",
            "minimum": 1,
            "nullable": True,
            "description": "Optional route scope. When null, the rule can match all routes in the team.",
        },
        "route_name": {"type": "string", "nullable": True, "readOnly": True},
        "service_id": {"type": "integer", "minimum": 1},
        "service_name": {"type": "string", "nullable": True, "readOnly": True},
        "position": {
            "type": "integer",
            "minimum": 0,
            "default": 0,
            "description": "Lower position is evaluated first.",
        },
        "name": {
            "type": "string",
            "minLength": NAME_MIN_LENGTH,
            "maxLength": NAME_MAX_LENGTH,
            "example": "RabbitMQ labels",
        },
        "description": {
            "type": "string",
            "nullable": True,
            "maxLength": DESCRIPTION_MAX_LENGTH,
        },
        "matchers": {
            "type": "object",
            "additionalProperties": True,
            "description": "Matcher object evaluated against incoming alert labels/annotations/payload.",
            "example": {
                "labels": {
                    "job": "RabbitMQ",
                    "rabbitmq": {
                        "op": "regex",
                        "value": "^rabbitmq-cloud$",
                    },
                },
            },
        },
        "enabled": {"type": "boolean", "default": True},
    },
}

SERVICE_LINK_SCHEMA = {
    "type": "object",
    "required": ["label", "url"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "service_id": {"type": "integer", "readOnly": True},
        "service_name": {"type": "string", "nullable": True, "readOnly": True},
        "service_slug": {"type": "string", "nullable": True, "readOnly": True},
        "team_id": {"type": "integer", "nullable": True, "readOnly": True},
        "team_name": {"type": "string", "nullable": True, "readOnly": True},
        "team_slug": {"type": "string", "nullable": True, "readOnly": True},
        "link_type": {
            "type": "string",
            "enum": SERVICE_LINK_TYPES,
            "default": "other",
            "example": "dashboard",
        },
        "label": {
            "type": "string",
            "minLength": NAME_MIN_LENGTH,
            "maxLength": NAME_MAX_LENGTH,
            "example": "Grafana dashboard",
        },
        "url": {
            "type": "string",
            "minLength": 3,
            "maxLength": 2048,
            "example": "https://grafana.example.com/d/rabbitmq-cloud",
        },
        "description": {
            "type": "string",
            "nullable": True,
            "maxLength": DESCRIPTION_MAX_LENGTH,
        },
        "priority": {"type": "integer", "minimum": 0, "default": 100},
        "enabled": {"type": "boolean", "default": True},
    },
}

SERVICE_RUNBOOK_SCHEMA = {
    "type": "object",
    "required": ["title", "url"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "service_id": {"type": "integer", "readOnly": True},
        "service_name": {"type": "string", "nullable": True, "readOnly": True},
        "service_slug": {"type": "string", "nullable": True, "readOnly": True},
        "team_id": {"type": "integer", "nullable": True, "readOnly": True},
        "team_name": {"type": "string", "nullable": True, "readOnly": True},
        "team_slug": {"type": "string", "nullable": True, "readOnly": True},
        "title": {
            "type": "string",
            "minLength": NAME_MIN_LENGTH,
            "maxLength": NAME_MAX_LENGTH,
            "example": "RabbitMQ cluster partition",
        },
        "description": {
            "type": "string",
            "nullable": True,
            "maxLength": DESCRIPTION_MAX_LENGTH,
        },
        "url": {
            "type": "string",
            "minLength": 3,
            "maxLength": 2048,
            "example": "https://docs.example.com/runbooks/rabbitmq/cluster-partition",
        },
        "severity": {
            "type": "string",
            "nullable": True,
            "maxLength": NAME_MAX_LENGTH,
            "example": "critical",
        },
        "matchers": {
            "type": "object",
            "additionalProperties": True,
            "default": {},
            "description": "Optional matcher object used to select a more specific runbook.",
            "example": {"labels": {"alertname": "RabbitMQClusterPartition"}},
        },
        "priority": {"type": "integer", "minimum": 0, "default": 100},
        "enabled": {"type": "boolean", "default": True},
    },
}

SERVICE_DEPENDENCY_SCHEMA = {
    "type": "object",
    "required": ["depends_on_service_id"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "service_id": {"type": "integer", "readOnly": True},
        "service_name": {"type": "string", "nullable": True, "readOnly": True},
        "service_slug": {"type": "string", "nullable": True, "readOnly": True},
        "team_id": {"type": "integer", "nullable": True, "readOnly": True},
        "team_name": {"type": "string", "nullable": True, "readOnly": True},
        "team_slug": {"type": "string", "nullable": True, "readOnly": True},
        "depends_on_service_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Upstream service id.",
        },
        "depends_on_service_name": {"type": "string", "nullable": True, "readOnly": True},
        "depends_on_service_slug": {"type": "string", "nullable": True, "readOnly": True},
        "depends_on_service_status": {"type": "string", "nullable": True, "enum": SERVICE_STATUSES},
        "depends_on_team_id": {"type": "integer", "nullable": True, "readOnly": True},
        "depends_on_team_name": {"type": "string", "nullable": True, "readOnly": True},
        "depends_on_team_slug": {"type": "string", "nullable": True, "readOnly": True},
        "dependency_type": {
            "type": "string",
            "enum": SERVICE_DEPENDENCY_TYPES,
            "default": "hard",
        },
        "criticality": {
            "type": "string",
            "enum": SERVICE_DEPENDENCY_CRITICALITIES,
            "default": "important",
        },
        "correlation_enabled": {
            "type": "boolean",
            "default": True,
            "description": "Whether this dependency can be used for dependency-aware alert correlation.",
        },
        "propagation_delay_seconds": {
            "type": "integer",
            "minimum": 0,
            "maximum": 86400,
            "default": 300,
            "description": "Maximum expected propagation delay between related alerts.",
        },
        "description": {
            "type": "string",
            "nullable": True,
            "maxLength": DESCRIPTION_MAX_LENGTH,
        },
        "enabled": {"type": "boolean", "default": True},
    },
}


# ---------------------------------------------------------------------------
# Impact v2 schemas
# ---------------------------------------------------------------------------

SERVICE_IMPACT_PATH_NODE_SCHEMA = {
    "type": "object",
    "properties": {
        "service_id": {"type": "integer", "minimum": 1},
        "service_slug": {"type": "string", "nullable": True},
        "service_name": {"type": "string", "nullable": True},
        "status": {"type": "string", "enum": SERVICE_STATUSES},
        "effective_status": {"type": "string", "enum": SERVICE_STATUSES},
        "impact_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "propagated_impact_score": {"type": "integer", "nullable": True, "minimum": 0, "maximum": 100},
        "dependency_multiplier": {"type": "number", "nullable": True},
        "dependency_type": {
            "type": "string",
            "nullable": True,
            "enum": SERVICE_DEPENDENCY_TYPES,
        },
        "dependency_criticality": {
            "type": "string",
            "nullable": True,
            "enum": SERVICE_DEPENDENCY_CRITICALITIES,
        },
    },
}

SERVICE_IMPACT_ROOT_CAUSE_SCHEMA = {
    "type": "object",
    "properties": {
        "service_id": {"type": "integer", "minimum": 1},
        "service_slug": {"type": "string", "nullable": True},
        "service_name": {"type": "string", "nullable": True},
        "reason": {"type": "string", "enum": SERVICE_IMPACT_REASONS},
        "status": {"type": "string", "enum": SERVICE_STATUSES},
        "effective_status": {"type": "string", "enum": SERVICE_STATUSES},
        "impact_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "severity": {"type": "string", "nullable": True},
        "priority_slug": {"type": "string", "nullable": True},
        "priority_order": {"type": "integer", "nullable": True},
        "open_alert_groups": {"type": "integer", "minimum": 0},
        "critical_open_alert_groups": {"type": "integer", "minimum": 0},
        "path": {
            "type": "array",
            "items": SERVICE_IMPACT_PATH_NODE_SCHEMA,
        },
    },
}

SERVICE_IMPACT_EXPLANATION_SCHEMA = {
    "type": "object",
    "nullable": True,
    "properties": {
        "primary_reason": {"type": "string", "enum": SERVICE_IMPACT_REASONS},
        "primary_source_service_id": {"type": "integer", "nullable": True},
        "primary_source_service_slug": {"type": "string", "nullable": True},
        "primary_source_service_name": {"type": "string", "nullable": True},
        "title": {"type": "string"},
        "message": {"type": "string"},
        "own_impact_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "alert_impact_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "dependency_impact_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "effective_impact_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "rules": {"type": "array", "items": {"type": "string"}},
        "paths": {
            "type": "array",
            "items": {
                "type": "array",
                "items": SERVICE_IMPACT_PATH_NODE_SCHEMA,
            },
        },
    },
}

SERVICE_BLAST_RADIUS_SCHEMA = {
    "type": "object",
    "nullable": True,
    "properties": {
        "direct_downstream": {"type": "integer", "minimum": 0},
        "transitive_downstream": {"type": "integer", "minimum": 0},
        "critical_downstream": {"type": "integer", "minimum": 0},
        "tier_1_downstream": {"type": "integer", "minimum": 0},
        "affected_downstream": {"type": "integer", "minimum": 0},
        "paths": {
            "type": "array",
            "items": {
                "type": "array",
                "items": SERVICE_IMPACT_PATH_NODE_SCHEMA,
            },
        },
        "cycle_detected": {"type": "boolean"},
        "depth_limited": {"type": "boolean"},
    },
}

SERVICE_IMPACT_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "service_id": {"type": "integer", "minimum": 1},
        "service_slug": {"type": "string"},
        "service_name": {"type": "string"},
        "team_id": {"type": "integer", "minimum": 1},
        "team_slug": {"type": "string", "nullable": True},
        "team_name": {"type": "string", "nullable": True},
        "criticality": {"type": "string", "enum": SERVICE_CRITICALITIES},
        "tier": {"type": "string", "enum": SERVICE_TIERS},
        "own_status": {"type": "string", "enum": SERVICE_STATUSES},
        "alert_impact_status": {"type": "string", "enum": SERVICE_STATUSES},
        "dependency_impact_status": {"type": "string", "enum": SERVICE_STATUSES},
        "effective_status": {"type": "string", "enum": SERVICE_STATUSES},
        "own_impact_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "alert_impact_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "dependency_impact_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "effective_impact_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "impact_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "primary_reason": {"type": "string", "enum": SERVICE_IMPACT_REASONS},
        "open_alert_groups": {"type": "integer", "minimum": 0},
        "critical_open_alert_groups": {"type": "integer", "minimum": 0},
        "upstream_issues_count": {"type": "integer", "minimum": 0},
        "root_causes": {
            "type": "array",
            "items": SERVICE_IMPACT_ROOT_CAUSE_SCHEMA,
        },
        "explanation": SERVICE_IMPACT_EXPLANATION_SCHEMA,
        "blast_radius": SERVICE_BLAST_RADIUS_SCHEMA,
        "cycle_detected": {"type": "boolean"},
        "depth_limited": {"type": "boolean"},
    },
}

SERVICE_IMPACT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "version": {"type": "integer", "example": 2},
        "items": {
            "type": "array",
            "items": SERVICE_IMPACT_ITEM_SCHEMA,
        },
        "summary": {
            "type": "object",
            "properties": {
                "total": {"type": "integer", "minimum": 0},
                "affected": {"type": "integer", "minimum": 0},
                "critical": {"type": "integer", "minimum": 0},
                "by_effective_status": {
                    "type": "object",
                    "additionalProperties": {"type": "integer"},
                },
                "max_impact_score": {"type": "integer", "minimum": 0, "maximum": 100},
                "average_impact_score": {"type": "integer", "minimum": 0, "maximum": 100},
                "cycle_detected": {"type": "integer", "minimum": 0},
                "depth_limited": {"type": "integer", "minimum": 0},
            },
        },
        "filters": {"type": "object", "additionalProperties": True},
    },
}


# ---------------------------------------------------------------------------
# Service details v2 schemas
# ---------------------------------------------------------------------------

SERVICE_ALERT_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "window_days": {"type": "integer", "minimum": 1},
        "total": {"type": "integer", "minimum": 0},
        "recent": {"type": "integer", "minimum": 0},
        "open": {"type": "integer", "minimum": 0},
        "firing": {"type": "integer", "minimum": 0},
        "acknowledged": {"type": "integer", "minimum": 0},
        "resolved": {"type": "integer", "minimum": 0},
        "critical_open": {"type": "integer", "minimum": 0},
        "last_seen_at": {"type": "string", "format": "date-time", "nullable": True},
        "by_status": {"type": "object", "additionalProperties": {"type": "integer"}},
        "by_severity": {"type": "object", "additionalProperties": {"type": "integer"}},
    },
}

SERVICE_STATUS_HISTORY_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "old_status": {"type": "string", "nullable": True, "enum": SERVICE_STATUSES},
        "new_status": {"type": "string", "nullable": True, "enum": SERVICE_STATUSES},
        "source": {"type": "string", "nullable": True},
        "message": {"type": "string", "nullable": True},
        "alert_id": {"type": "integer", "nullable": True},
        "maintenance_window_id": {"type": "integer", "nullable": True},
        "changed_by_id": {"type": "integer", "nullable": True},
        "created_at": {"type": "string", "format": "date-time", "nullable": True},
    },
}

SERVICE_DETAILS_ANALYTICS_SCHEMA = {
    "type": "object",
    "properties": {
        "version": {"type": "integer", "example": 1},
        "window": {"type": "object", "additionalProperties": True},
        "widgets": {"type": "object", "additionalProperties": True},
        "breakdowns": {"type": "object", "additionalProperties": True},
        "series": {"type": "array", "items": {"type": "object"}},
        "extensions": {"type": "object", "additionalProperties": True},
    },
}

MAINTENANCE_WINDOW_REFERENCE_SCHEMA = {
    "type": "object",
    "additionalProperties": True,
    "description": "Serialized maintenance window. Full schema is documented in the maintenance windows API.",
}

SERVICE_DETAILS_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "service": SERVICE_SCHEMA,
        "summary": {
            "type": "object",
            "properties": {
                "alerts": SERVICE_ALERT_SUMMARY_SCHEMA,
                "maintenance_windows": {"type": "integer", "minimum": 0},
                "links": {"type": "integer", "minimum": 0},
                "runbooks": {"type": "integer", "minimum": 0},
                "upstream_dependencies": {"type": "integer", "minimum": 0},
                "downstream_dependencies": {"type": "integer", "minimum": 0},
                "timeline_events": {"type": "integer", "minimum": 0},
                "slis": {"type": "integer", "minimum": 0},
                "slos": {"type": "integer", "minimum": 0},
                "readiness": READINESS_STATE_SCHEMA,
            },
        },
        "maintenance_windows": {
            "type": "array",
            "items": MAINTENANCE_WINDOW_REFERENCE_SCHEMA,
        },
        "links": {"type": "array", "items": SERVICE_LINK_SCHEMA},
        "runbooks": {"type": "array", "items": SERVICE_RUNBOOK_SCHEMA},
        "dependencies": {
            "type": "object",
            "properties": {
                "upstream": {"type": "array", "items": SERVICE_DEPENDENCY_SCHEMA},
                "downstream": {"type": "array", "items": SERVICE_DEPENDENCY_SCHEMA},
            },
        },
        "timeline": {"type": "array", "items": SERVICE_TIMELINE_EVENT_SCHEMA},
        "sli_slo": {
            "type": "object",
            "properties": {
                "slis": {"type": "array", "items": SERVICE_SLI_SCHEMA},
                "slos": {"type": "array", "items": SERVICE_SLO_SCHEMA},
            },
        },
        "impact": SERVICE_IMPACT_ITEM_SCHEMA,
        "analytics": SERVICE_DETAILS_ANALYTICS_SCHEMA,
        "readiness": SERVICE_READINESS_RESPONSE_SCHEMA,
    },
}


# ---------------------------------------------------------------------------
# Analytics v2 schemas
# ---------------------------------------------------------------------------

SERVICE_ANALYTICS_ALERT_GROUPS_SCHEMA = {
    "type": "object",
    "properties": {
        "total": {"type": "integer", "minimum": 0},
        "open": {"type": "integer", "minimum": 0},
        "firing": {"type": "integer", "minimum": 0},
        "acknowledged": {"type": "integer", "minimum": 0},
        "resolved": {"type": "integer", "minimum": 0},
        "silenced": {"type": "integer", "minimum": 0},
        "critical_open": {"type": "integer", "minimum": 0},
        "by_status": {"type": "object", "additionalProperties": {"type": "integer"}},
        "by_severity": {"type": "object", "additionalProperties": {"type": "integer"}},
        "first_seen_at": {"type": "string", "format": "date-time", "nullable": True},
        "last_seen_at": {"type": "string", "format": "date-time", "nullable": True},
    },
}

SERVICE_ANALYTICS_NOISE_SCHEMA = {
    "type": "object",
    "properties": {
        "raw_alerts": {"type": "integer", "minimum": 0},
        "alert_groups": {"type": "integer", "minimum": 0},
        "dedup_ratio": {"type": "number", "format": "float", "minimum": 0},
        "top_alertnames": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "alertname": {"type": "string"},
                    "count": {"type": "integer", "minimum": 0},
                },
            },
        },
    },
}

SERVICE_ANALYTICS_RESPONSE_METRICS_SCHEMA = {
    "type": "object",
    "properties": {
        "acknowledged_groups": {"type": "integer", "minimum": 0},
        "resolved_groups": {"type": "integer", "minimum": 0},
        "mtta_seconds_avg": {"type": "integer", "nullable": True, "minimum": 0},
        "mtta_seconds_p50": {"type": "integer", "nullable": True, "minimum": 0},
        "mtta_seconds_p95": {"type": "integer", "nullable": True, "minimum": 0},
        "mttr_seconds_avg": {"type": "integer", "nullable": True, "minimum": 0},
        "mttr_seconds_p50": {"type": "integer", "nullable": True, "minimum": 0},
        "mttr_seconds_p95": {"type": "integer", "nullable": True, "minimum": 0},
    },
}

SERVICE_ANALYTICS_MAINTENANCE_SCHEMA = {
    "type": "object",
    "properties": {
        "windows": {"type": "integer", "minimum": 0},
        "suppressed_alert_groups": {"type": "integer", "minimum": 0},
    },
}

SERVICE_ANALYTICS_IMPACT_WIDGET_SCHEMA = {
    "type": "object",
    "properties": {
        "effective_status": {"type": "string", "enum": SERVICE_STATUSES},
        "primary_reason": {"type": "string", "nullable": True, "enum": SERVICE_IMPACT_REASONS},
        "upstream_issues_count": {"type": "integer", "minimum": 0},
        "root_causes": {"type": "integer", "minimum": 0},
        "blast_radius": {
            "type": "object",
            "properties": {
                "direct_downstream": {"type": "integer", "minimum": 0},
                "transitive_downstream": {"type": "integer", "minimum": 0},
                "critical_downstream": {"type": "integer", "minimum": 0},
                "tier_1_downstream": {"type": "integer", "minimum": 0},
            },
        },
    },
}

SERVICE_ANALYTICS_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "service_id": {"type": "integer", "minimum": 1},
        "service_slug": {"type": "string"},
        "service_name": {"type": "string"},
        "team_id": {"type": "integer", "minimum": 1},
        "team_slug": {"type": "string", "nullable": True},
        "team_name": {"type": "string", "nullable": True},
        "service_status": {"type": "string", "enum": SERVICE_STATUSES},
        "service_criticality": {"type": "string", "enum": SERVICE_CRITICALITIES},
        "service_environment": {"type": "string", "enum": SERVICE_ENVIRONMENTS},
        "service_tier": {"type": "string", "enum": SERVICE_TIERS},
        "enabled": {"type": "boolean"},
        "window": {"type": "object", "additionalProperties": True},
        "alert_groups": SERVICE_ANALYTICS_ALERT_GROUPS_SCHEMA,
        "noise": SERVICE_ANALYTICS_NOISE_SCHEMA,
        "response": SERVICE_ANALYTICS_RESPONSE_METRICS_SCHEMA,
        "maintenance": SERVICE_ANALYTICS_MAINTENANCE_SCHEMA,
        "impact": SERVICE_ANALYTICS_IMPACT_WIDGET_SCHEMA,
        "last_alert_at": {"type": "string", "format": "date-time", "nullable": True},
    },
}

SERVICE_ANALYTICS_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "version": {"type": "integer", "example": 2},
        "window": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1, "maximum": 365},
                "since": {"type": "string", "format": "date-time"},
                "until": {"type": "string", "format": "date-time"},
            },
        },
        "items": {
            "type": "array",
            "items": SERVICE_ANALYTICS_ITEM_SCHEMA,
        },
        "summary": {
            "type": "object",
            "properties": {
                "services": {"type": "integer", "minimum": 0},
                "affected_services": {"type": "integer", "minimum": 0},
                "open_alert_groups": {"type": "integer", "minimum": 0},
                "critical_open_alert_groups": {"type": "integer", "minimum": 0},
                "raw_alerts": {"type": "integer", "minimum": 0},
                "by_effective_status": {
                    "type": "object",
                    "additionalProperties": {"type": "integer"},
                },
                "top_noisy_services": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                },
            },
        },
        "series": {
            "type": "object",
            "properties": {
                "alert_groups_by_day": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                },
                "raw_alerts_by_day": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                },
                "impact_by_day": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                },
            },
        },
        "filters": {"type": "object", "additionalProperties": True},
    },
}


# ---------------------------------------------------------------------------
# Query parameter sets
# ---------------------------------------------------------------------------

SERVICE_IMPACT_QUERY_PARAMS = [
    query_param("team_id", "Filter by team id.", {"type": "integer", "minimum": 1}),
    query_param(
        "service_id",
        "Return one service item while still calculating the readable dependency graph.",
        {"type": "integer", "minimum": 1},
    ),
    query_param("include_disabled", "Include disabled services.", {"type": "boolean", "default": False}),
    query_param("include_operational", "Include operational services.", {"type": "boolean", "default": True}),
    query_param("include_explanation", "Include human-readable explanation blocks.", {"type": "boolean", "default": True}),
    query_param("include_root_causes", "Include root cause services.", {"type": "boolean", "default": True}),
    query_param("include_blast_radius", "Include downstream blast radius.", {"type": "boolean", "default": True}),
    query_param("include_paths", "Include dependency paths.", {"type": "boolean", "default": True}),
    query_param("max_depth", "Dependency traversal depth.", {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}),
    query_param("limit", "Maximum returned items.", {"type": "integer", "minimum": 1, "maximum": 500, "default": 100}),
    query_param("sort", "Sort field.", {"type": "string", "enum": SERVICE_IMPACT_SORTS, "default": "effective_status"}),
    query_param("order", "Sort order.", {"type": "string", "enum": ["asc", "desc"], "default": "desc"}),
]

SERVICE_SINGLE_IMPACT_QUERY_PARAMS = [
    query_param("include_disabled", "Include disabled service result.", {"type": "boolean", "default": False}),
    query_param("include_explanation", "Include human-readable explanation blocks.", {"type": "boolean", "default": True}),
    query_param("include_root_causes", "Include root cause services.", {"type": "boolean", "default": True}),
    query_param("include_blast_radius", "Include downstream blast radius.", {"type": "boolean", "default": True}),
    query_param("include_paths", "Include dependency paths.", {"type": "boolean", "default": True}),
    query_param("max_depth", "Dependency traversal depth.", {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}),
]

SERVICE_ANALYTICS_QUERY_PARAMS = [
    query_param("team_id", "Filter by team id.", {"type": "integer", "minimum": 1}),
    query_param(
        "service_id",
        "Return analytics for one service while still calculating impact using the readable dependency graph.",
        {"type": "integer", "minimum": 1},
    ),
    query_param("days", "Analytics window in days.", {"type": "integer", "minimum": 1, "maximum": 365, "default": 30}),
    query_param("include_disabled", "Include disabled services.", {"type": "boolean", "default": False}),
    query_param("include_operational", "Include operational services.", {"type": "boolean", "default": True}),
    query_param("include_series", "Include daily time series.", {"type": "boolean", "default": True}),
    query_param("include_noise", "Include raw alert/noise metrics.", {"type": "boolean", "default": True}),
    query_param("include_response", "Include response-time metrics when available.", {"type": "boolean", "default": True}),
    query_param("include_maintenance", "Include maintenance suppression counters.", {"type": "boolean", "default": True}),
    query_param("include_impact", "Include current Impact v2 widget per service.", {"type": "boolean", "default": True}),
    query_param("limit", "Maximum returned items.", {"type": "integer", "minimum": 1, "maximum": 500, "default": 100}),
    query_param("sort", "Sort field.", {"type": "string", "enum": SERVICE_ANALYTICS_SORTS, "default": "open_alert_groups"}),
    query_param("order", "Sort order.", {"type": "string", "enum": ["asc", "desc"], "default": "desc"}),
]

SERVICE_DETAILS_QUERY_PARAMS = [
    query_param("days", "Analytics window in days.", {"type": "integer", "minimum": 1, "maximum": 365, "default": 30}),
]

SERVICE_OWNER_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "service_id": {"type": "integer"},
        "user_id": {"type": "integer", "nullable": True},
        "user": {
            "type": "object",
            "nullable": True,
            "properties": {
                "id": {"type": "integer"},
                "username": {"type": "string"},
                "email": {"type": "string", "nullable": True},
                "display_name": {"type": "string", "nullable": True},
            },
        },
        "role": {"type": "string"},
        "active": {"type": "boolean"},
        "source": {"type": "string", "nullable": True},
        "notify_on_created": {"type": "boolean"},
        "notify_on_priority_change": {"type": "boolean"},
        "notify_on_status_change": {"type": "boolean"},
        "notify_on_resolved": {"type": "boolean"},
        "created_at": {"type": "string", "nullable": True},
        "updated_at": {"type": "string", "nullable": True},
    },
}


SERVICE_OWNER_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "user_id": {
            "type": "integer",
            "nullable": True,
            "description": "IncidentRelay user copied as stakeholder for new incidents.",
        },
        "role": {
            "type": "string",
            "description": "Stakeholder role, for example owner, business_owner, support.",
            "example": "business_owner",
        },
        "active": {
            "type": "boolean",
            "default": True,
        },
        "notify_on_created": {
            "type": "boolean",
            "default": True,
        },
        "notify_on_priority_change": {
            "type": "boolean",
            "default": True,
        },
        "notify_on_status_change": {
            "type": "boolean",
            "default": True,
        },
        "notify_on_resolved": {
            "type": "boolean",
            "default": True,
        },
    },
    "required": ["user_id"],
}

# ---------------------------------------------------------------------------
# OpenAPI endpoint module interface
# ---------------------------------------------------------------------------


def tags():
    """Return OpenAPI tags."""
    return [
        {
            "name": "services",
            "description": (
                "Service directory and affected-system model. "
                "Services group alerts by the logical system that is broken, "
                "can be linked to routes, matched by alert labels, and can expose "
                "runbooks, links, dependencies, analytics and impact status."
            ),
        }
    ]


def paths():
    """Return OpenAPI paths for service endpoints."""
    return {
        "/api/services": {
            "get": {
                "tags": ["services"],
                "summary": "List services",
                "description": (
                    "Returns services visible to the current user. "
                    "Optional team_id filters services by team."
                ),
                "operationId": "listServices",
                "parameters": [
                    query_param(
                        "team_id",
                        "Filter services by team id.",
                        {"type": "integer", "minimum": 1},
                    )
                ],
                "responses": {
                    "200": response("List of services.", {"type": "array", "items": SERVICE_SCHEMA}),
                    "403": response("Access denied.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["services"],
                "summary": "Create service",
                "description": "Creates a logical service under a team. Team write access is required.",
                "operationId": "createService",
                "requestBody": json_body("Service properties.", SERVICE_SCHEMA),
                "responses": {
                    "201": response("Service created.", SERVICE_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/{service_id}": {
            "get": {
                "tags": ["services"],
                "summary": "Get service",
                "description": "Returns one service by id.",
                "operationId": "getService",
                "parameters": [path_param("service_id", "Service id.")],
                "responses": {
                    "200": response("Service details.", SERVICE_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
            "put": {
                "tags": ["services"],
                "summary": "Update service",
                "description": "Updates service properties. Team write access is required for both old and new team.",
                "operationId": "updateService",
                "parameters": [path_param("service_id", "Service id.")],
                "requestBody": json_body("Updated service properties.", SERVICE_SCHEMA),
                "responses": {
                    "200": response("Service updated.", SERVICE_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
            "delete": {
                "tags": ["services"],
                "summary": "Delete service",
                "description": "Soft-deletes a service. Existing alerts keep their service reference.",
                "operationId": "deleteService",
                "parameters": [path_param("service_id", "Service id.")],
                "responses": {
                    "200": response("Service deleted.", DELETE_RESPONSE_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/{service_id}/details": {
            "get": {
                "tags": ["services"],
                "summary": "Get expanded service details",
                "description": (
                    "Returns the Service details v2 payload used by the UI details panel. "
                    "It contains service metadata, alert summary, maintenance windows, links, "
                    "runbooks, dependencies, service timeline events, readiness, current "
                    "Impact v2 item and a small analytics widget block."
                ),
                "operationId": "getServiceDetails",
                "parameters": [
                    path_param("service_id", "Service id."),
                    *SERVICE_DETAILS_QUERY_PARAMS,
                ],
                "responses": {
                    "200": response("Expanded service details.", SERVICE_DETAILS_RESPONSE_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/match-rules": {
            "get": {
                "tags": ["services"],
                "summary": "List service match rules",
                "description": "Returns service match rules filtered by team_id, route_id or service_id. At least one filter is required.",
                "operationId": "listServiceMatchRules",
                "parameters": [
                    query_param("team_id", "Filter by team id.", {"type": "integer", "minimum": 1}),
                    query_param("route_id", "Filter by route id.", {"type": "integer", "minimum": 1}),
                    query_param("service_id", "Filter by service id.", {"type": "integer", "minimum": 1}),
                ],
                "responses": {
                    "200": response("List of service match rules.", {"type": "array", "items": SERVICE_MATCH_RULE_SCHEMA}),
                    "400": response("Missing or invalid filter.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/{service_id}/match-rules": {
            "get": {
                "tags": ["services"],
                "summary": "List service match rules by service",
                "description": "Returns match rules attached to one service.",
                "operationId": "listMatchRulesByService",
                "parameters": [path_param("service_id", "Service id.")],
                "responses": {
                    "200": response("List of service match rules.", {"type": "array", "items": SERVICE_MATCH_RULE_SCHEMA}),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["services"],
                "summary": "Create service match rule",
                "description": "Creates a rule that resolves incoming alerts to a service. The service_id in URL and request body must match.",
                "operationId": "createServiceMatchRule",
                "parameters": [path_param("service_id", "Service id.")],
                "requestBody": json_body("Service match rule properties.", SERVICE_MATCH_RULE_SCHEMA),
                "responses": {
                    "201": response("Service match rule created.", SERVICE_MATCH_RULE_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/match-rules/{rule_id}": {
            "put": {
                "tags": ["services"],
                "summary": "Update service match rule",
                "description": "Updates one service match rule.",
                "operationId": "updateServiceMatchRule",
                "parameters": [path_param("rule_id", "Service match rule id.")],
                "requestBody": json_body("Updated service match rule properties.", SERVICE_MATCH_RULE_SCHEMA),
                "responses": {
                    "200": response("Service match rule updated.", SERVICE_MATCH_RULE_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service match rule not found.", ERROR_SCHEMA),
                },
            },
            "delete": {
                "tags": ["services"],
                "summary": "Delete service match rule",
                "description": "Soft-deletes one service match rule.",
                "operationId": "deleteServiceMatchRule",
                "parameters": [path_param("rule_id", "Service match rule id.")],
                "responses": {
                    "200": response("Service match rule deleted.", DELETE_RESPONSE_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service match rule not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/{service_id}/links": {
            "get": {
                "tags": ["services"],
                "summary": "List service links",
                "description": "Returns dashboard, metrics, logs, repository or documentation links for one service.",
                "operationId": "listServiceLinks",
                "parameters": [path_param("service_id", "Service id.")],
                "responses": {
                    "200": response("List of service links.", {"type": "array", "items": SERVICE_LINK_SCHEMA}),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["services"],
                "summary": "Create service link",
                "description": "Creates a link for one service.",
                "operationId": "createServiceLink",
                "parameters": [path_param("service_id", "Service id.")],
                "requestBody": json_body("Service link properties.", SERVICE_LINK_SCHEMA),
                "responses": {
                    "201": response("Service link created.", SERVICE_LINK_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/links": {
            "get": {
                "tags": ["services"],
                "summary": "List links for readable services",
                "description": "Returns links for all readable services in the current scope. Use team_id or service_id to narrow the result.",
                "operationId": "listAllServiceLinks",
                "parameters": [
                    query_param("team_id", "Filter by team id.", {"type": "integer", "minimum": 1}),
                    query_param("service_id", "Filter by service id.", {"type": "integer", "minimum": 1}),
                ],
                "responses": {
                    "200": response("List of service links.", {"type": "array", "items": SERVICE_LINK_SCHEMA}),
                    "403": response("Access denied.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/links/{link_id}": {
            "put": {
                "tags": ["services"],
                "summary": "Update service link",
                "description": "Updates one service link.",
                "operationId": "updateServiceLink",
                "parameters": [path_param("link_id", "Service link id.")],
                "requestBody": json_body("Updated service link.", SERVICE_LINK_SCHEMA),
                "responses": {
                    "200": response("Service link updated.", SERVICE_LINK_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service link not found.", ERROR_SCHEMA),
                },
            },
            "delete": {
                "tags": ["services"],
                "summary": "Delete service link",
                "description": "Soft-deletes one service link.",
                "operationId": "deleteServiceLink",
                "parameters": [path_param("link_id", "Service link id.")],
                "responses": {
                    "200": response("Service link deleted.", DELETE_RESPONSE_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service link not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/{service_id}/runbooks": {
            "get": {
                "tags": ["services"],
                "summary": "List service runbooks",
                "description": "Returns runbooks for one service.",
                "operationId": "listServiceRunbooks",
                "parameters": [path_param("service_id", "Service id.")],
                "responses": {
                    "200": response("List of service runbooks.", {"type": "array", "items": SERVICE_RUNBOOK_SCHEMA}),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["services"],
                "summary": "Create service runbook",
                "description": "Creates a runbook for one service.",
                "operationId": "createServiceRunbook",
                "parameters": [path_param("service_id", "Service id.")],
                "requestBody": json_body("Service runbook properties.", SERVICE_RUNBOOK_SCHEMA),
                "responses": {
                    "201": response("Service runbook created.", SERVICE_RUNBOOK_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/runbooks": {
            "get": {
                "tags": ["services"],
                "summary": "List runbooks for readable services",
                "description": "Returns runbooks for all readable services in the current scope. Use team_id or service_id to narrow the result.",
                "operationId": "listAllServiceRunbooks",
                "parameters": [
                    query_param("team_id", "Filter by team id.", {"type": "integer", "minimum": 1}),
                    query_param("service_id", "Filter by service id.", {"type": "integer", "minimum": 1}),
                ],
                "responses": {
                    "200": response("List of service runbooks.", {"type": "array", "items": SERVICE_RUNBOOK_SCHEMA}),
                    "403": response("Access denied.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/runbooks/{runbook_id}": {
            "put": {
                "tags": ["services"],
                "summary": "Update service runbook",
                "description": "Updates one service runbook.",
                "operationId": "updateServiceRunbook",
                "parameters": [path_param("runbook_id", "Service runbook id.")],
                "requestBody": json_body("Updated service runbook.", SERVICE_RUNBOOK_SCHEMA),
                "responses": {
                    "200": response("Service runbook updated.", SERVICE_RUNBOOK_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service runbook not found.", ERROR_SCHEMA),
                },
            },
            "delete": {
                "tags": ["services"],
                "summary": "Delete service runbook",
                "description": "Soft-deletes one service runbook.",
                "operationId": "deleteServiceRunbook",
                "parameters": [path_param("runbook_id", "Service runbook id.")],
                "responses": {
                    "200": response("Service runbook deleted.", DELETE_RESPONSE_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service runbook not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/{service_id}/dependencies": {
            "get": {
                "tags": ["services"],
                "summary": "List service dependencies",
                "description": "Returns upstream dependencies for one service.",
                "operationId": "listServiceDependencies",
                "parameters": [path_param("service_id", "Service id.")],
                "responses": {
                    "200": response("List of service dependencies.", {"type": "array", "items": SERVICE_DEPENDENCY_SCHEMA}),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["services"],
                "summary": "Create service dependency",
                "description": "Creates a dependency from this service to another service. Cross-team dependencies are allowed when the user can edit the source service and read the target service.",
                "operationId": "createServiceDependency",
                "parameters": [path_param("service_id", "Service id.")],
                "requestBody": json_body("Service dependency properties.", SERVICE_DEPENDENCY_SCHEMA),
                "responses": {
                    "201": response("Service dependency created.", SERVICE_DEPENDENCY_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/dependencies": {
            "get": {
                "tags": ["services"],
                "summary": "List dependencies for readable services",
                "description": "Returns dependencies for all readable services in the current scope. Use team_id or service_id to narrow the result.",
                "operationId": "listAllServiceDependencies",
                "parameters": [
                    query_param("team_id", "Filter by team id.", {"type": "integer", "minimum": 1}),
                    query_param("service_id", "Filter by service id.", {"type": "integer", "minimum": 1}),
                ],
                "responses": {
                    "200": response("List of service dependencies.", {"type": "array", "items": SERVICE_DEPENDENCY_SCHEMA}),
                    "403": response("Access denied.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/dependencies/{dependency_id}": {
            "put": {
                "tags": ["services"],
                "summary": "Update service dependency",
                "description": "Updates one service dependency.",
                "operationId": "updateServiceDependency",
                "parameters": [path_param("dependency_id", "Service dependency id.")],
                "requestBody": json_body("Updated service dependency.", SERVICE_DEPENDENCY_SCHEMA),
                "responses": {
                    "200": response("Service dependency updated.", SERVICE_DEPENDENCY_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service dependency not found.", ERROR_SCHEMA),
                },
            },
            "delete": {
                "tags": ["services"],
                "summary": "Delete service dependency",
                "description": "Soft-deletes one service dependency.",
                "operationId": "deleteServiceDependency",
                "parameters": [path_param("dependency_id", "Service dependency id.")],
                "responses": {
                    "200": response("Service dependency deleted.", DELETE_RESPONSE_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service dependency not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/impact": {
            "get": {
                "tags": ["services"],
                "summary": "Service impact v2",
                "description": (
                    "Returns the current computed service impact v2 payload. "
                    "Impact combines service own status, open grouped alert impact, "
                    "upstream dependency impact, root causes, explanation paths and "
                    "downstream blast radius. Impact is based on AlertGroup, not raw Alert events."
                ),
                "operationId": "listServiceImpactV2",
                "parameters": SERVICE_IMPACT_QUERY_PARAMS,
                "responses": {
                    "200": response("Service Impact v2 payload.", SERVICE_IMPACT_RESPONSE_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/{service_id}/impact": {
            "get": {
                "tags": ["services"],
                "summary": "Single service impact v2",
                "description": (
                    "Returns one Service Impact v2 item. The selected service is the result filter only; "
                    "the readable dependency graph is still calculated so upstream root causes remain visible."
                ),
                "operationId": "getServiceImpactV2",
                "parameters": [
                    path_param("service_id", "Service id."),
                    *SERVICE_SINGLE_IMPACT_QUERY_PARAMS,
                ],
                "responses": {
                    "200": response("Service Impact v2 item.", SERVICE_IMPACT_ITEM_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/analytics": {
            "get": {
                "tags": ["services"],
                "summary": "Service analytics v2",
                "description": (
                    "Returns historical service analytics v2 for a selected window. "
                    "Analytics uses AlertGroup for grouped operational metrics and raw Alert for noise metrics. "
                    "The impact widget is the current Impact v2 state, not historical impact."
                ),
                "operationId": "getServiceAnalyticsV2",
                "parameters": SERVICE_ANALYTICS_QUERY_PARAMS,
                "responses": {
                    "200": response("Service Analytics v2 payload.", SERVICE_ANALYTICS_RESPONSE_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Service not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/services/{service_id}/owners": {
            "get": {
                "tags": ["services"],
                "summary": "List service default stakeholders",
                "description": (
                    "Returns default stakeholders configured for a service. "
                    "Active service owners are copied to newly created incidents "
                    "as incident stakeholders."
                ),
                "security": [{"bearerAuth": []}],
                "parameters": [
                    {
                        "name": "service_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Service default stakeholders",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": SERVICE_OWNER_SCHEMA,
                                }
                            }
                        },
                    }
                },
            },
            "post": {
                "tags": ["services"],
                "summary": "Create service default stakeholder",
                "description": (
                    "Creates a default stakeholder for a service. "
                    "The stakeholder is copied to new incidents created for this service."
                ),
                "security": [{"bearerAuth": []}],
                "parameters": [
                    {
                        "name": "service_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": SERVICE_OWNER_INPUT_SCHEMA,
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": "Service default stakeholder created",
                        "content": {
                            "application/json": {
                                "schema": SERVICE_OWNER_SCHEMA,
                            }
                        },
                    }
                },
            },
        },
        "/api/services/{service_id}/owners/{owner_id}": {
            "put": {
                "tags": ["services"],
                "summary": "Update service default stakeholder",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    {
                        "name": "service_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    },
                    {
                        "name": "owner_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    },
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": SERVICE_OWNER_INPUT_SCHEMA,
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Service default stakeholder updated",
                        "content": {
                            "application/json": {
                                "schema": SERVICE_OWNER_SCHEMA,
                            }
                        },
                    }
                },
            },
            "delete": {
                "tags": ["services"],
                "summary": "Deactivate service default stakeholder",
                "description": (
                    "Deactivates a service default stakeholder. "
                    "Existing incident stakeholders are not changed."
                ),
                "security": [{"bearerAuth": []}],
                "parameters": [
                    {
                        "name": "service_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    },
                    {
                        "name": "owner_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    },
                ],
                "responses": {
                    "200": {
                        "description": "Service default stakeholder deactivated",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "deleted": {"type": "boolean"},
                                        "id": {"type": "integer"},
                                    },
                                }
                            }
                        },
                    }
                },
            },
        },
    }
