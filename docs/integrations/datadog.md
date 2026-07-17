---
title: Datadog
description: Send Datadog monitor alerts and recoveries to IncidentRelay through the Datadog Webhooks integration.
---

# Datadog integration

IncidentRelay accepts Datadog monitor notifications through a native incoming route.

Endpoint:

```text
POST /api/integrations/datadog
```

## Create the IncidentRelay route

Create a route with:

```text
Source: Datadog
```

Attach the required notification channels, save the route, and copy its intake token.

## Configure Datadog Webhooks

In Datadog, open **Integrations → Webhooks**, create a webhook, and set its URL to:

```text
https://incidentrelay.example.com/api/integrations/datadog
```

Configure the custom headers as JSON:

```json
{
  "Authorization": "Bearer INCIDENTRELAY_ROUTE_TOKEN"
}
```

Configure the custom JSON payload:

```json
{
  "alert_title": "$ALERT_TITLE",
  "text_only_msg": "$TEXT_ONLY_MSG",
  "alert_id": "$ALERT_ID",
  "alert_cycle_key": "$ALERT_CYCLE_KEY",
  "aggreg_key": "$AGGREG_KEY",
  "alert_transition": "$ALERT_TRANSITION",
  "alert_type": "$ALERT_TYPE",
  "alert_priority": "$ALERT_PRIORITY",
  "alert_scope": "$ALERT_SCOPE",
  "alert_metric": "$ALERT_METRIC",
  "event_type": "$EVENT_TYPE",
  "event_id": "$ID",
  "hostname": "$HOSTNAME",
  "link": "$LINK",
  "tags": "$TAGS",
  "date_posix": "$DATE_POSIX"
}
```

Do not enable form encoding. Send the payload as JSON.

Add the webhook mention to each Datadog monitor that should notify IncidentRelay:

```text
@webhook-incidentrelay
```

Datadog retries webhook delivery for internal errors and `5xx` responses. Validate the payload before enabling it broadly, because client-side `4xx` errors are not treated as transient failures.

## Lifecycle and deduplication

IncidentRelay uses fields in this order:

```text
ALERT_CYCLE_KEY
AGGREG_KEY
explicit dedup_key or fingerprint
generated key from monitor/event identity and scope
```

`ALERT_CYCLE_KEY` is preferred because Datadog keeps it stable from the initial trigger until recovery.

Transition mapping:

| Datadog transition | IncidentRelay status |
|---|---|
| `Triggered`, `Re-Triggered` | `firing` |
| `Warn`, `Re-Warn` | `firing` |
| `No Data`, `Re-No Data` | `firing` |
| `Renotify` | `firing` |
| `Recovered` | `resolved` |

If `alert_transition` is omitted, `alert_type=success` is treated as resolved. Other values default to firing.

## Severity mapping

An explicit `severity` field takes precedence. Otherwise IncidentRelay uses monitor priority and then `ALERT_TYPE`.

| Datadog value | IncidentRelay severity |
|---|---|
| `P1` or `error` | `critical` |
| `P2` | `high` |
| `P3` | `medium` |
| `P4` or `warning` | `warning` |
| `P5` or `info` | `info` |

## Labels

Datadog tags and `ALERT_SCOPE` are converted to matcher-friendly labels.

Example input:

```text
env:prod,service:payments,team:sre,monitor
```

Normalized labels:

```json
{
  "env": "prod",
  "service": "payments",
  "team": "sre",
  "monitor": "true"
}
```

IncidentRelay also adds metadata labels such as:

```text
datadog_alert_id
datadog_event_id
datadog_alert_cycle_key
datadog_aggreg_key
datadog_alert_transition
datadog_alert_type
datadog_alert_priority
datadog_scope
datadog_event_type
datadog_metric
host
event_link
```

These labels can be used in route matchers, service match rules, priority policies, silences, notification policies, and analytics.

## Test request

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/datadog' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ROUTE_TOKEN' \
  -d '{
    "alert_title": "[Triggered] API latency is high",
    "text_only_msg": "p95 latency exceeded 2 seconds",
    "alert_id": "1234",
    "alert_cycle_key": "cycle-1234-prod-api",
    "alert_transition": "Triggered",
    "alert_type": "error",
    "alert_priority": "P1",
    "alert_scope": "env:prod,service:api",
    "hostname": "api-01",
    "link": "https://app.datadoghq.com/monitors/1234",
    "tags": "env:prod,service:api,team:sre"
  }'
```

Send the same payload with:

```json
{
  "alert_transition": "Recovered"
}
```

and the same `alert_cycle_key` to resolve the existing alert.

## Troubleshooting

- `401 Route intake token is required`: check the `Authorization` custom header.
- `400 Route source must be datadog`: the token belongs to a route with another source.
- Trigger and recovery create separate alerts: verify that both payloads contain the same non-empty `ALERT_CYCLE_KEY`.
- Service matching does not work: inspect the normalized labels in Alert details and compare them with the service matcher.
- Datadog does not call the endpoint: verify that the monitor message includes the configured `@webhook-...` mention.
