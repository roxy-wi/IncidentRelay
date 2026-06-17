---
title: Generic Webhook Integration
description: Generic incoming webhook route setup and payload format.
---

# Generic webhook integration

Generic webhook is an incoming alert source for custom systems.

Endpoint:

```text
POST /api/integrations/webhook
```

Authentication uses a route intake token:

```text
Authorization: Bearer ROUTE_TOKEN
```

## Route setup

Create a route with:

```text
Source: webhook
```

Attach at least one notification channel and copy the route intake token into the sender.

## Service assignment

After a route matches the incoming alert, IncidentRelay can attach the alert to a service.

There are two ways:

1. Select a default service on the route.
2. Configure service match rules.

Use a default service when all alerts through the route belong to the same system. Use service match rules when one route receives alerts for multiple systems.

Example service match rule:

```json
{
  "labels": {
    "service": "api",
    "environment": {
      "op": "regex",
      "value": "^(prod|production)$"
    }
  }
}
```

This can attach matching alerts to an `API` or `Billing API` service.

## Payload example

```json
{
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
}
```

`event_link` is the recommended field for a direct link to the source event, dashboard, trace, deployment, log query, or another system page that explains the alert.

Supported aliases:

```text
event_link
event_url
alert_url
source_url
dashboard_url
runbook_url
```

The first non-empty value is stored in `labels.event_link` and exposed as `alert.event_link` in the alert API response.

## Normalized fields

| IncidentRelay field | Source |
|---|---|
| `source` | `webhook` |
| `team_slug` | `team`, `labels.team`, or `labels.oncall_team` |
| `external_id` | `external_id` |
| `dedup_key` | `fingerprint`, or generated from source, external ID, title and labels |
| `title` | `title`, default `Webhook alert` |
| `message` | `message` |
| `severity` | `severity` |
| `labels` | `labels` plus helper labels such as `event_link` |
| `event_link` | `event_link`, `event_url`, `alert_url`, `source_url`, `dashboard_url`, `runbook_url`, or matching label aliases |
| `payload` | original payload |
| `status` | `status`, default `firing` |
