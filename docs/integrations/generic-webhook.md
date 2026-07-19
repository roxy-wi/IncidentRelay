---
title: Generic Webhook and PagerDuty Events API v2
description: Generic incoming webhook route setup, payload format and PagerDuty Events API v2 compatibility.
---

# Generic webhook integration

The Webhook route accepts two request formats at the same endpoint:

1. IncidentRelay generic webhook payload.
2. PagerDuty Events API v2-compatible alert events.

Endpoint:

```text
POST /api/integrations/webhook
```

## Route setup

Create a route with:

```text
Source: Webhook / PagerDuty Events API v2
```

Attach the required notification channels and copy the route intake token.

The same token is used differently by each format:

| Format | Authentication |
|---|---|
| IncidentRelay generic webhook | `Authorization: Bearer ROUTE_TOKEN` |
| PagerDuty Events API v2-compatible | JSON field `routing_key: ROUTE_TOKEN` |

`routing_key` is treated as a secret. IncidentRelay uses it to select the route and stores `[REDACTED]` instead of the token in the alert payload.

## IncidentRelay generic format

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/webhook' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ROUTE_TOKEN' \
  -d '{
    "status": "firing",
    "external_id": "deploy-incident-42",
    "fingerprint": "deploy-api-prod-42",
    "title": "API deploy failed",
    "message": "Deployment failed on api-prod-1",
    "severity": "critical",
    "team": "infra",
    "event_link": "https://monitoring.example.com/events/deploy-incident-42",
    "labels": {
      "service": "api",
      "environment": "prod",
      "host": "api-prod-1"
    },
    "details": {
      "deploy_id": "42",
      "region": "eu-1"
    }
  }'
```

### Generic normalized fields

| IncidentRelay field | Source |
|---|---|
| `source` | `webhook` |
| `team_slug` | `team`, `labels.team`, or `labels.oncall_team` |
| `external_id` | `external_id` |
| `dedup_key` | `fingerprint`, or generated from source, external ID, title and labels |
| `title` | `title` |
| `message` | `message` |
| `severity` | `severity` |
| `labels` | `labels` plus helper labels such as `event_link` |
| `payload` | Original payload, with secret `routing_key` redacted when present |
| `status` | `status`, default `firing` |

## PagerDuty Events API v2-compatible format

Systems that already have a PagerDuty Events API v2 exporter can point it at the IncidentRelay webhook endpoint.

Use the IncidentRelay route intake token as `routing_key`.

### Trigger

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/webhook' \
  -H 'Content-Type: application/json' \
  -d '{
    "routing_key": "ROUTE_TOKEN",
    "event_action": "trigger",
    "dedup_key": "database-prod-01",
    "payload": {
      "summary": "Production database is unavailable",
      "source": "db-prod-01",
      "severity": "critical",
      "component": "postgresql",
      "group": "production",
      "class": "database",
      "custom_details": {
        "service": "database",
        "environment": "prod",
        "host": "db-prod-01"
      }
    },
    "links": [
      {
        "href": "https://monitoring.example.com/incidents/db-prod-01",
        "text": "Open monitoring"
      }
    ]
  }'
```

Successful PagerDuty-compatible requests return HTTP `202`:

```json
{
  "status": "success",
  "message": "Event processed",
  "dedup_key": "database-prod-01"
}
```

### Acknowledge

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/webhook' \
  -H 'Content-Type: application/json' \
  -d '{
    "routing_key": "ROUTE_TOKEN",
    "event_action": "acknowledge",
    "dedup_key": "database-prod-01"
  }'
```

The matching IncidentRelay alert group is acknowledged. The lookup is scoped to the webhook route identified by `routing_key`.

### Resolve

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/webhook' \
  -H 'Content-Type: application/json' \
  -d '{
    "routing_key": "ROUTE_TOKEN",
    "event_action": "resolve",
    "dedup_key": "database-prod-01"
  }'
```

The matching IncidentRelay alert group and its child alerts are resolved.

Unknown or already-resolved `dedup_key` values are accepted as successful no-ops. This preserves the asynchronous follow-up-event behavior expected by PagerDuty-compatible senders.

### PagerDuty field mapping

| PagerDuty field | IncidentRelay field |
|---|---|
| `routing_key` | Webhook route intake token; not stored in clear text |
| `event_action=trigger` | `status=firing` |
| `event_action=acknowledge` | Acknowledge matching alert group |
| `event_action=resolve` | Resolve matching alert group |
| `dedup_key` | `dedup_key` and `external_id` |
| `payload.summary` | `title` |
| `payload.severity` | Normalized severity |
| `payload.source` | Label `source` |
| `payload.component` | Label `component` |
| `payload.group` | Label `group` |
| `payload.class` | Label `class` |
| `payload.custom_details` | Scalar values copied to labels; full object retained in payload |
| First `links[].href` | `labels.event_link` |
| `client` | Label `pagerduty_client` |

PagerDuty severity is normalized using IncidentRelay aliases. For example, `error` becomes `critical`.

`payload.summary`, `payload.source`, and `payload.severity` are required for `trigger`. `dedup_key` is required for `acknowledge` and `resolve`.

## Service assignment

After the route accepts an event, IncidentRelay can attach it to a service in two ways:

1. Select a default service on the route.
2. Configure service match rules.

PagerDuty standard fields and scalar `custom_details` become labels, so they can be used by service match rules.

Example:

```json
{
  "labels": {
    "component": "postgresql",
    "environment": {
      "op": "regex",
      "value": "^(prod|production)$"
    }
  }
}
```

## Event links

The generic format supports these aliases:

```text
event_link
event_url
alert_url
source_url
dashboard_url
runbook_url
```

For PagerDuty-compatible requests, the first non-empty `links[].href` is stored as `labels.event_link`. `client_url` is used as a fallback.
