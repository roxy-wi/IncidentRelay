---
title: Uptime Kuma
description: Send Uptime Kuma monitor state changes to IncidentRelay and automatically resolve alerts when monitors recover.
---

# Uptime Kuma integration

Uptime Kuma checks whether websites, APIs, hosts, ports and other targets are available. IncidentRelay turns those monitor state changes into actionable alerts, routes them to the responsible team, starts the configured notification and escalation flow, and resolves the same alert when the monitor becomes healthy again.

Use this integration when you want this workflow:

```text
Uptime Kuma detects DOWN
    -> IncidentRelay creates or updates an alert
    -> route, service and orchestration rules select ownership
    -> on-call users are notified
    -> Uptime Kuma detects UP
    -> IncidentRelay resolves the existing alert
```

The native integration understands the standard Uptime Kuma Webhook JSON body. You do not need to build a custom payload template.

Endpoint:

```text
POST /api/integrations/uptime-kuma
```

## What the integration is useful for

Typical examples include:

- a public website stops responding;
- an internal API returns errors or times out;
- a TCP port cannot be reached;
- a server no longer answers ping;
- a DNS check fails;
- a certificate or keyword monitor changes state;
- several monitors need to be routed to different teams using Uptime Kuma tags;
- transient failures should be delayed, suppressed or enriched by Event Orchestration.

Uptime Kuma performs the check. IncidentRelay owns the operational response: assignment, notification, escalation, acknowledgement, incident grouping, service impact, comments, timeline and audit history.

## Before you start

You need:

1. an IncidentRelay group and team;
2. at least one notification channel or another delivery method;
3. a route whose source is **Uptime Kuma**;
4. access to Uptime Kuma notification settings;
5. an HTTPS URL that Uptime Kuma can reach.

A route intake token belongs to one IncidentRelay route. Keep it secret. Anyone who has the token can submit events to that route.

## Step 1: create a route in IncidentRelay

1. Open **Routes**.
2. Click **Create route**.
3. Select the group and team that should initially own the alerts.
4. Set **Source** to **Uptime Kuma**.
5. Give the route a clear name, for example `Uptime Kuma production`.
6. Attach the notification channels that should receive alerts.
7. Save the route.
8. Open the route intake details and copy:
   - the intake URL;
   - the bearer token;
   - the example request.

For a native Uptime Kuma route, IncidentRelay uses this endpoint:

```text
https://incidentrelay.example.com/api/integrations/uptime-kuma
```

New Uptime Kuma routes default to grouping by `uptime_kuma_monitor_id`. This keeps repeated DOWN events and the later UP event attached to the same monitor incident.

## Step 2: configure Uptime Kuma

In Uptime Kuma:

1. Open **Settings**.
2. Open **Notifications**.
3. Click **Setup Notification**.
4. Choose **Webhook**.
5. Enter a descriptive name, for example `IncidentRelay`.
6. Set the webhook URL to the IncidentRelay intake URL.
7. Use the `POST` method.
8. Use JSON / `application/json` content type.
9. Add the authorization header shown below.
10. Keep the standard/default Uptime Kuma request body.
11. Save the notification.
12. Attach it to each monitor that should create IncidentRelay alerts.

Additional headers:

```json
{
  "Authorization": "Bearer INCIDENTRELAY_ROUTE_TOKEN"
}
```

Do not put the token in the query string. Do not switch to a custom body unless you intentionally reproduce the standard `heartbeat`, `monitor` and `msg` fields described below.

Use Uptime Kuma's **Test** button after saving. A test notification may not contain a real monitor or heartbeat. IncidentRelay accepts it as an informational test event so you can verify connectivity and authentication.

## Lifecycle mapping

Uptime Kuma sends a numeric status in `heartbeat.status`. IncidentRelay maps it as follows:

| Uptime Kuma status | Meaning | IncidentRelay lifecycle |
| --- | --- | --- |
| `0` | DOWN | `firing` |
| `1` | UP | `resolved` |
| `2` | PENDING | `firing` |
| `3` | MAINTENANCE | `resolved` |

A DOWN or PENDING notification creates a new alert or updates the existing alert for that monitor. An UP notification resolves it. MAINTENANCE is also treated as resolved so a monitor intentionally placed into maintenance does not keep paging the on-call user.

IncidentRelay uses this stable deduplication key when a monitor id is present:

```text
uptime-kuma:<monitor id>
```

For example, monitor `42` produces:

```text
uptime-kuma:42
```

The monitor id must remain the same between DOWN and UP. That is normally true for the standard Uptime Kuma webhook payload.

## Example DOWN payload

A standard notification resembles this simplified payload:

```json
{
  "heartbeat": {
    "monitorID": 42,
    "status": 0,
    "time": "2026-07-27 12:10:00.000",
    "msg": "Request timeout after 48000ms",
    "ping": null,
    "duration": 48
  },
  "monitor": {
    "id": 42,
    "name": "Payments API",
    "type": "http",
    "url": "https://payments.example.com/health",
    "tags": [
      {"name": "team", "value": "sre"},
      {"name": "service", "value": "payments"},
      {"name": "environment", "value": "production"},
      {"name": "severity", "value": "critical"}
    ]
  },
  "msg": "[Payments API] [DOWN] Request timeout"
}
```

IncidentRelay normalizes it approximately to:

```json
{
  "source": "uptime_kuma",
  "status": "firing",
  "title": "Payments API",
  "message": "Request timeout after 48000ms",
  "severity": "critical",
  "team_slug": "sre",
  "dedup_key": "uptime-kuma:42"
}
```

## Example recovery payload

When the monitor becomes healthy, Uptime Kuma sends the same monitor id with status `1`:

```json
{
  "heartbeat": {
    "monitorID": 42,
    "status": 1,
    "time": "2026-07-27 12:12:30.000",
    "msg": "200 - OK",
    "ping": 84
  },
  "monitor": {
    "id": 42,
    "name": "Payments API",
    "type": "http",
    "url": "https://payments.example.com/health"
  },
  "msg": "[Payments API] [UP] 200 - OK"
}
```

Because the deduplication key is still `uptime-kuma:42`, IncidentRelay resolves the existing alert rather than creating an unrelated recovery alert.

## Labels created by IncidentRelay

The normalizer adds matcher-friendly labels:

| Label | Example | Purpose |
| --- | --- | --- |
| `uptime_kuma_monitor_id` | `42` | Stable monitor identity and grouping. |
| `uptime_kuma_monitor_name` | `Payments API` | Human-readable monitor name. |
| `uptime_kuma_monitor_type` | `http` | HTTP, ping, port and other monitor types. |
| `uptime_kuma_status` | `down` | `down`, `up`, `pending` or `maintenance`. |
| `uptime_kuma_status_code` | `0` | Original numeric status. |
| `uptime_kuma_target` | `https://.../health` | URL or host/port being checked. |
| `uptime_kuma_hostname` | `db-01.example.com` | Hostname when present. |
| `uptime_kuma_port` | `5432` | Port when present. |
| `uptime_kuma_ping_ms` | `84` | Latest response time when present. |
| `uptime_kuma_duration_seconds` | `48` | Failure/check duration when present. |
| `uptime_kuma_local_datetime` | `2026-07-27 ...` | Time supplied by Uptime Kuma. |
| `event_link` | `https://...` | Link to the monitored HTTP target or supplied monitor link. |

The full original webhook body is also retained as the raw integration payload for inspection and orchestration matching.

## Use Uptime Kuma tags for routing

Tags make one shared Uptime Kuma notification integration useful for many teams and services.

Recommended tags:

```text
team=sre
service=payments
environment=production
severity=critical
region=eu-west
cluster=payments-primary
```

The integration exposes every tag with a safe prefixed name:

```text
uptime_kuma_tag_team=sre
uptime_kuma_tag_service=payments
uptime_kuma_tag_environment=production
```

Common routing tags are additionally exposed without the prefix:

```text
team=sre
service=payments
environment=production
severity=critical
region=eu-west
cluster=payments-primary
```

The `team` or `oncall_team` tag can select `team_slug`. The `severity` or `priority` tag is used as the normalized alert severity when it contains a supported value.

Keep tag names consistent across monitors. Prefer lowercase names and stable values. For example, use `environment=production` everywhere instead of mixing `prod`, `production` and `Production` unless your matchers handle all variants.

## Use with Event Orchestration

Event Orchestration can enrich or route Uptime Kuma events before the normal alert lifecycle runs.

### Route every Uptime Kuma event

Condition:

```text
event.source equals uptime_kuma
```

Possible actions:

```text
set_team -> Platform SRE
set_route -> Uptime Kuma production
stop
```

### Route one service by tags

Conditions:

```text
ALL
├── event.source equals uptime_kuma
├── labels.service equals payments
└── labels.environment equals production
```

Actions:

```text
set_team -> Payments on-call
set_service -> Payments API
set_priority -> P1
stop
```

### Delay short outages

Many uptime checks recover after one failed probe. To page only when a failure persists:

```text
IF event.source equals uptime_kuma
AND labels.uptime_kuma_status equals down
THEN pause 120 seconds
     retrigger preserve
     reason "Wait for a transient outage to recover"
```

If the UP notification arrives within two minutes, the pending event is resolved without creating an active alert. Test this behavior in Simulator and Replay before publishing.

### Raise severity for a critical monitor

```text
ALL
├── event.source equals uptime_kuma
├── labels.uptime_kuma_tag_tier equals critical
└── labels.environment equals production
```

Action:

```text
set_severity -> critical
```

### Group related monitors into one incident

Suppose several monitors check different endpoints of one service. You can group them into one alert group while retaining a child alert per monitor:

```text
group_key: uptime-kuma:{{ labels.service }}:{{ labels.environment }}
dedup_key: uptime-kuma:{{ labels.uptime_kuma_monitor_id }}
window_seconds: 900
```

Read the [Event Orchestration user guide](../usage/event-orchestration.md) before changing grouping or adding `pause`, `suppress` or `drop` actions in production.

## Test with curl

Replace the URL and token:

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/uptime-kuma' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ROUTE_TOKEN' \
  -d '{
    "heartbeat": {
      "monitorID": 42,
      "status": 0,
      "msg": "Connection refused",
      "ping": null
    },
    "monitor": {
      "id": 42,
      "name": "PostgreSQL",
      "type": "port",
      "hostname": "db-01.example.com",
      "port": 5432,
      "tags": [
        {"name": "team", "value": "database"},
        {"name": "service", "value": "postgresql"},
        {"name": "environment", "value": "production"}
      ]
    },
    "msg": "[PostgreSQL] [DOWN] Connection refused"
  }'
```

Then send an UP event with the same monitor id:

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/uptime-kuma' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ROUTE_TOKEN' \
  -d '{
    "heartbeat": {
      "monitorID": 42,
      "status": 1,
      "msg": "TCP connection succeeded",
      "ping": 12
    },
    "monitor": {
      "id": 42,
      "name": "PostgreSQL",
      "type": "port",
      "hostname": "db-01.example.com",
      "port": 5432
    },
    "msg": "[PostgreSQL] [UP] TCP connection succeeded"
  }'
```

The second response should refer to the same alert and group and report a resolved status.

## What happens when the route is wrong

The endpoint verifies that the bearer token belongs to a route whose source is `uptime_kuma`.

Common responses:

| Response | Meaning |
| --- | --- |
| `401 Route intake token is required` | Authorization header is missing or malformed. |
| `401 Invalid or disabled route intake token` | Token is wrong, rotated, or the route is disabled. |
| `400 Route source must be uptime_kuma` | The token belongs to another integration source. |
| `422` validation response | The JSON body does not contain enough Uptime Kuma data. |

Do not reuse an Alertmanager, Grafana or Generic Webhook token for this endpoint. Create a dedicated Uptime Kuma route instead.

## Troubleshooting

### Uptime Kuma test succeeds, but real monitors do not notify

- Open the monitor and verify that the IncidentRelay notification is enabled for it.
- Confirm that notifications are enabled for DOWN and recovery events.
- Check Uptime Kuma notification logs.
- Verify that the URL is reachable from the Uptime Kuma container or host, not only from your browser.

### IncidentRelay returns 401

- Ensure the header is exactly `Authorization: Bearer TOKEN`.
- Remove accidental quotes around the complete header value.
- Check whether the route token was rotated.
- Confirm that a reverse proxy forwards the `Authorization` header.

### IncidentRelay returns route source mismatch

The token belongs to a route created for another source. Open **Routes**, create or edit a route with source **Uptime Kuma**, and copy its intake token.

### DOWN creates an alert, but UP does not resolve it

Compare the two raw payloads:

- both must contain the same `monitor.id` or `heartbeat.monitorID`;
- the recovery must contain `heartbeat.status=1`;
- orchestration must not replace the deduplication key with a changing value;
- route grouping should use stable labels, preferably `uptime_kuma_monitor_id`.

### Every notification creates a new alert

- Check that the standard monitor id is present.
- Do not use timestamps in orchestration `set_dedup_key` or `set_grouping` actions.
- Verify that DOWN and UP events use the same route.

### Tags are not available for matching

Inspect the raw monitor object. Tags must be included in `monitor.tags`. Older or customized Uptime Kuma payloads may omit them. You can still match on monitor id, name, type, hostname or target.

### The alert title is too generic

A real monitor notification should contain `monitor.name`. If it is missing, IncidentRelay falls back to a generic `Uptime Kuma notification` title. Keep monitor names descriptive and unique enough for operators.

## Security recommendations

- Use HTTPS between Uptime Kuma and IncidentRelay.
- Use a dedicated route and token for Uptime Kuma.
- Do not paste the token into monitor names, messages, tags or URLs.
- Rotate the route token if it is exposed.
- Restrict network access to the intake endpoint when possible.
- Keep the default JSON body unless a custom body is required and reviewed.
- Treat monitor messages and tags as untrusted external input when using templates or webhook actions.
- Test orchestration in Simulator or shadow mode before publishing actions that drop, suppress, pause or call external webhooks.

## Operational checklist

Before enabling the integration broadly:

- [ ] Uptime Kuma route uses source `uptime_kuma`.
- [ ] Bearer token is stored in Additional Headers.
- [ ] Default JSON body is enabled.
- [ ] Test notification reaches IncidentRelay.
- [ ] A real DOWN event creates one alert.
- [ ] A real UP event resolves that same alert.
- [ ] Team and service tags match existing IncidentRelay objects or orchestration rules.
- [ ] Notification channels reach the intended on-call user.
- [ ] Event Orchestration has been simulated before publication.
- [ ] Token rotation and ownership are documented.
