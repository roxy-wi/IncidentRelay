from app.api.openapi.common import response, path_param, json_body, query_param
from app.api.openapi.endpoints.business_services import BUSINESS_SERVICE_IMPACT_SCHEMA


def string_path_param(name, description):
    """Build a string path parameter."""
    return {
        "name": name,
        "in": "path",
        "required": True,
        "description": description,
        "schema": {"type": "string", "minLength": 1},
    }


def query_array_param(name, description, items_schema=None):
    """Build a repeated query parameter.

    Example:
        ?status=firing&status=acknowledged
    """

    return {
        "name": name,
        "in": "query",
        "required": False,
        "description": description,
        "style": "form",
        "explode": True,
        "schema": {
            "type": "array",
            "items": items_schema or {"type": "string"},
        },
    }


def date_time_property(description, nullable=False):
    """Build an OpenAPI date-time property."""

    schema = {
        "type": "string",
        "format": "date-time",
        "description": description,
    }

    if nullable:
        schema["nullable"] = True

    return schema


def user_short_schema():
    """Build a compact user schema."""

    return {
        "type": "object",
        "nullable": True,
        "properties": {
            "id": {"type": "integer"},
            "username": {"type": "string"},
            "display_name": {"type": "string", "nullable": True},
            "email": {"type": "string", "nullable": True},
            "telegram_user_id": {"type": "string", "nullable": True},
            "slack_user_id": {"type": "string", "nullable": True},
            "mattermost_user_id": {"type": "string", "nullable": True},
        },
    }


def alert_child_schema(include_payload=False):
    """Build a child alert response schema."""

    properties = {
        "type": {"type": "string", "enum": ["alert"]},
        "id": {"type": "integer"},
        "group_id": {"type": "integer", "nullable": True},
        "team_id": {"type": "integer", "nullable": True},
        "route_id": {"type": "integer", "nullable": True},
        "service_id": {"type": "integer", "nullable": True},
        "rotation_id": {"type": "integer", "nullable": True},
        "source": {"type": "string"},
        "external_id": {"type": "string", "nullable": True},
        "dedup_key": {"type": "string"},
        "group_key": {"type": "string"},
        "title": {"type": "string"},
        "message": {"type": "string", "nullable": True},
        "severity": {"type": "string", "nullable": True},
        "status": {"type": "string"},
        "previous_status": {"type": "string", "nullable": True},
        "silenced": {"type": "boolean"},
        "labels": {"type": "object", "additionalProperties": True},
        "labels_count": {"type": "integer"},
        "assignee": {"type": "string", "nullable": True},
        "assignee_id": {"type": "integer", "nullable": True},
        "assignee_details": user_short_schema(),
        "first_seen_at": date_time_property(
            "First time this child alert was seen in UTC.",
        ),
        "last_seen_at": date_time_property(
            "Last time this child alert was seen in UTC.",
        ),
        "resolved_at": date_time_property(
            "Time when this child alert was resolved in UTC.",
            nullable=True,
        ),
    }

    if include_payload:
        properties["payload"] = {
            "type": "object",
            "nullable": True,
            "additionalProperties": True,
        }

    return {
        "type": "object",
        "properties": properties,
    }


def alert_event_schema():
    """Build alert event response schema."""

    return {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "alert_id": {"type": "integer", "nullable": True},
            "group_id": {"type": "integer", "nullable": True},
            "event_type": {"type": "string"},
            "message": {"type": "string", "nullable": True},
            "user_id": {"type": "integer", "nullable": True},
            "created_at": date_time_property("Event timestamp in UTC."),
        },
        "additionalProperties": True,
    }


def alert_notification_schema():
    """Build alert notification response schema."""

    return {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "alert_id": {"type": "integer", "nullable": True},
            "group_id": {"type": "integer", "nullable": True},
            "channel_id": {"type": "integer", "nullable": True},
            "provider": {"type": "string", "nullable": True},
            "status": {"type": "string", "nullable": True},
            "event_type": {"type": "string", "nullable": True},
            "external_message_id": {"type": "string", "nullable": True},
            "last_error": {"type": "string", "nullable": True},
            "created_at": date_time_property("Notification record creation timestamp in UTC.", nullable=True),
            "updated_at": date_time_property("Notification record update timestamp in UTC.", nullable=True),
        },
        "additionalProperties": True,
    }


def alert_explain_step_schema():
    """Build alert explain step response schema."""
    return {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "position": {
                "type": "integer",
                "description": "Step order inside this trace.",
            },
            "stage": {
                "type": "string",
                "description": "Processing stage, for example intake, routing, grouping or notification.",
                "example": "routing",
            },
            "code": {
                "type": "string",
                "description": "Machine-readable step code.",
                "example": "route_matched",
            },
            "status": {
                "type": "string",
                "description": "Step status.",
                "example": "success",
            },
            "title": {
                "type": "string",
                "description": "Human-readable step title.",
                "example": "Route matched",
            },
            "message": {
                "type": "string",
                "nullable": True,
                "description": "Optional human-readable details.",
            },
            "data": {
                "type": "object",
                "additionalProperties": True,
                "description": "Step-specific diagnostic data.",
            },
            "created_at": date_time_property(
                "Step creation timestamp in UTC.",
                nullable=True,
            ),
        },
        "additionalProperties": True,
    }


def alert_explain_trace_schema(include_steps=False):
    """Build alert explain trace response schema."""
    properties = {
        "id": {"type": "integer"},
        "trace_id": {
            "type": "string",
            "description": "Public trace id returned by integration ingest responses.",
            "example": "4fd2a8c9-8c2f-44e8-96fd-77b7f03e72f2",
        },
        "mode": {
            "type": "string",
            "description": "Trace mode.",
            "example": "live",
        },
        "group_id": {
            "type": "integer",
            "nullable": True,
            "description": "Alert group id when processing created or reused an alert group.",
        },
        "alert_id": {
            "type": "integer",
            "nullable": True,
            "description": "Child alert id when processing created or updated an alert.",
        },
        "source": {
            "type": "string",
            "nullable": True,
            "description": "Alert source.",
            "example": "alertmanager",
        },
        "dedup_key": {
            "type": "string",
            "nullable": True,
            "description": "Normalized alert deduplication key.",
        },
        "status": {
            "type": "string",
            "description": "Trace processing status.",
            "example": "completed",
        },
        "outcome": {
            "type": "string",
            "nullable": True,
            "description": "Processing outcome.",
            "example": "created",
        },
        "reason": {
            "type": "string",
            "nullable": True,
            "description": "Reason for stopped or failed processing.",
        },
        "input_summary": {
            "type": "object",
            "additionalProperties": True,
            "description": "Safe summary of the incoming alert payload.",
        },
        "result": {
            "type": "object",
            "additionalProperties": True,
            "description": "Safe summary of the processing result.",
        },
        "started_at": date_time_property(
            "Trace start timestamp in UTC.",
            nullable=True,
        ),
        "finished_at": date_time_property(
            "Trace finish timestamp in UTC.",
            nullable=True,
        ),
    }

    if include_steps:
        properties["steps"] = {
            "type": "array",
            "items": alert_explain_step_schema(),
        }

    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": True,
    }


def alert_correlation_summary_schema():
    """Build compact alert correlation summary schema."""
    return {
        "type": "object",
        "properties": {
            "total": {"type": "integer", "minimum": 0},
            "root_candidates": {"type": "integer", "minimum": 0},
            "downstream_impacts": {"type": "integer", "minimum": 0},
            "best_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "roles": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["possible_symptom", "possible_root_cause"],
                },
            },
            "has_correlation": {"type": "boolean"},
        },
        "additionalProperties": True,
    }


def alert_correlation_group_ref_schema():
    """Build compact alert group reference schema for correlations."""
    return {
        "type": "object",
        "nullable": True,
        "properties": {
            "id": {"type": "integer"},
            "title": {"type": "string"},
            "status": {"type": "string"},
            "severity": {"type": "string", "nullable": True},
            "priority": {"type": "string", "nullable": True},
            "service_id": {"type": "integer", "nullable": True},
            "service_slug": {"type": "string", "nullable": True},
            "service_name": {"type": "string", "nullable": True},
            "source": {"type": "string", "nullable": True},
            "last_seen_at": date_time_property("Last seen timestamp in UTC.", nullable=True),
        },
        "additionalProperties": True,
    }


def alert_group_correlation_schema():
    """Build saved alert group correlation schema."""
    group_ref = alert_correlation_group_ref_schema()

    return {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "role": {
                "type": "string",
                "enum": ["possible_symptom", "possible_root_cause", "related"],
            },
            "relation_type": {
                "type": "string",
                "enum": [
                    "possible_root_cause",
                    "possible_downstream_impact",
                    "same_dependency_chain",
                ],
            },
            "direction": {"type": "string", "enum": ["upstream", "downstream"]},
            "score": {"type": "integer", "minimum": 0, "maximum": 100},
            "depth": {"type": "integer", "minimum": 1},
            "dependency_type": {"type": "string", "nullable": True},
            "criticality": {"type": "string", "nullable": True},
            "reason": {"type": "string", "nullable": True},
            "active": {"type": "boolean"},
            "first_seen_at": date_time_property("First correlation timestamp in UTC."),
            "last_seen_at": date_time_property("Last correlation timestamp in UTC."),
            "root_group": group_ref,
            "related_group": group_ref,
            "peer_group": group_ref,
        },
        "additionalProperties": True,
    }


def alert_group_correlations_schema():
    """Build alert group details correlation block schema."""
    return {
        "type": "object",
        "properties": {
            "root_candidates": {
                "type": "array",
                "items": alert_group_correlation_schema(),
            },
            "downstream_impacts": {
                "type": "array",
                "items": alert_group_correlation_schema(),
            },
            "total": {"type": "integer", "minimum": 0},
        },
        "additionalProperties": True,
    }


def alert_group_business_impact_summary_schema():
    return {
        "type": "object",
        "properties": {
            "has_business_impact": {"type": "boolean"},
            "total": {"type": "integer"},
            "highest_status": {
                "type": "string",
                "nullable": True,
                "enum": [
                    "unknown",
                    "operational",
                    "degraded",
                    "partial_outage",
                    "major_outage",
                    "maintenance",
                    None,
                ],
            },
            "highest_score": {"type": "integer"},
            "services": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "business_service_id": {"type": "integer"},
                        "business_service_slug": {"type": "string"},
                        "business_service_name": {"type": "string"},
                        "public_name": {"type": "string"},
                        "impact_status": {"type": "string"},
                        "impact_score": {"type": "integer"},
                    },
                },
            },
        },
    }


def alert_group_schema(include_details=False):
    """Build an alert group response schema.

    /api/alerts keeps the historical URL, but items are alert groups.
    """

    properties = {
        "type": {"type": "string", "enum": ["alert_group"]},
        "id": {"type": "integer"},
        "team_id": {"type": "integer", "nullable": True},
        "team_slug": {"type": "string", "nullable": True},
        "team_name": {"type": "string", "nullable": True},
        "route_id": {"type": "integer", "nullable": True},
        "route_name": {"type": "string", "nullable": True},
        "route_source": {"type": "string", "nullable": True},
        "service_id": {"type": "integer", "nullable": True},
        "service_slug": {"type": "string", "nullable": True},
        "service_name": {"type": "string", "nullable": True},
        "rotation_id": {"type": "integer", "nullable": True},
        "rotation_name": {"type": "string", "nullable": True},
        "rotation_reminder_interval_seconds": {
            "type": "integer",
            "nullable": True,
            "minimum": 0,
            "description": "Reminder interval in seconds. 0 disables reminders.",
        },
        "source": {"type": "string"},
        "group_key": {"type": "string"},
        "title": {"type": "string"},
        "message": {"type": "string", "nullable": True},
        "severity": {"type": "string", "nullable": True},
        "status": {
            "type": "string",
            "enum": ["firing", "acknowledged", "resolved", "silenced", "merged"],
        },
        "previous_status": {"type": "string", "nullable": True},
        "silenced": {"type": "boolean"},
        "common_labels": {
            "type": "object",
            "nullable": True,
            "additionalProperties": True,
            "description": "Labels common to all child alerts in this group.",
        },
        "label_values": {
            "type": "object",
            "nullable": True,
            "additionalProperties": True,
            "description": "Collected label values across child alerts.",
        },
        "payload_summary": {
            "type": "object",
            "nullable": True,
            "additionalProperties": True,
        },
        "alert_count": {"type": "integer"},
        "firing_count": {"type": "integer"},
        "acknowledged_count": {"type": "integer"},
        "resolved_count": {"type": "integer"},
        "silenced_count": {"type": "integer"},
        "assignee": {"type": "string", "nullable": True},
        "assignee_id": {"type": "integer", "nullable": True},
        "assignee_details": user_short_schema(),
        "acknowledged_by": {"type": "string", "nullable": True},
        "acknowledged_by_details": user_short_schema(),
        "acknowledged_at": date_time_property(
            "Alert group acknowledgement timestamp in UTC.",
            nullable=True,
        ),
        "resolved_by": {"type": "string", "nullable": True},
        "resolved_at": date_time_property(
            "Time when this alert group was resolved in UTC.",
            nullable=True,
        ),
        "first_seen_at": date_time_property(
            "First time any child alert in this group was seen in UTC.",
        ),
        "last_seen_at": date_time_property(
            "Last time any child alert in this group was seen in UTC.",
        ),
        "last_notification_at": date_time_property(
            "Last notification timestamp in UTC.",
            nullable=True,
        ),
        "notification_due_at": date_time_property(
            "Pending notification due timestamp in UTC.",
            nullable=True,
        ),
        "notification_pending": {"type": "boolean"},
        "notification_reason": {"type": "string", "nullable": True},
        "reminder_count": {"type": "integer"},
        "escalation_level": {"type": "integer"},
        "correlation_summary": alert_correlation_summary_schema(),
        "business_impact_summary": alert_group_business_impact_summary_schema(),
        "merged_into_id": {"type": "integer", "nullable": True},
        "merged_at": date_time_property(
            "Timestamp when this group was merged into another group.",
            nullable=True,
        ),
        "merge_reason": {"type": "string", "nullable": True},
        "created_at": date_time_property("Group creation timestamp in UTC."),
        "updated_at": date_time_property("Group update timestamp in UTC."),
    }

    if include_details:
        properties["alerts"] = {
            "type": "array",
            "items": alert_child_schema(include_payload=True),
        }
        properties["events"] = {
            "type": "array",
            "items": alert_event_schema(),
        }
        properties["notifications"] = {
            "type": "array",
            "items": alert_notification_schema(),
        }
        properties["correlations"] = alert_group_correlations_schema()
        properties["business_impacts"] = {
            "type": "array",
            "items": BUSINESS_SERVICE_IMPACT_SCHEMA,
        }

    return {
        "type": "object",
        "properties": properties,
    }


def alert_list_schema():
    """Build list alert groups response schema."""

    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": alert_group_schema(),
            },
            "pagination": {
                "type": "object",
                "additionalProperties": True,
            },
            "summary": {
                "type": "object",
                "additionalProperties": True,
            },
            "sort": {
                "type": "object",
                "additionalProperties": True,
            },
        },
    }


def alert_group_merge_request_schema():
    """Build alert group merge request schema."""

    return {
        "type": "object",
        "required": ["target_group_id", "source_group_ids"],
        "properties": {
            "target_group_id": {
                "type": "integer",
                "minimum": 1,
                "description": "Target alert group id. This group remains visible after merge.",
            },
            "source_group_ids": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "integer", "minimum": 1},
                "description": "Source group ids. Their child alerts are moved into the target group.",
            },
            "reason": {
                "type": "string",
                "nullable": True,
                "description": "Optional human-readable merge reason.",
            },
        },
    }


def alert_comment_user_schema():
    """Build compact alert comment author schema."""
    return {
        "type": "object",
        "nullable": True,
        "properties": {
            "id": {"type": "integer", "readOnly": True, "example": 7},
            "username": {"type": "string", "nullable": True, "example": "alice"},
            "display_name": {"type": "string", "nullable": True, "example": "Alice"},
            "email": {
                "type": "string",
                "format": "email",
                "nullable": True,
                "example": "alice@example.com",
            },
        },
    }


def alert_comment_schema():
    """Build alert comment response schema."""
    return {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "readOnly": True, "example": 42},
            "group_id": {
                "type": "integer",
                "nullable": True,
                "description": "Alert group id.",
                "example": 1001,
            },
            "alert_id": {
                "type": "integer",
                "nullable": True,
                "description": "Concrete child alert id when the comment is attached to a child alert.",
                "example": None,
            },
            "user_id": {
                "type": "integer",
                "nullable": True,
                "description": "Author user id.",
                "example": 7,
            },
            "user": alert_comment_user_schema(),
            "body": {
                "type": "string",
                "description": "Comment text.",
                "minLength": 1,
                "maxLength": 5000,
                "example": "Investigating disk usage on host1.",
            },
            "created_at": date_time_property("Comment creation timestamp in UTC."),
            "updated_at": date_time_property("Last comment update timestamp in UTC."),
            "edited": {
                "type": "boolean",
                "description": "True when updated_at is later than created_at.",
                "example": False,
            },
        },
    }




def alert_comment_create_request_schema():
    """Build alert comment create request schema."""
    return {
        "type": "object",
        "required": ["body"],
        "properties": {
            "body": {
                "type": "string",
                "minLength": 1,
                "maxLength": 5000,
                "description": "Comment body. Leading and trailing whitespace is trimmed.",
            },
        },
    }


def alert_comment_update_request_schema():
    """Build alert comment update request schema."""
    return {
        "type": "object",
        "required": ["body"],
        "properties": {
            "body": {
                "type": "string",
                "minLength": 1,
                "maxLength": 5000,
                "description": "Updated comment body. Leading and trailing whitespace is trimmed.",
            },
        },
    }


def delete_alert_comment_response_schema():
    """Build delete alert comment response schema."""
    return {
        "type": "object",
        "properties": {
            "deleted": {"type": "boolean"},
            "id": {"type": "integer"},
        },
    }


def tags():
    """Return OpenAPI tags."""

    return [
        {
            "name": "alerts",
            "description": (
                "Alert group lifecycle endpoints. /api/alerts returns incident-level "
                "alert groups. Each group contains one or more child alerts."
            ),
        }
    ]


def bearer_security():
    """Return bearer auth security requirement."""

    return [{"bearerAuth": []}]


def paths():
    """Return OpenAPI paths for alert group endpoints."""

    status_schema = {
        "type": "string",
        "enum": ["firing", "acknowledged", "resolved", "silenced", "merged"],
    }

    severity_schema = {"type": "string"}

    return {
        "/api/alerts": {
            "get": {
                "tags": ["alerts"],
                "summary": "List alert groups",
                "description": (
                    "Returns alert groups with optional filtering and sorting. "
                    "The URL is kept as /api/alerts for compatibility, but each item is an alert group. "
                    "Use repeated query parameters for multi-value filters, for example "
                    "?status=firing&status=acknowledged."
                ),
                "operationId": "listAlertGroups",
                "security": bearer_security(),
                "parameters": [
                    query_param(
                        "team_id",
                        "Filter alert groups by team id.",
                        {"type": "integer", "minimum": 1},
                    ),
                    query_array_param(
                        "status",
                        "Filter by one or more group statuses.",
                        status_schema,
                    ),
                    query_array_param(
                        "severity",
                        "Filter by one or more severities.",
                        severity_schema,
                    ),
                    query_array_param(
                        "service_id",
                        "Filter by one or more service ids.",
                        {"type": "integer", "minimum": 1},
                    ),
                    query_param(
                        "source",
                        "Filter by source: alertmanager, zabbix or webhook.",
                    ),
                    query_param("service_slug", "Filter by service slug."),
                    query_param("service_status", "Filter by service status."),
                    query_param("service_criticality", "Filter by service criticality."),
                    query_param(
                        "include_merged",
                        "Set to 1 to include groups marked as merged.",
                        {"type": "string", "enum": ["0", "1"], "default": "0"},
                    ),
                    query_param(
                        "sort",
                        "Sort field.",
                        {
                            "type": "string",
                            "enum": [
                                "id",
                                "status",
                                "title",
                                "severity",
                                "team",
                                "assignee",
                                "created",
                                "last_seen",
                                "activity",
                                "reminders",
                            ],
                            "default": "activity",
                        },
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
                        "search",
                        "Search by id, title, team, assignee, source, route, rotation or group fields.",
                    ),
                    query_param(
                        "page",
                        "Page number.",
                        {"type": "integer", "minimum": 1, "default": 1},
                    ),
                    query_param(
                        "page_size",
                        "Rows per page. Maximum value is 100.",
                        {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 25,
                        },
                    ),
                ],
                "responses": {
                    "200": response("List of alert groups.", alert_list_schema()),
                    "401": response("Authentication required."),
                    "403": response("Access denied."),
                },
            }
        },
        "/api/alerts/merge": {
            "post": {
                "tags": ["alerts"],
                "summary": "Merge alert groups",
                "description": (
                    "Moves child alerts from source groups into the target group. "
                    "Source groups are marked as merged. The response is the recalculated target group."
                ),
                "operationId": "mergeAlertGroups",
                "security": bearer_security(),
                "requestBody": json_body(
                    "Merge target and source alert groups.",
                    alert_group_merge_request_schema(),
                ),
                "responses": {
                    "200": response("Merged target alert group.", alert_group_schema(include_details=True)),
                    "400": response("Invalid merge request."),
                    "401": response("Authentication required."),
                    "403": response("Access denied."),
                    "404": response("Alert group not found."),
                },
            }
        },
        "/api/alerts/{alert_id}": {
            "get": {
                "tags": ["alerts"],
                "summary": "Get alert group",
                "description": (
                    "Returns a single alert group with child alerts, group-level events and "
                    "notification delivery records. The path parameter is named alert_id for "
                    "backwards compatibility, but it is an alert group id."
                ),
                "operationId": "getAlertGroup",
                "security": bearer_security(),
                "parameters": [
                    path_param("alert_id", "Alert group id."),
                ],
                "responses": {
                    "200": response(
                        "Alert group details.",
                        alert_group_schema(include_details=True),
                    ),
                    "401": response("Authentication required."),
                    "403": response("Access denied."),
                    "404": response("Alert group not found."),
                },
            }
        },
        "/api/alerts/{alert_id}/explain": {
            "get": {
                "tags": ["alerts"],
                "summary": "List alert explain traces",
                "description": (
                    "Returns explain traces linked to an alert group. "
                    "The alert_id path parameter is the alert group id used by the alert details endpoint."
                ),
                "operationId": "listAlertExplainTraces",
                "security": bearer_security(),
                "parameters": [
                    path_param("alert_id", "Alert group id."),
                ],
                "responses": {
                    "200": response(
                        "List of explain traces linked to the alert group.",
                        {
                            "type": "array",
                            "items": alert_explain_trace_schema(
                                include_steps=False,
                            ),
                        },
                    ),
                    "401": response("Authentication required."),
                    "403": response("Access denied."),
                    "404": response("Alert group not found."),
                },
            },
        },

        "/api/alerts/explain/{trace_id}": {
            "get": {
                "tags": ["alerts"],
                "summary": "Get alert explain trace",
                "description": (
                    "Returns one explain trace with ordered processing steps. "
                    "Traces linked to an alert group use alert group read access checks. "
                    "Orphan traces without group_id can be read only by administrators."
                ),
                "operationId": "getAlertExplainTrace",
                "security": bearer_security(),
                "parameters": [
                    string_path_param(
                        "trace_id",
                        "Explain trace id returned by an integration ingest response.",
                    ),
                ],
                "responses": {
                    "200": response(
                        "Explain trace with ordered processing steps.",
                        alert_explain_trace_schema(include_steps=True),
                    ),
                    "401": response("Authentication required."),
                    "403": response("Access denied."),
                    "404": response("Alert explain trace not found."),
                },
            },
        },
        "/api/alerts/{alert_id}/ack": {
            "post": {
                "tags": ["alerts"],
                "summary": "Acknowledge alert group",
                "description": (
                    "Marks an alert group as acknowledged. Child alerts are not individually "
                    "acknowledged. If a new child alert arrives later, the group is reopened as firing."
                ),
                "operationId": "acknowledgeAlertGroup",
                "security": bearer_security(),
                "parameters": [
                    path_param("alert_id", "Alert group id."),
                ],
                "requestBody": json_body(
                    "Optional acknowledge user.",
                    {
                        "type": "object",
                        "properties": {
                            "user_id": {
                                "type": "integer",
                                "minimum": 1,
                                "nullable": True,
                            },
                        },
                    },
                    required=False,
                ),
                "responses": {
                    "200": response("Alert group acknowledged.", alert_group_schema()),
                    "401": response("Authentication required."),
                    "403": response("Access denied."),
                    "404": response("Alert group not found."),
                },
            }
        },
        "/api/alerts/{alert_id}/resolve": {
            "post": {
                "tags": ["alerts"],
                "summary": "Resolve alert group",
                "description": (
                    "Marks an alert group as resolved and resolves all child alerts in the group. "
                    "If the group was already notified, a resolved notification is sent."
                ),
                "operationId": "resolveAlertGroup",
                "security": bearer_security(),
                "parameters": [
                    path_param("alert_id", "Alert group id."),
                ],
                "requestBody": json_body(
                    "Optional resolve user.",
                    {
                        "type": "object",
                        "properties": {
                            "user_id": {
                                "type": "integer",
                                "minimum": 1,
                                "nullable": True,
                            },
                        },
                    },
                    required=False,
                ),
                "responses": {
                    "200": response("Alert group resolved.", alert_group_schema()),
                    "401": response("Authentication required."),
                    "403": response("Access denied."),
                    "404": response("Alert group not found."),
                },
            }
        },
        "/api/alerts/{alert_id}/events": {
            "get": {
                "tags": ["alerts"],
                "summary": "List alert group events",
                "description": (
                    "Returns group-level events and child-alert events for an alert group. "
                    "This is the main debug endpoint for notifications, reminders, escalations and merge history."
                ),
                "operationId": "listAlertGroupEvents",
                "security": bearer_security(),
                "parameters": [
                    path_param("alert_id", "Alert group id."),
                ],
                "responses": {
                    "200": response(
                        "Alert group event history.",
                        {
                            "type": "array",
                            "items": alert_event_schema(),
                        },
                    ),
                    "401": response("Authentication required."),
                    "403": response("Access denied."),
                    "404": response("Alert group not found."),
                },
            }
        },
        "/api/alerts/{alert_id}/comments": {
            "get": {
                "tags": ["alerts"],
                "summary": "List alert group comments",
                "description": (
                    "Returns non-deleted human comments attached to an alert group. "
                    "The path parameter is named alert_id for backwards compatibility, "
                    "but it is an alert group id."
                ),
                "operationId": "listAlertGroupComments",
                "security": bearer_security(),
                "parameters": [
                    path_param("alert_id", "Alert group id."),
                ],
                "responses": {
                    "200": response(
                        "Alert group comments.",
                        {
                            "type": "array",
                            "items": alert_comment_schema(),
                        },
                    ),
                    "401": response("Authentication required."),
                    "403": response("Access denied."),
                    "404": response("Alert group not found."),
                },
            },
            "post": {
                "tags": ["alerts"],
                "summary": "Create alert group comment",
                "description": (
                    "Creates a human comment attached to an alert group and records "
                    "a comment event in the alert timeline."
                ),
                "operationId": "createAlertGroupComment",
                "security": bearer_security(),
                "parameters": [
                    path_param("alert_id", "Alert group id."),
                ],
                "requestBody": json_body(
                    "Comment payload.",
                    alert_comment_create_request_schema(),
                ),
                "responses": {
                    "201": response(
                        "Created alert group comment.",
                        alert_comment_schema(),
                    ),
                    "400": response("Invalid comment payload."),
                    "401": response("Authentication required."),
                    "403": response("Access denied."),
                    "404": response("Alert group not found."),
                },
            },
        },
        "/api/alerts/{alert_id}/comments/{comment_id}": {
            "put": {
                "tags": ["alerts"],
                "summary": "Update alert group comment",
                "description": (
                    "Updates an existing non-deleted comment attached to an alert group "
                    "and records a comment update event in the alert timeline."
                ),
                "operationId": "updateAlertGroupComment",
                "security": bearer_security(),
                "parameters": [
                    path_param("alert_id", "Alert group id."),
                    path_param("comment_id", "Comment id."),
                ],
                "requestBody": json_body(
                    "Updated comment payload.",
                    alert_comment_update_request_schema(),
                ),
                "responses": {
                    "200": response(
                        "Updated alert group comment.",
                        alert_comment_schema(),
                    ),
                    "400": response("Invalid comment payload."),
                    "401": response("Authentication required."),
                    "403": response("Access denied."),
                    "404": response("Alert group or comment not found."),
                },
            },
            "delete": {
                "tags": ["alerts"],
                "summary": "Delete alert group comment",
                "description": (
                    "Soft-deletes a comment attached to an alert group and records "
                    "a comment deletion event in the alert timeline."
                ),
                "operationId": "deleteAlertGroupComment",
                "security": bearer_security(),
                "parameters": [
                    path_param("alert_id", "Alert group id."),
                    path_param("comment_id", "Comment id."),
                ],
                "responses": {
                    "200": response(
                        "Deleted alert group comment.",
                        delete_alert_comment_response_schema(),
                    ),
                    "401": response("Authentication required."),
                    "403": response("Access denied."),
                    "404": response("Alert group or comment not found."),
                },
            },
        },
    }
