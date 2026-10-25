---
title: OpenSearch Alerting
description: Receive OpenSearch Alerting custom webhook notifications in IncidentRelay.
---

# OpenSearch Alerting integration

Receive notifications from **OpenSearch Alerting** as technical AlertGroups. This
integration is independent of deployment Change Events: it processes monitoring
signals (`firing` and explicitly submitted `resolved`) through the normal
IncidentRelay Route, Event Orchestration, escalation and notification lifecycle.

Endpoint: `POST /api/integrations/opensearch`

## IncidentRelay route

Create a Route with **Source = OpenSearch Alerting**, select the owning team,
notification channels and optional default service, and save it. Copy the
route's **intake token** (do not use a Slack/email notification-channel token).

Suggested route grouping:

```json
["opensearch_monitor_id", "opensearch_trigger_id", "opensearch_bucket_key"]
```

A missing bucket key triggers the normal IncidentRelay per-alert fallback. If a
monitor produces **multiple independent bucket alerts**, configure a stable
`bucket_key` and send **one webhook per bucket** so they stay independent.

## OpenSearch setup

1. In **Notifications**, create a **Custom webhook** channel using the URL:

   `https://incidentrelay.example.com/api/integrations/opensearch`

2. Configure its HTTP headers:

   ```text
   Content-Type: application/json
   Authorization: Bearer <incidentrelay-route-intake-token>
   ```

3. In **Alerting → Monitors**, add an action to the relevant trigger and select
   that channel. Use a JSON message template. For a query-level monitor:

   ```json
   {
     "monitor_id": "{{ctx.monitor.id}}",
     "trigger_id": "{{ctx.trigger.id}}",
     "severity": "{{ctx.trigger.severity}}",
     "status": "ACTIVE"
   }
   ```

   This minimal template intentionally avoids interpolating arbitrary message
   text into JSON. If you add monitor names, trigger names or query output,
   make sure those values are JSON-escaped; invalid JSON is rejected with 400.
   OpenSearch does not automatically JSON-encode arbitrary Mustache text.

4. Send a test notification and verify the AlertGroup in IncidentRelay.

OpenSearch 2.x+ uses **Notifications channels**, not the removed legacy
Destinations creation interface. OpenSearch documents that custom webhook
headers may be stored in plain text in the cluster: protect the token and
rotate it if exposed. Use HTTPS. See the
[OpenSearch Notifications documentation](https://docs.opensearch.org/latest/observing-your-data/notifications/index/).

## Alert identity and recovery

IncidentRelay builds the stable deduplication key from
`monitor_id + trigger_id + bucket_key (if present)` and the authenticated Route.
A changing message, severity, OpenSearch alert record ID or title never creates
a different key for the same monitor/trigger/bucket. Severity levels `1`–`5`
map to critical/high/medium/warning/info.

The `status` field supports `ACTIVE` (firing) and explicit `COMPLETED`,
`recovered` or `resolved` (resolved). For example, **when your OpenSearch monitor
configuration supports a distinct completion notification**, send:

```json
{
  "monitor_id": "monitor-123",
  "trigger_id": "trigger-errors",
  "status": "COMPLETED"
}
```

The completion event **must use the same monitor, trigger and bucket identifiers**.
Not every OpenSearch monitor/action mode emits an independent recovery
notification. For per-bucket monitors, `ctx.completedAlerts` can provide
completed alert context; consult the OpenSearch monitor/action documentation
for your deployment and construct one recovery payload per bucket. IncidentRelay
never treats silence, missing webhook calls, or elapsed time as recovery.

## Supported JSON properties

| Property | Required | Purpose |
| --- | --- | --- |
| `monitor_id` | Yes | Stable OpenSearch monitor identifier |
| `trigger_id` | Yes | Stable OpenSearch trigger identifier |
| `bucket_key` | For per-bucket alerts | Stable bucket identity (not a changing count) |
| `status` | No | `ACTIVE` or explicit recovery status; defaults to firing |
| `severity` | No | OpenSearch numeric level or IncidentRelay severity |
| `monitor_name`, `trigger_name`, `title`, `message` | No | Readable context; does not change dedup identity |
| `alert_id` | No | External record ID for tracing, not dedup identity |
| `labels`, `team` | No | Matcher-friendly metadata; Route token takes precedence for ownership |
| `monitor_url`, `event_link` | No | Absolute HTTP(S) source link |

The normalizer also accepts `monitor.id`, `trigger.id`, and
`ctx.monitor.id`/`ctx.trigger.id` in nested JSON objects when supplied.
This endpoint does **not** accept bare OpenSearch query results or arbitrary
Notification-channel test messages without monitor and trigger IDs.

The API uses the standard IncidentRelay response array with `created`,
`group_id`, `alert_id`, `status`, `outcome` and optional `trace_id`. Use the
[Event Orchestration simulator](../usage/event-orchestration.md) to preview the
normalization and routing decision without creating production alerts.
