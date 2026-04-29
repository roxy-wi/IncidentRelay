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


def tags():
    """
    Return OpenAPI tags.
    """

    return [
        {
            "name": "integrations",
            "description": (
                "Incoming alert endpoints for Alertmanager, Zabbix and generic webhooks. "
                "Each endpoint requires a route intake token. The route token selects "
                "the route, team, rotation and notification channels."
            ),
        }
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
        },
        "example": {
            "event_id": "100500",
            "status": "firing",
            "severity": "high",
            "host": "host1",
            "trigger": "Disk space is low",
            "message": "/var is 95% full",
            "labels": {
                "team": "infra",
                "host": "host1",
                "trigger": "DiskSpaceLow",
            },
        },
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
                "responses": {
                    "200": response("Alerts accepted."),
                    "400": response("Invalid Alertmanager payload."),
                    "401": response("Route intake token or API token is required."),
                },
            }
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
                "responses": {
                    "200": response("Alert accepted."),
                    "400": response("Invalid Zabbix payload."),
                    "401": response("Route intake token or API token is required."),
                },
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
                "responses": {
                    "200": response("Alert accepted."),
                    "400": response("Invalid webhook payload."),
                    "401": response("Route intake token or API token is required."),
                },
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
    }
