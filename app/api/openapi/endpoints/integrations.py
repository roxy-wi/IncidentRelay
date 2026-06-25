def path_param(name, description):
    """
    Build an integer path parameter.
    """

    return {
        "name": name,
        "in": "path",
        "required": True,
        "description": description,
        "schema": {"type": "integer", "minimum": 1},
    }


def query_param(name, description, schema=None, required=False):
    """
    Build a query parameter.
    """

    return {
        "name": name,
        "in": "query",
        "required": required,
        "description": description,
        "schema": schema or {"type": "string"},
    }


def json_body(description, schema, required=True):
    """
    Build a JSON request body.
    """

    return {
        "required": required,
        "description": description,
        "content": {
            "application/json": {
                "schema": schema
            }
        },
    }


def response(description, schema=None):
    """
    Build a JSON response.
    """

    item = {"description": description}

    if schema:
        item["content"] = {
            "application/json": {
                "schema": schema
            }
        }

    return item


def header_param(name, description, schema=None, required=False):
    """Build a header parameter."""
    return {
        "name": name,
        "in": "header",
        "required": required,
        "description": description,
        "schema": schema or {"type": "string"},
    }


ALERT_PROCESSING_RESULT_SCHEMA = {
    "type": "object",
    "description": "Result of processing one normalized incoming alert.",
    "properties": {
        "created": {
            "type": "boolean",
            "description": "True when a new alert group was created.",
            "example": True,
        },
        "id": {
            "type": "integer",
            "nullable": True,
            "description": "Alert group id. Kept for backward compatibility.",
            "example": 123,
        },
        "group_id": {
            "type": "integer",
            "nullable": True,
            "description": "Alert group id when an alert group exists.",
            "example": 123,
        },
        "alert_id": {
            "type": "integer",
            "nullable": True,
            "description": "Child alert id when an alert exists.",
            "example": 456,
        },
        "status": {
            "type": "string",
            "nullable": True,
            "description": "Resulting alert group or alert status.",
            "example": "firing",
        },
        "outcome": {
            "type": "string",
            "description": "Alert processing outcome.",
            "enum": [
                "created",
                "updated",
                "resolved",
                "routing_failed",
                "suppressed",
                "orphan_resolved_ignored",
                "failed",
            ],
            "example": "created",
        },
        "processing_status": {
            "type": "string",
            "description": "High-level processing status.",
            "enum": [
                "completed",
                "stopped",
                "failed",
            ],
            "example": "completed",
        },
        "reason": {
            "type": "string",
            "nullable": True,
            "description": "Reason for stopped or failed processing.",
            "example": "Alert did not match any active route.",
        },
        "trace_id": {
            "type": "string",
            "nullable": True,
            "description": (
                "Explain trace id. Use GET /api/alerts/explain/{trace_id} "
                "to inspect routing and processing steps."
            ),
            "example": "4fd2a8c9-8c2f-44e8-96fd-77b7f03e72f2",
        },
        "routing_error": {
            "type": "string",
            "nullable": True,
            "description": "Routing error alias for routing_failed responses.",
            "example": "Alert did not match any active route.",
        },
        "team_id": {
            "type": "integer",
            "nullable": True,
            "description": "Matched team id.",
        },
        "team_slug": {
            "type": "string",
            "nullable": True,
            "description": "Matched team slug.",
        },
        "route_id": {
            "type": "integer",
            "nullable": True,
            "description": "Matched route id.",
        },
        "rotation_id": {
            "type": "integer",
            "nullable": True,
            "description": "Resolved rotation id.",
        },
        "assignee": {
            "type": "string",
            "nullable": True,
            "description": "Assigned username, when available.",
        },
    },
    "additionalProperties": True,
}


ALERT_PROCESSING_RESULT_LIST_SCHEMA = {
    "type": "array",
    "items": ALERT_PROCESSING_RESULT_SCHEMA,
}


def incoming_alert_responses(success_description="Alerts accepted."):
    """Build standard incoming alert processing responses."""
    return {
        "200": response(
            success_description,
            ALERT_PROCESSING_RESULT_LIST_SCHEMA,
        ),
        "202": response(
            "Alerts processed, but no alert group was created.",
            ALERT_PROCESSING_RESULT_LIST_SCHEMA,
        ),
        "207": response(
            "Batch contains both accepted and failed alerts.",
            ALERT_PROCESSING_RESULT_LIST_SCHEMA,
        ),
        "400": response(
            "Invalid payload or all alerts failed routing.",
        ),
        "401": response("Route intake token or API token is required."),
    }


SENTRY_WEBHOOK_BODY_SCHEMA = {
    "type": "object",
    "description": (
        "Sentry Internal Integration webhook payload. "
        "The payload structure depends on Sentry-Hook-Resource and action. "
        "IncidentRelay accepts event_alert, metric_alert and issue lifecycle events."
    ),
    "additionalProperties": True,
    "properties": {
        "action": {
            "type": "string",
            "description": "Sentry webhook action.",
            "example": "triggered",
        },
        "actor": {
            "type": "object",
            "nullable": True,
            "additionalProperties": True,
            "description": "Sentry actor that caused the event, when present.",
        },
        "installation": {
            "type": "object",
            "nullable": True,
            "additionalProperties": True,
            "description": "Sentry integration installation object, when present.",
        },
        "data": {
            "type": "object",
            "additionalProperties": True,
            "description": (
                "Sentry event data. For issue alert rules this usually contains "
                "event_alert, issue, event, project and organization. For metric "
                "alerts it contains metric_alert. For issue lifecycle events it "
                "contains issue."
            ),
            "properties": {
                "event_alert": {
                    "type": "object",
                    "nullable": True,
                    "additionalProperties": True,
                    "description": "Sentry issue alert rule object.",
                },
                "metric_alert": {
                    "type": "object",
                    "nullable": True,
                    "additionalProperties": True,
                    "description": "Sentry metric alert object.",
                },
                "issue": {
                    "type": "object",
                    "nullable": True,
                    "additionalProperties": True,
                    "description": "Sentry issue/group object.",
                },
                "event": {
                    "type": "object",
                    "nullable": True,
                    "additionalProperties": True,
                    "description": "Sentry event object.",
                },
                "project": {
                    "type": "object",
                    "nullable": True,
                    "additionalProperties": True,
                    "description": "Sentry project object.",
                },
                "organization": {
                    "type": "object",
                    "nullable": True,
                    "additionalProperties": True,
                    "description": "Sentry organization object.",
                },
            },
        },
    },
    "example": {
        "action": "triggered",
        "data": {
            "event_alert": {"id": "event-rule-1", "name": "New issue alert"},
            "issue": {
                "id": "12345",
                "shortId": "BACKEND-1",
                "title": "ZeroDivisionError",
                "level": "error",
                "permalink": "https://sentry.example.com/issues/12345/",
            },
            "event": {
                "event_id": "event-abc",
                "environment": "production",
                "message": "division by zero",
            },
            "project": {"id": 42, "slug": "backend-api", "name": "Backend API"},
            "organization": {"slug": "acme", "name": "Acme"},
        },
    },
}


SENTRY_WEBHOOK_RESPONSE_SCHEMA = ALERT_PROCESSING_RESULT_LIST_SCHEMA

SENTRY_WEBHOOK_PATH_ITEM = {
    "post": {
        "tags": ["integrations"],
        "summary": "Receive Sentry webhook",
        "description": (
            "Receives signed webhooks from a Sentry Internal Integration. "
            "The route id in the URL selects an IncidentRelay route with source=sentry. "
            "The request is authenticated by Sentry-Hook-Signature using the "
            "Sentry Client Secret stored in route integration_config. "
            "This endpoint does not use IncidentRelay bearer intake tokens."
        ),
        "operationId": "receiveSentryWebhook",
        "parameters": [
            path_param("route_id", "Sentry IncidentRelay route id."),
            header_param(
                "Sentry-Hook-Signature",
                "HMAC-SHA256 signature generated by Sentry using the Internal Integration Client Secret.",
                {"type": "string", "minLength": 1},
                required=True,
            ),
            header_param(
                "Sentry-Hook-Resource",
                "Sentry resource name. IncidentRelay uses this to normalize event_alert, metric_alert and issue events.",
                {
                    "type": "string",
                    "enum": ["event_alert", "metric_alert", "issue"],
                },
                required=False,
            ),
        ],
        "requestBody": json_body(
            "Sentry Internal Integration webhook payload.",
            SENTRY_WEBHOOK_BODY_SCHEMA,
        ),
        "responses": {
            "200": response("Sentry webhook accepted.", SENTRY_WEBHOOK_RESPONSE_SCHEMA),
            "400": response("Invalid payload or route source mismatch."),
            "403": response("Missing or invalid Sentry-Hook-Signature, disabled route, or inactive team/group."),
            "404": response("Sentry route was not found."),
            "409": response("Sentry webhook secret is not configured for this route."),
        },
    }
}

VOICE_CALLBACK_BODY_SCHEMA = {
    "type": "object",
    "description": (
        "Provider-specific voice callback payload. "
        "IncidentRelay passes this payload to the selected voice provider module. "
        "The provider normalizes it into status, DTMF or error events."
    ),
    "additionalProperties": True,
    "properties": {
        "call_id": {
            "type": "string",
            "description": "External provider call id.",
            "example": "abc-123",
        },
        "event": {
            "type": "string",
            "description": "Provider event name.",
            "example": "dtmf",
        },
        "event_type": {
            "type": "string",
            "description": "Normalized or provider-specific event type.",
            "enum": ["status", "dtmf", "error"],
            "example": "dtmf",
        },
        "status": {
            "type": "string",
            "description": "Provider call status.",
            "example": "answered",
        },
        "digit": {
            "type": "string",
            "description": "DTMF digit pressed by the call recipient.",
            "example": "1",
        },
        "action": {
            "type": "string",
            "description": (
                "Optional normalized action. "
                "If omitted, IncidentRelay maps digit through channel config dtmf_actions."
            ),
            "enum": ["acknowledge", "resolve"],
            "example": "acknowledge",
        },
        "alert_id": {
            "type": "integer",
            "nullable": True,
            "description": "Optional alert id returned by the provider.",
            "example": 123,
        },
        "message": {
            "type": "string",
            "nullable": True,
            "description": "Optional provider event message.",
            "example": "User pressed 1",
        },
    },
    "example": {
        "call_id": "abc-123",
        "event_type": "dtmf",
        "status": "answered",
        "digit": "1",
    },
}


VOICE_CALLBACK_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "example": "processed",
        },
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "call_id": {
                        "type": "string",
                        "example": "abc-123",
                    },
                    "event_type": {
                        "type": "string",
                        "example": "dtmf",
                    },
                    "status": {
                        "type": "string",
                        "nullable": True,
                        "example": "answered",
                    },
                    "digit": {
                        "type": "string",
                        "nullable": True,
                        "example": "1",
                    },
                    "action": {
                        "type": "string",
                        "nullable": True,
                        "example": "acknowledge",
                    },
                    "alert_id": {
                        "type": "integer",
                        "nullable": True,
                        "example": 123,
                    },
                },
            },
        },
    },
}

SLACK_ACTION_FORM_SCHEMA = {
    "type": "object",
    "required": ["payload"],
    "properties": {
        "payload": {
            "type": "string",
            "description": (
                "JSON-encoded Slack Block Kit interaction payload. "
                "Slack sends this field using "
                "application/x-www-form-urlencoded."
            ),
            "example": (
                '{"type":"block_actions",'
                '"user":{"id":"U0123456789"},'
                '"channel":{"id":"C0123456789"},'
                '"actions":[{'
                '"action_id":"incidentrelay_acknowledge",'
                '"value":"{\\"action\\":\\"acknowledge\\",'
                '\\"alert_id\\":123,'
                '\\"channel_id\\":12}"'
                "}]}",
            ),
        },
    },
    "additionalProperties": True,
}


SLACK_ACTION_RESPONSE_SCHEMA = {
    "type": "object",
    "required": [
        "ok",
        "action",
        "alert_id",
        "user_id",
    ],
    "properties": {
        "ok": {
            "type": "boolean",
            "description": "Whether the Slack action was processed.",
            "example": True,
        },
        "action": {
            "type": "string",
            "enum": [
                "acknowledge",
                "resolve",
            ],
            "description": "Alert action performed by IncidentRelay.",
            "example": "acknowledge",
        },
        "alert_id": {
            "type": "integer",
            "description": "IncidentRelay alert group ID.",
            "example": 123,
        },
        "user_id": {
            "type": "integer",
            "nullable": True,
            "description": (
                "IncidentRelay user matched by Slack user ID. "
                "Null when the Slack user is not linked."
            ),
            "example": 7,
        },
    },
    "additionalProperties": False,
}


SLACK_ACTION_ERROR_SCHEMA = {
    "type": "object",
    "required": [
        "error",
        "message",
    ],
    "properties": {
        "error": {
            "type": "string",
            "enum": [
                "invalid_payload",
                "invalid_action",
                "invalid_signature",
                "stale_request",
                "action_rejected",
                "alert_not_found",
            ],
            "description": "Machine-readable Slack action error.",
            "example": "invalid_signature",
        },
        "message": {
            "type": "string",
            "description": "Human-readable error description.",
            "example": "Slack request signature is invalid.",
        },
    },
    "additionalProperties": False,
}

librenms_body = {
    "type": "object",
    "description": (
        "LibreNMS API transport payload. Configure LibreNMS to send JSON "
        "using alert template variables such as id, uid, state, severity, "
        "title, msg, hostname and device_id."
    ),
    "additionalProperties": True,
    "properties": {
        "id": {
            "type": "string",
            "nullable": True,
            "description": "LibreNMS alert id.",
            "example": "12345",
        },
        "uid": {
            "type": "string",
            "nullable": True,
            "description": "LibreNMS unique alert uid. Prefer this as stable external id.",
            "example": "lnms-alert-12345",
        },
        "alert_id": {
            "type": "string",
            "nullable": True,
            "description": "Alternative alert id field.",
            "example": "12345",
        },
        "alert_uid": {
            "type": "string",
            "nullable": True,
            "description": "Alternative alert uid field.",
            "example": "lnms-alert-12345",
        },
        "external_id": {
            "type": "string",
            "nullable": True,
            "description": (
                "Stable LibreNMS alert identifier used by IncidentRelay for "
                "deduplication. Must be the same for firing and recovery events."
            ),
            "example": "12345",
        },
        "state": {
            "oneOf": [
                {"type": "string"},
                {"type": "integer"},
            ],
            "nullable": True,
            "description": (
                "LibreNMS alert state. 0/ok/clear/recovered/resolved are "
                "normalized as resolved, other values are normalized as firing."
            ),
            "example": "1",
        },
        "status": {
            "type": "string",
            "nullable": True,
            "description": "Alternative status/state field.",
            "example": "firing",
        },
        "severity": {
            "type": "string",
            "nullable": True,
            "description": "LibreNMS severity.",
            "example": "critical",
        },
        "title": {
            "type": "string",
            "nullable": True,
            "description": "Alert title.",
            "example": "Device down",
        },
        "subject": {
            "type": "string",
            "nullable": True,
            "description": "Alternative alert title.",
            "example": "Device down",
        },
        "name": {
            "type": "string",
            "nullable": True,
            "description": "LibreNMS alert rule name.",
            "example": "Device down",
        },
        "rule": {
            "type": "string",
            "nullable": True,
            "description": "Alternative alert rule name.",
            "example": "Device down",
        },
        "message": {
            "type": "string",
            "nullable": True,
            "description": "Alert message.",
            "example": "Device router1 is unreachable",
        },
        "msg": {
            "type": "string",
            "nullable": True,
            "description": "LibreNMS alert message variable.",
            "example": "Device router1 is unreachable",
        },
        "description": {
            "type": "string",
            "nullable": True,
            "description": "Alternative alert description.",
            "example": "Device router1 is unreachable",
        },
        "alert_notes": {
            "type": "string",
            "nullable": True,
            "description": "LibreNMS alert notes.",
            "example": "Check uplink and power.",
        },
        "hostname": {
            "type": "string",
            "nullable": True,
            "description": "Device hostname.",
            "example": "router1",
        },
        "display": {
            "type": "string",
            "nullable": True,
            "description": "Device display name.",
            "example": "router1",
        },
        "sysName": {
            "type": "string",
            "nullable": True,
            "description": "Device sysName.",
            "example": "router1.example.com",
        },
        "device_id": {
            "oneOf": [
                {"type": "string"},
                {"type": "integer"},
            ],
            "nullable": True,
            "description": "LibreNMS device id.",
            "example": "77",
        },
        "ip": {
            "type": "string",
            "nullable": True,
            "description": "Device IP address.",
            "example": "10.0.0.1",
        },
        "os": {
            "type": "string",
            "nullable": True,
            "description": "Device OS.",
            "example": "linux",
        },
        "type": {
            "type": "string",
            "nullable": True,
            "description": "Device type.",
            "example": "network",
        },
        "hardware": {
            "type": "string",
            "nullable": True,
            "description": "Device hardware.",
            "example": "Cisco IOS",
        },
        "version": {
            "type": "string",
            "nullable": True,
            "description": "Device OS or hardware version.",
            "example": "17.9",
        },
        "location": {
            "type": "string",
            "nullable": True,
            "description": "Device location.",
            "example": "DC1",
        },
        "timestamp": {
            "type": "string",
            "nullable": True,
            "description": "LibreNMS alert timestamp.",
            "example": "2026-06-17 10:00:00",
        },
        "elapsed": {
            "type": "string",
            "nullable": True,
            "description": "Alert elapsed time.",
            "example": "5m",
        },
        "proc": {
            "type": "string",
            "nullable": True,
            "description": "LibreNMS procedure or source link when available.",
        },
        "team": {
            "type": "string",
            "nullable": True,
            "description": "Optional IncidentRelay team slug override.",
            "example": "sre",
        },
        "fingerprint": {
            "type": "string",
            "nullable": True,
            "description": "Optional explicit IncidentRelay dedup key.",
            "example": "librenms-router1-device-down",
        },
        "event_link": {
            "type": "string",
            "nullable": True,
            "description": "External alert URL.",
            "example": "https://librenms.example.com/alerts",
        },
        "event_url": {
            "type": "string",
            "nullable": True,
            "description": "Alternative external alert URL.",
        },
        "alert_url": {
            "type": "string",
            "nullable": True,
            "description": "Alternative external alert URL.",
        },
        "source_url": {
            "type": "string",
            "nullable": True,
            "description": "Alternative external source URL.",
        },
        "device_url": {
            "type": "string",
            "nullable": True,
            "description": "LibreNMS device URL.",
        },
        "librenms_url": {
            "type": "string",
            "nullable": True,
            "description": (
                "LibreNMS base URL. IncidentRelay can build a device link "
                "from this plus hostname/device_id."
            ),
            "example": "https://librenms.example.com",
        },
        "labels": {
            "type": "object",
            "additionalProperties": True,
            "description": "Additional labels copied to the normalized alert.",
            "example": {
                "environment": "prod",
                "service": "network",
            },
        },
        "faults": {
            "description": "LibreNMS faults payload, if included by the transport.",
            "nullable": True,
        },
        "contacts": {
            "description": "LibreNMS contacts payload, if included by the transport.",
            "nullable": True,
        },
        "applications": {
            "description": "LibreNMS applications payload, if included by the transport.",
            "nullable": True,
        },
    },
    "example": {
        "id": "12345",
        "uid": "lnms-alert-12345",
        "state": "1",
        "severity": "critical",
        "title": "Device down",
        "message": "Device router1 is unreachable",
        "hostname": "router1",
        "device_id": "77",
        "ip": "10.0.0.1",
        "rule": "Device down",
        "timestamp": "2026-06-17 10:00:00",
        "team": "sre",
        "librenms_url": "https://librenms.example.com",
    },
}


def tags():
    """Return OpenAPI tags."""
    return [
        {
            "name": "integrations",
            "description": (
                "Incoming alert endpoints for Alertmanager, Grafana, RMON, "
                "Amazon SNS and CloudWatch, Zabbix, LibreNMS, generic webhooks "
                "and Sentry. Alertmanager, Grafana, RMON, Zabbix, LibreNMS "
                "and generic webhooks use route intake tokens. Sentry uses a "
                "route-specific webhook signature. Amazon SNS requests are "
                "verified using the SNS signature and the exact Topic ARN "
                "configured for the route."
            ),
        },
    ]


def paths():
    """
    Return OpenAPI paths for integration endpoints.
    """

    alertmanager_alert_schema = {
        "type": "object",
        "required": ["labels"],
        "additionalProperties": True,
        "properties": {
            "status": {
                "type": "string",
                "enum": ["firing", "resolved"],
                "default": "firing",
                "description": "Alert status from Alertmanager.",
            },
            "labels": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Alert labels.",
                "example": {
                    "alertname": "TargetMissingOrDown",
                    "instance": "10.101.164.165:9290",
                    "severity": "critical",
                    "team": "infra",
                },
            },
            "annotations": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Alert annotations.",
                "example": {
                    "summary": "Target missing or down",
                    "description": "Target 10.101.164.165:9290 is not available",
                },
            },
            "startsAt": {
                "type": "string",
                "format": "date-time",
                "nullable": True,
                "description": "Alert start time.",
            },
            "endsAt": {
                "type": "string",
                "format": "date-time",
                "nullable": True,
                "description": "Alert end time.",
            },
            "generatorURL": {
                "type": "string",
                "nullable": True,
                "description": "URL to the source that generated the alert.",
            },
            "fingerprint": {
                "type": "string",
                "nullable": True,
                "description": "Alertmanager alert fingerprint. Used for deduplication when available.",
                "example": "target-missing-10.101.164.165",
            },
            "silenceURL": {
                "type": "string",
                "nullable": True,
                "description": "Alertmanager silence URL.",
                "example": "https://alertmanager.example.com/#/silences/new",
            },
            "dashboardURL": {
                "type": "string",
                "nullable": True,
                "description": "Dashboard URL related to this alert.",
                "example": "https://grafana.example.com/d/node",
            },
            "panelURL": {
                "type": "string",
                "nullable": True,
                "description": "Panel URL related to this alert.",
                "example": "https://grafana.example.com/d/node?viewPanel=12",
            },
        },
    }

    alertmanager_body = {
        "type": "object",
        "required": ["alerts"],
        "additionalProperties": True,
        "properties": {
            "receiver": {
                "type": "string",
                "nullable": True,
                "description": "Alertmanager receiver name.",
                "example": "incidentrelay-infra",
            },
            "status": {
                "type": "string",
                "enum": ["firing", "resolved"],
                "default": "firing",
                "description": "Overall payload status.",
            },
            "alerts": {
                "type": "array",
                "description": "Alerts included in the Alertmanager notification.",
                "items": alertmanager_alert_schema,
            },
            "groupLabels": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Alertmanager groupLabels field.",
                "example": {
                    "alertname": "TargetMissingOrDown",
                    "instance": "10.101.164.165:9290",
                },
            },
            "commonLabels": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Alertmanager commonLabels field.",
                "example": {
                    "alertname": "TargetMissingOrDown",
                    "severity": "critical",
                    "team": "infra",
                },
            },
            "commonAnnotations": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Alertmanager commonAnnotations field.",
                "example": {
                    "summary": "Target missing or down",
                    "event_link": "https://grafana.example.com/d/node?viewPanel=12",
                    "runbook_url": "https://wiki.example.com/runbooks/disk-full",
                },
            },
            "externalURL": {
                "type": "string",
                "nullable": True,
                "description": "Alertmanager external URL.",
                "example": "https://alertmanager.example.com",
            },
            "version": {
                "type": "string",
                "nullable": True,
                "description": "Alertmanager webhook payload version.",
                "example": "4",
            },
            "groupKey": {
                "type": "string",
                "nullable": True,
                "description": "Alertmanager group key.",
                "example": '{}/{severity="critical"}:{alertname="TargetMissingOrDown"}',
            },
            "truncatedAlerts": {
                "type": "integer",
                "nullable": True,
                "description": "Number of truncated alerts.",
                "example": 0,
            },
        },
        "example": {
            "receiver": "incidentrelay-infra",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "TargetMissingOrDown",
                        "instance": "10.101.164.165:9290",
                        "severity": "critical",
                        "team": "infra",
                    },
                    "annotations": {
                        "summary": "Target missing or down",
                        "description": "Target 10.101.164.165:9290 is not available",
                    },
                    "startsAt": "2026-04-28T15:35:00Z",
                    "endsAt": "0001-01-01T00:00:00Z",
                    "generatorURL": "https://prometheus.example.com/graph?g0.expr=up",
                    "fingerprint": "target-missing-10.101.164.165",
                }
            ],
            "groupLabels": {
                "alertname": "TargetMissingOrDown",
                "instance": "10.101.164.165:9290",
            },
            "commonLabels": {
                "severity": "critical",
                "team": "infra",
            },
            "commonAnnotations": {
                "summary": "Target missing or down",
            },
            "externalURL": "https://alertmanager.example.com",
            "version": "4",
            "groupKey": '{}/{severity="critical"}:{alertname="TargetMissingOrDown"}',
            "truncatedAlerts": 0,
        },
    }

    grafana_alert_schema = {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "status": {
                "type": "string",
                "description": (
                    "Grafana alert instance status. Resolved-like values are "
                    "normalized to resolved; other values are treated as firing."
                ),
                "example": "firing",
            },
            "labels": {
                "type": "object",
                "additionalProperties": True,
                "description": "Labels attached to this Grafana alert instance.",
                "example": {
                    "alertname": "DiskFull",
                    "severity": "critical",
                    "instance": "host1",
                    "grafana_folder": "Infrastructure",
                    "__alert_rule_uid__": "disk-full-rule",
                },
            },
            "annotations": {
                "type": "object",
                "additionalProperties": True,
                "description": (
                    "Annotations attached to this Grafana alert instance."
                ),
                "example": {
                    "summary": "Disk is full",
                    "description": "/var is 95% full",
                },
            },
            "startsAt": {
                "type": "string",
                "format": "date-time",
                "nullable": True,
                "description": "Time when the alert instance started firing.",
            },
            "endsAt": {
                "type": "string",
                "format": "date-time",
                "nullable": True,
                "description": "Time when the alert instance was resolved.",
            },
            "generatorURL": {
                "type": "string",
                "nullable": True,
                "description": "URL of the Grafana alert rule.",
            },
            "fingerprint": {
                "type": "string",
                "nullable": True,
                "description": (
                    "Stable Grafana alert instance fingerprint used for "
                    "deduplication. When omitted, IncidentRelay generates a "
                    "stable deduplication key."
                ),
                "example": "grafana-disk-full-host1",
            },
            "silenceURL": {
                "type": "string",
                "nullable": True,
                "description": "Grafana URL for creating a matching silence.",
            },
            "dashboardURL": {
                "type": "string",
                "nullable": True,
                "description": "Related Grafana dashboard URL.",
                "example": (
                    "https://grafana.example.com/d/system-overview"
                ),
            },
            "panelURL": {
                "type": "string",
                "nullable": True,
                "description": "Related Grafana panel URL.",
                "example": (
                    "https://grafana.example.com/d/system-overview"
                    "?viewPanel=12"
                ),
            },
            "values": {
                "type": "object",
                "additionalProperties": True,
                "description": "Evaluated Grafana expression values.",
                "example": {
                    "A": 95,
                },
            },
            "valueString": {
                "type": "string",
                "nullable": True,
                "description": (
                    "Human-readable Grafana expression values."
                ),
                "example": "[ var='A' value=95 ]",
            },
        },
    }

    grafana_body = {
        "type": "object",
        "required": ["alerts"],
        "additionalProperties": True,
        "properties": {
            "receiver": {
                "type": "string",
                "nullable": True,
                "description": "Grafana contact point receiver name.",
                "example": "incidentrelay",
            },
            "status": {
                "type": "string",
                "nullable": True,
                "description": (
                    "Overall Grafana notification status. The status of each "
                    "individual alert instance takes precedence."
                ),
                "example": "firing",
            },
            "orgId": {
                "oneOf": [
                    {"type": "integer"},
                    {"type": "string"},
                ],
                "nullable": True,
                "description": "Grafana organization id.",
                "example": 1,
            },
            "alerts": {
                "type": "array",
                "minItems": 1,
                "description": (
                    "Grafana alert instances included in the notification."
                ),
                "items": grafana_alert_schema,
            },
            "groupLabels": {
                "type": "object",
                "additionalProperties": True,
                "description": "Labels used by Grafana to group the notification.",
                "example": {
                    "alertname": "DiskFull",
                },
            },
            "commonLabels": {
                "type": "object",
                "additionalProperties": True,
                "description": "Labels common to all alert instances.",
                "example": {
                    "team": "sre",
                    "environment": "production",
                },
            },
            "commonAnnotations": {
                "type": "object",
                "additionalProperties": True,
                "description": "Annotations common to all alert instances.",
                "example": {
                    "runbook_url": (
                        "https://example.com/runbooks/disk"
                    ),
                },
            },
            "externalURL": {
                "type": "string",
                "nullable": True,
                "description": "Base URL of the Grafana instance.",
                "example": "https://grafana.example.com/",
            },
            "version": {
                "type": "string",
                "nullable": True,
                "description": "Grafana webhook payload version.",
            },
            "groupKey": {
                "type": "string",
                "nullable": True,
                "description": "Grafana notification group key.",
                "example": '{}:{alertname="DiskFull"}',
            },
            "truncatedAlerts": {
                "type": "integer",
                "minimum": 0,
                "nullable": True,
                "description": (
                    "Number of alert instances omitted from the payload."
                ),
                "example": 0,
            },
            "title": {
                "type": "string",
                "nullable": True,
                "description": "Rendered Grafana notification title.",
                "example": "[FIRING:1] DiskFull",
            },
            "state": {
                "type": "string",
                "nullable": True,
                "description": "Rendered Grafana notification state.",
                "example": "alerting",
            },
            "message": {
                "type": "string",
                "nullable": True,
                "description": "Rendered Grafana notification message.",
                "example": "Grafana notification",
            },
        },
        "example": {
            "receiver": "incidentrelay",
            "status": "firing",
            "orgId": 1,
            "groupKey": '{}:{alertname="DiskFull"}',
            "groupLabels": {
                "alertname": "DiskFull",
            },
            "commonLabels": {
                "team": "sre",
                "environment": "production",
            },
            "commonAnnotations": {
                "runbook_url": (
                    "https://example.com/runbooks/disk"
                ),
            },
            "externalURL": "https://grafana.example.com/",
            "title": "[FIRING:1] DiskFull",
            "state": "alerting",
            "message": "Grafana notification",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "DiskFull",
                        "severity": "critical",
                        "instance": "host1",
                        "grafana_folder": "Infrastructure",
                        "__alert_rule_uid__": "disk-full-rule",
                    },
                    "annotations": {
                        "summary": "Disk is full",
                        "description": "/var is 95% full",
                    },
                    "startsAt": "2026-06-21T10:00:00Z",
                    "endsAt": "0001-01-01T00:00:00Z",
                    "generatorURL": (
                        "https://grafana.example.com/alerting/"
                        "grafana/disk-full-rule/view"
                    ),
                    "fingerprint": "grafana-disk-full-host1",
                    "silenceURL": (
                        "https://grafana.example.com/alerting/silence/new"
                    ),
                    "dashboardURL": (
                        "https://grafana.example.com/d/system-overview"
                    ),
                    "panelURL": (
                        "https://grafana.example.com/d/system-overview"
                        "?viewPanel=12"
                    ),
                    "values": {
                        "A": 95,
                    },
                    "valueString": "[ var='A' value=95 ]",
                },
            ],
        },
    }

    rmon_body = {
        "type": "object",
        "required": ["title"],
        "additionalProperties": True,
        "properties": {
            "title": {
                "type": "string",
                "minLength": 1,
                "maxLength": 255,
                "description": "RMON alert title.",
                "example": "[rmon-production] critical: HTTP check failed",
            },
            "message": {
                "type": "string",
                "nullable": True,
                "description": "Detailed alert message.",
                "example": "critical: HTTP check failed",
            },
            "severity": {
                "type": "string",
                "nullable": True,
                "description": "RMON alert severity.",
                "example": "critical",
            },
            "status": {
                "type": "string",
                "nullable": True,
                "description": (
                    "RMON alert status. Resolved-like values such as resolved, "
                    "recovered, ok and up are normalized to resolved. Other "
                    "values are treated as firing."
                ),
                "example": "firing",
            },
            "fingerprint": {
                "type": "string",
                "nullable": True,
                "description": (
                    "Stable deduplication key. It must remain unchanged "
                    "between firing and resolved notifications."
                ),
                "example": "42 7",
            },
            "external_id": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "integer"},
                ],
                "nullable": True,
                "description": "External RMON check or event identifier.",
                "example": 42,
            },
            "team": {
                "type": "string",
                "nullable": True,
                "description": "Optional IncidentRelay team slug fallback.",
                "example": "sre",
            },
            "labels": {
                "type": "object",
                "additionalProperties": True,
                "description": (
                    "Additional labels used for routing and grouping."
                ),
                "example": {
                    "team": "sre",
                    "environment": "production",
                },
            },
            "runbook": {
                "type": "string",
                "nullable": True,
                "description": (
                    "Runbook text or URL configured for the RMON check."
                ),
            },
            "runbook_url": {
                "type": "string",
                "nullable": True,
                "description": "Runbook URL associated with the check.",
                "example": (
                    "https://example.com/runbooks/public-api"
                ),
            },
            "event_link": {
                "type": "string",
                "nullable": True,
                "description": "Direct URL to the source event or check.",
            },
            "rmon_name": {
                "type": "string",
                "nullable": True,
                "description": "Name of the originating RMON instance.",
                "example": "rmon-production",
            },
            "check_id": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "integer"},
                ],
                "nullable": True,
                "description": "RMON check identifier.",
                "example": 42,
            },
            "multi_check_id": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "integer"},
                ],
                "nullable": True,
                "description": "RMON multi-check identifier.",
                "example": 42,
            },
            "state_id": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "integer"},
                ],
                "nullable": True,
                "description": "RMON check-state identifier.",
                "example": 7,
            },
            "check_name": {
                "type": "string",
                "nullable": True,
                "description": "Human-readable RMON check name.",
                "example": "Public API",
            },
            "check_type": {
                "type": "string",
                "nullable": True,
                "description": "RMON check type.",
                "example": "http",
            },
            "target": {
                "type": "string",
                "nullable": True,
                "description": "Host, URL or other checked target.",
                "example": "https://api.example.com/health",
            },
            "agent": {
                "type": "string",
                "nullable": True,
                "description": "RMON agent that executed the check.",
                "example": "eu-west-agent",
            },
            "region": {
                "type": "string",
                "nullable": True,
                "description": "Region associated with the check.",
                "example": "eu-west",
            },
            "country": {
                "type": "string",
                "nullable": True,
                "description": "Country associated with the check.",
                "example": "DE",
            },
            "description": {
                "type": "string",
                "nullable": True,
                "description": "Description configured for the RMON check.",
            },
        },
        "example": {
            "title": "[rmon-production] critical: HTTP check failed",
            "message": "critical: HTTP check failed",
            "severity": "critical",
            "status": "firing",
            "fingerprint": "42 7",
            "external_id": 42,
            "rmon_name": "rmon-production",
            "multi_check_id": 42,
            "state_id": 7,
            "check_name": "Public API",
            "check_type": "http",
            "target": "https://api.example.com/health",
            "agent": "eu-west-agent",
            "region": "eu-west",
            "country": "DE",
            "runbook_url": (
                "https://example.com/runbooks/public-api"
            ),
            "labels": {
                "team": "sre",
                "environment": "production",
            },
        },
    }

    aws_sns_message_attribute = {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "Type": {
                "type": "string",
                "example": "String",
            },
            "Value": {
                "type": "string",
                "example": "production",
            },
            "StringValue": {
                "type": "string",
                "nullable": True,
            },
        },
    }

    aws_sns_body = {
        "type": "object",
        "required": [
            "Type",
            "MessageId",
            "TopicArn",
            "Message",
            "Timestamp",
            "SignatureVersion",
            "Signature",
            "SigningCertURL",
        ],
        "additionalProperties": True,
        "properties": {
            "Type": {
                "type": "string",
                "enum": [
                    "Notification",
                    "SubscriptionConfirmation",
                    "UnsubscribeConfirmation",
                ],
                "description": "Amazon SNS envelope type.",
                "example": "Notification",
            },
            "MessageId": {
                "type": "string",
                "minLength": 1,
                "description": "Unique Amazon SNS message identifier.",
                "example": "sns-message-1",
            },
            "TopicArn": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Amazon SNS Topic ARN. It must exactly match the Topic ARN "
                    "configured for the IncidentRelay route."
                ),
                "example": (
                    "arn:aws:sns:eu-west-1:"
                    "123456789012:incidentrelay-alerts"
                ),
            },
            "Subject": {
                "type": "string",
                "nullable": True,
                "description": "Optional Amazon SNS message subject.",
                "example": "ALARM: HighCPU",
            },
            "Message": {
                "type": "string",
                "description": (
                    "SNS message body. CloudWatch alarm notifications contain "
                    "a JSON-encoded CloudWatch alarm object."
                ),
            },
            "Timestamp": {
                "type": "string",
                "format": "date-time",
                "description": "Time when Amazon SNS created the message.",
                "example": "2026-06-21T10:00:01.000Z",
            },
            "SignatureVersion": {
                "type": "string",
                "enum": ["1", "2"],
                "description": (
                    "Amazon SNS signature version. Version 1 uses SHA-1 and "
                    "version 2 uses SHA-256."
                ),
                "example": "2",
            },
            "Signature": {
                "type": "string",
                "minLength": 1,
                "description": "Base64-encoded Amazon SNS RSA signature.",
            },
            "SigningCertURL": {
                "type": "string",
                "format": "uri",
                "description": (
                    "HTTPS URL of the Amazon SNS signing certificate. "
                    "IncidentRelay only accepts approved Amazon SNS hosts "
                    "and certificate paths."
                ),
                "example": (
                    "https://sns.eu-west-1.amazonaws.com/"
                    "SimpleNotificationService-example.pem"
                ),
            },
            "Token": {
                "type": "string",
                "nullable": True,
                "description": (
                    "Subscription confirmation token. Required for "
                    "confirmation messages."
                ),
            },
            "SubscribeURL": {
                "type": "string",
                "format": "uri",
                "nullable": True,
                "description": (
                    "Signed Amazon SNS subscription confirmation URL."
                ),
            },
            "UnsubscribeURL": {
                "type": "string",
                "format": "uri",
                "nullable": True,
            },
            "MessageAttributes": {
                "type": "object",
                "description": (
                    "Optional SNS message attributes. String attributes are "
                    "converted into IncidentRelay labels."
                ),
                "additionalProperties": aws_sns_message_attribute,
                "example": {
                    "team": {
                        "Type": "String",
                        "Value": "sre",
                    },
                    "environment": {
                        "Type": "String",
                        "Value": "production",
                    },
                },
            },
        },
        "example": {
            "Type": "Notification",
            "MessageId": "sns-message-1",
            "TopicArn": (
                "arn:aws:sns:eu-west-1:"
                "123456789012:incidentrelay-alerts"
            ),
            "Subject": "ALARM: HighCPU",
            "Message": (
                '{"AlarmName":"HighCPU",'
                '"AlarmDescription":"CPU usage is too high",'
                '"AWSAccountId":"123456789012",'
                '"NewStateValue":"ALARM",'
                '"NewStateReason":"Threshold crossed",'
                '"Region":"EU (Ireland)",'
                '"AlarmArn":"arn:aws:cloudwatch:eu-west-1:'
                '123456789012:alarm:HighCPU",'
                '"OldStateValue":"OK"}'
            ),
            "Timestamp": "2026-06-21T10:00:01.000Z",
            "SignatureVersion": "2",
            "Signature": "base64-signature",
            "SigningCertURL": (
                "https://sns.eu-west-1.amazonaws.com/"
                "SimpleNotificationService-example.pem"
            ),
            "MessageAttributes": {
                "team": {
                    "Type": "String",
                    "Value": "sre",
                },
                "environment": {
                    "Type": "String",
                    "Value": "production",
                },
            },
        },
    }

    aws_sns_confirmation_response = {
        "type": "object",
        "required": [
            "status",
            "message_id",
            "topic_arn",
        ],
        "properties": {
            "status": {
                "type": "string",
                "enum": [
                    "confirmed",
                    "unsubscribed",
                ],
                "example": "confirmed",
            },
            "message_id": {
                "type": "string",
                "example": "sns-confirmation-1",
            },
            "topic_arn": {
                "type": "string",
                "example": (
                    "arn:aws:sns:eu-west-1:"
                    "123456789012:incidentrelay-alerts"
                ),
            },
        },
        "additionalProperties": False,
    }

    aws_sns_responses = incoming_alert_responses(
        "Amazon SNS notification accepted."
    )

    aws_sns_ingest_response = aws_sns_responses[
        "200"
    ]["content"]["application/json"]["schema"]

    aws_sns_responses["200"] = {
        "description": (
            "Notification processed or subscription state confirmed."
        ),
        "content": {
            "application/json": {
                "schema": {
                    "oneOf": [
                        aws_sns_ingest_response,
                        aws_sns_confirmation_response,
                    ],
                },
            },
        },
    }

    # AWS SNS authenticates requests using the SNS signature and configured
    # Topic ARN, not a route intake bearer token.
    aws_sns_responses.pop("401", None)

    aws_sns_responses["403"] = {
        "description": (
            "Signature validation failed, Topic ARN did not match, "
            "or the route is not available."
        ),
    }

    aws_sns_responses["404"] = {
        "description": "AWS SNS route was not found.",
    }

    aws_sns_responses["502"] = {
        "description": (
            "The signing certificate could not be loaded or subscription "
            "confirmation failed."
        ),
    }

    zabbix_body = {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "event_id": {
                "type": "string",
                "description": "Zabbix event id. Use the same event_id for firing and resolved events.",
                "example": "100500",
            },
            "trigger_id": {
                "type": "string",
                "nullable": True,
                "description": "Zabbix trigger id.",
                "example": "200600",
            },
            "title": {
                "type": "string",
                "nullable": True,
                "description": "Alert title.",
                "example": "Disk space is low",
            },
            "host": {
                "type": "string",
                "nullable": True,
                "description": "Zabbix host name.",
                "example": "host1",
            },
            "trigger": {
                "type": "string",
                "nullable": True,
                "description": "Zabbix trigger name.",
                "example": "DiskSpaceLow",
            },
            "message": {
                "type": "string",
                "nullable": True,
                "description": "Alert message.",
                "example": "/var is 95% full",
            },
            "severity": {
                "type": "string",
                "nullable": True,
                "description": "Alert severity.",
                "example": "high",
            },
            "status": {
                "type": "string",
                "enum": ["firing", "resolved"],
                "default": "firing",
                "description": "Alert status.",
            },
            "team": {
                "type": "string",
                "nullable": True,
                "description": "Optional team slug fallback.",
                "example": "infra",
            },
            "labels": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Additional labels.",
                "example": {
                    "team": "infra",
                    "host": "host1",
                    "trigger": "DiskSpaceLow",
                },
            },
            "fingerprint": {
                "type": "string",
                "nullable": True,
                "description": "Optional stable deduplication key.",
                "example": "zabbix-100500",
            },
            "event_name": {
                "type": "string",
                "nullable": True,
                "description": "Zabbix event name, usually {EVENT.NAME}.",
                "example": "Disk space is low on host1",
            },
            "problem_name": {
                "type": "string",
                "nullable": True,
                "description": "Problem name fallback.",
                "example": "Disk space is low on host1",
            },
            "trigger_name": {
                "type": "string",
                "nullable": True,
                "description": "Zabbix trigger name.",
                "example": "Free disk space is less than 10%",
            },
            "event_tag": {
                "nullable": True,
                "description": "Zabbix event tags, for example {EVENT.TAGS} or {EVENT.TAGSJSON}.",
                "example": "team: infra, service: filesystem",
            },
            "tags": {
                "nullable": True,
                "description": "Zabbix tags. Can be object, array, JSON string or EVENT.TAGSJSON.",
                "example": [
                    {"tag": "team", "value": "infra"},
                    {"tag": "service", "value": "filesystem"}
                ],
            },
            "event_link": {
                "type": "string",
                "nullable": True,
                "description": "Direct URL to the Zabbix event/problem.",
                "example": "https://zabbix.example.com/tr_events.php?triggerid=98765&eventid=123456",
            },
            "event_url": {
                "type": "string",
                "nullable": True,
                "description": "Alias for event_link.",
            },
            "problem_url": {
                "type": "string",
                "nullable": True,
                "description": "Alias for event_link.",
            },
            "trigger_url": {
                "type": "string",
                "nullable": True,
                "description": "Alias for event_link.",
            },
            "zabbix_url": {
                "type": "string",
                "nullable": True,
                "description": "Base Zabbix frontend URL. IncidentRelay can build event_link from it when event_id is present.",
                "example": "https://zabbix.example.com",
            },
        },
        "example": {
            "status": "firing",
            "event_id": "123456",
            "trigger_id": "98765",
            "event_name": "High CPU load on host1",
            "host": "host1",
            "event_severity": "High",
            "event_status": "PROBLEM",
            "opdata": "CPU load is above 90%",
            "event_tag": "team: infra, service: cpu",
            "event_link": "https://zabbix.example.com/tr_events.php?triggerid=98765&eventid=123456",
            "team": "infra",
            "labels": {
                "host": "host1",
                "service": "cpu",
                "environment": "prod"
            }
        }
    }

    webhook_body = {
        "type": "object",
        "required": ["title"],
        "additionalProperties": True,
        "properties": {
            "title": {
                "type": "string",
                "description": "Alert title.",
                "example": "Disk is full",
            },
            "message": {
                "type": "string",
                "nullable": True,
                "description": "Alert message.",
                "example": "/var is 95% full",
            },
            "severity": {
                "type": "string",
                "nullable": True,
                "description": "Alert severity.",
                "example": "critical",
            },
            "status": {
                "type": "string",
                "enum": ["firing", "resolved"],
                "default": "firing",
                "description": "Alert status.",
            },
            "team": {
                "type": "string",
                "nullable": True,
                "description": "Optional team slug fallback.",
                "example": "infra",
            },
            "labels": {
                "type": "object",
                "additionalProperties": {"type": "string"},
                "description": "Alert labels.",
                "example": {
                    "team": "infra",
                    "instance": "host1",
                    "alertname": "DiskFull",
                },
            },
            "fingerprint": {
                "type": "string",
                "nullable": True,
                "description": "Stable deduplication key. Use the same value for firing and resolved.",
                "example": "disk-full-host1-var",
            },
            "external_id": {
                "type": "string",
                "nullable": True,
                "description": "External system event id.",
                "example": "event-123",
            },
            "event_link": {
                "type": "string",
                "nullable": True,
                "description": "Direct URL to the source event.",
                "example": "https://monitoring.example.com/events/deploy-incident-42",
            },
            "event_url": {
                "type": "string",
                "nullable": True,
                "description": "Alias for event_link.",
            },
            "alert_url": {
                "type": "string",
                "nullable": True,
                "description": "Alias for event_link.",
            },
            "source_url": {
                "type": "string",
                "nullable": True,
                "description": "Alias for event_link.",
            },
            "dashboard_url": {
                "type": "string",
                "nullable": True,
                "description": "Dashboard URL related to the alert.",
            },
            "runbook_url": {
                "type": "string",
                "nullable": True,
                "description": "Runbook URL related to the alert.",
            },
        },
        "example": {
            "title": "Disk is full",
            "message": "/var is 95% full",
            "severity": "critical",
            "status": "firing",
            "fingerprint": "disk-full-host1-var",
            "labels": {
                "team": "infra",
                "instance": "host1",
                "alertname": "DiskFull",
            },
            "event_link": "https://monitoring.example.com/events/deploy-incident-42",
        },
    }

    return {
        "/api/integrations/alertmanager": {
            "post": {
                "tags": ["integrations"],
                "summary": "Receive Alertmanager alerts",
                "description": (
                    "Accepts the standard Prometheus Alertmanager webhook payload. "
                    "The route intake token must belong to a route with source=alertmanager. "
                    "Top-level Alertmanager fields such as receiver, groupLabels, commonLabels, "
                    "commonAnnotations, externalURL, version, groupKey and truncatedAlerts are accepted."
                ),
                "operationId": "receiveAlertmanagerAlerts",
                "security": [{"bearerAuth": []}],
                "requestBody": json_body("Standard Alertmanager webhook payload.", alertmanager_body),
                "responses": incoming_alert_responses("Alertmanager alerts accepted."),
            }
        },
        "/api/integrations/grafana": {
            "post": {
                "tags": ["integrations"],
                "summary": "Receive Grafana Alerting alerts",
                "description": (
                    "Receives a Grafana Alerting webhook contact point payload. "
                    "The route intake token must belong to an active route with "
                    "source=grafana. Each object in alerts is normalized and "
                    "processed independently. The individual alert status takes "
                    "precedence over the top-level notification status."
                ),
                "operationId": "receiveGrafanaAlerts",
                "security": [{"bearerAuth": []}],
                "requestBody": json_body(
                    "Grafana Alerting webhook payload.",
                    grafana_body,
                ),
                "responses": incoming_alert_responses(
                    "Grafana alerts accepted."
                ),
            },
        },
        "/api/integrations/rmon": {
            "post": {
                "tags": ["integrations"],
                "summary": "Receive RMON alerts",
                "description": (
                    "Receives an alert from RMON. The route intake token "
                    "must belong to an active route with source=rmon. "
                    "The payload is normalized and processed through the "
                    "standard IncidentRelay routing, grouping, suppression, "
                    "notification and escalation pipeline."
                ),
                "operationId": "receiveRmonAlert",
                "security": [{"bearerAuth": []}],
                "requestBody": json_body(
                    "RMON alert payload.",
                    rmon_body,
                ),
                "responses": incoming_alert_responses(
                    "RMON alert accepted."
                ),
            },
        },
        "/api/integrations/aws-sns/{route_id}": {
            "post": {
                "tags": ["integrations"],
                "summary": "Receive Amazon SNS and CloudWatch notifications",
                "description": (
                    "Receives signed Amazon SNS messages for one IncidentRelay "
                    "route. The route must use source=aws_sns and have an exact "
                    "SNS Topic ARN configured. IncidentRelay verifies the SNS "
                    "signature, signing certificate URL and Topic ARN before "
                    "processing the message. CloudWatch ALARM and "
                    "INSUFFICIENT_DATA states are normalized to firing, while "
                    "OK is normalized to resolved. Subscription confirmation "
                    "messages are verified and confirmed automatically."
                ),
                "operationId": "receiveAwsSnsNotification",
                "security": [],
                "parameters": [
                    {
                        "name": "route_id",
                        "in": "path",
                        "required": True,
                        "description": (
                            "IncidentRelay route configured for this SNS topic."
                        ),
                        "schema": {
                            "type": "integer",
                            "minimum": 1,
                        },
                    },
                ],
                "requestBody": json_body(
                    "Signed Amazon SNS message envelope.",
                    aws_sns_body,
                ),
                "responses": aws_sns_responses,
            },
        },
        "/api/integrations/zabbix": {
            "post": {
                "tags": ["integrations"],
                "summary": "Receive Zabbix alerts",
                "description": (
                    "Receives a Zabbix webhook payload. The route intake token must belong "
                    "to a route with source=zabbix. Use the same event_id for firing and resolved events."
                ),
                "operationId": "receiveZabbixAlerts",
                "security": [{"bearerAuth": []}],
                "requestBody": json_body("Zabbix webhook payload.", zabbix_body),
                "responses": incoming_alert_responses("Zabbix alert accepted."),
            }
        },
        "/api/integrations/sentry/{route_id}": {
            "post": {
                "tags": ["integrations"],
                "summary": "Receive Sentry webhook",
                "description": (
                    "Receives signed webhooks from a Sentry Internal Integration. "
                    "The route id in the URL selects an IncidentRelay route with source=sentry. "
                    "The request is authenticated by Sentry-Hook-Signature using the "
                    "Sentry Client Secret stored in route integration_config. "
                    "This endpoint does not use IncidentRelay bearer intake tokens."
                ),
                "operationId": "receiveSentryWebhook",
                "parameters": [
                    path_param("route_id", "Sentry IncidentRelay route id."),
                    {
                        "name": "Sentry-Hook-Signature",
                        "in": "header",
                        "required": True,
                        "description": (
                            "HMAC-SHA256 signature generated by Sentry using the "
                            "Internal Integration Client Secret."
                        ),
                        "schema": {
                            "type": "string",
                            "minLength": 1,
                        },
                    },
                    {
                        "name": "Sentry-Hook-Resource",
                        "in": "header",
                        "required": False,
                        "description": (
                            "Sentry resource name. IncidentRelay uses this to normalize "
                            "event_alert, metric_alert and issue events."
                        ),
                        "schema": {
                            "type": "string",
                            "enum": [
                                "event_alert",
                                "metric_alert",
                                "issue",
                            ],
                        },
                    },
                ],
                "requestBody": json_body(
                    "Sentry Internal Integration webhook payload.",
                    SENTRY_WEBHOOK_BODY_SCHEMA,
                ),
                "responses": {
                    "200": response(
                        "Sentry webhook accepted.",
                        ALERT_PROCESSING_RESULT_LIST_SCHEMA,
                    ),
                    "202": response(
                        "Sentry webhook processed, but no alert group was created.",
                        ALERT_PROCESSING_RESULT_LIST_SCHEMA,
                    ),
                    "207": response(
                        "Batch contains both accepted and failed alerts.",
                        ALERT_PROCESSING_RESULT_LIST_SCHEMA,
                    ),
                    "400": response("Invalid payload or route source mismatch."),
                    "403": response(
                        "Missing or invalid Sentry-Hook-Signature, disabled route, or inactive team/group."
                    ),
                    "404": response("Sentry route was not found."),
                    "409": response("Sentry webhook secret is not configured for this route."),
                },
            }
        },
        "/api/integrations/librenms": {
            "post": {
                "tags": ["integrations"],
                "summary": "Receive LibreNMS alerts",
                "description": (
                    "Receives a LibreNMS API transport payload. The route intake "
                    "token must belong to a route with source=librenms. Use the "
                    "same uid/id for firing and recovery events."
                ),
                "operationId": "receiveLibreNMSAlerts",
                "security": [{"bearerAuth": []}],
                "requestBody": json_body("LibreNMS API transport payload.", librenms_body),
                "responses": incoming_alert_responses("LibreNMS alert accepted."),
            }
        },
        "/api/integrations/webhook": {
            "post": {
                "tags": ["integrations"],
                "summary": "Receive generic webhook alerts",
                "description": (
                    "Receives a generic alert payload. The route intake token must belong "
                    "to a route with source=webhook. Provide a stable fingerprint to avoid duplicate alerts."
                ),
                "operationId": "receiveGenericWebhookAlerts",
                "security": [{"bearerAuth": []}],
                "requestBody": json_body("Generic webhook payload.", webhook_body),
                "responses": incoming_alert_responses("Generic webhook alert accepted."),
            }
        },
        "/api/integrations/mattermost/actions": {
            "post": {
                "tags": ["integrations"],
                "summary": "Handle Mattermost interactive buttons",
                "description": (
                    "Receives Mattermost interactive message button callbacks. The endpoint validates "
                    "the callback secret from the action context, acknowledges or resolves the alert, "
                    "and updates the original Mattermost post when the channel is configured in Bot API mode."
                ),
                "operationId": "handleMattermostAction",
                "requestBody": json_body("Mattermost interactive action payload.", {
                    "type": "object",
                    "properties": {
                        "context": {
                            "type": "object",
                            "properties": {
                                "alert_id": {"type": "integer"},
                                "channel_id": {"type": "integer"},
                                "action": {"type": "string", "enum": ["acknowledge", "resolve"]},
                                "secret": {"type": "string"},
                            },
                        }
                    },
                }),
                "responses": {
                    "200": response("Action processed."),
                    "400": response("Invalid action payload."),
                    "403": response("Invalid callback secret."),
                },
            }
        },
        "/api/integrations/slack/actions": {
            "post": {
                "tags": ["integrations"],
                "summary": "Handle Slack alert action",
                "description": (
                    "Receives Slack Block Kit button interactions for alert "
                    "acknowledgement and resolution. "
                    "The request body is application/x-www-form-urlencoded "
                    "and contains a JSON-encoded payload field. "
                    "IncidentRelay verifies the raw request body using the "
                    "Slack signing secret configured on the referenced channel. "
                    "Requests older than five minutes are rejected. "
                    "This endpoint does not use IncidentRelay bearer tokens."
                ),
                "operationId": "handleSlackAlertAction",
                "security": [],
                "parameters": [
                    header_param(
                        "X-Slack-Request-Timestamp",
                        (
                            "Unix timestamp included in the Slack request. "
                            "Requests older than five minutes are rejected."
                        ),
                        {
                            "type": "string",
                            "pattern": "^[0-9]+$",
                            "example": "1782123456",
                        },
                        required=True,
                    ),
                    header_param(
                        "X-Slack-Signature",
                        (
                            "Slack v0 HMAC-SHA256 signature calculated from "
                            "the raw request body, timestamp and signing secret."
                        ),
                        {
                            "type": "string",
                            "pattern": "^v0=[a-f0-9]{64}$",
                            "example": (
                                "v0="
                                "0123456789abcdef"
                                "0123456789abcdef"
                                "0123456789abcdef"
                                "0123456789abcdef"
                            ),
                        },
                        required=True,
                    ),
                ],
                "requestBody": {
                    "required": True,
                    "description": (
                        "Slack Block Kit interaction encoded as a form field."
                    ),
                    "content": {
                        "application/x-www-form-urlencoded": {
                            "schema": SLACK_ACTION_FORM_SCHEMA,
                        },
                    },
                },
                "responses": {
                    "200": response(
                        "Slack alert action processed.",
                        SLACK_ACTION_RESPONSE_SCHEMA,
                    ),
                    "400": response(
                        (
                            "Malformed form body, unsupported interaction type, "
                            "invalid action or invalid alert context."
                        ),
                        SLACK_ACTION_ERROR_SCHEMA,
                    ),
                    "403": response(
                        (
                            "Missing or invalid Slack signature, expired request, "
                            "disabled or mismatched Slack channel, or alert and "
                            "channel belong to different teams."
                        ),
                        SLACK_ACTION_ERROR_SCHEMA,
                    ),
                    "404": response(
                        "Referenced IncidentRelay alert was not found.",
                        SLACK_ACTION_ERROR_SCHEMA,
                    ),
                },
            }
        },
        "/api/integrations/voice/callback/{channel_id}/{secret}": {
            "post": {
                "tags": ["integrations"],
                "summary": "Handle voice provider callback",
                "description": (
                    "Receives callbacks from voice call providers. "
                    "The endpoint validates the channel callback secret, loads the provider "
                    "configured for the voice_call channel, and passes the raw payload to "
                    "provider.parse_callback(). "
                    "Providers may normalize call status changes, DTMF button presses and errors. "
                    "DTMF digits can be mapped to IncidentRelay actions through channel config, "
                    "for example 1=acknowledge and 2=resolve."
                ),
                "operationId": "handleVoiceProviderCallback",
                "parameters": [
                    path_param("channel_id", "Voice call notification channel id."),
                    {
                        "name": "secret",
                        "in": "path",
                        "required": True,
                        "description": (
                            "Voice callback secret. "
                            "Uses channel config callback_secret or global voice.callback_secret."
                        ),
                        "schema": {
                            "type": "string",
                            "minLength": 1,
                        },
                    },
                ],
                "requestBody": json_body(
                    "Provider-specific callback payload.",
                    VOICE_CALLBACK_BODY_SCHEMA,
                ),
                "responses": {
                    "200": response(
                        "Callback processed or ignored.",
                        VOICE_CALLBACK_RESPONSE_SCHEMA,
                    ),
                    "400": response(
                        "Invalid callback payload, provider parse error or channel is not voice_call."
                    ),
                    "403": response("Invalid voice callback secret."),
                    "404": response("Channel or notification not found."),
                },
            }
        },
    }
