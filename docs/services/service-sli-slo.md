# Service SLI / SLO

IncidentRelay SLI/SLO adds service-level reliability targets using the data IncidentRelay already owns: alert groups, acknowledgement and resolution timestamps, service status, maintenance windows, and service catalog metadata.

The feature is intentionally named **SLI / SLO** in the UI and API.

- **SLI** — Service Level Indicator. It defines what is measured for a service.
- **SLO** — Service Level Objective. It defines the target for an SLI.
- **SLO measurement** — the latest calculation result for an SLO over its configured window.

Example:

```text
SLI: Critical alert acknowledgement latency
SLO: 95% of critical alert groups must be acknowledged within 15 minutes over 30 days
```

## Where to create SLI and SLO

SLI and SLO are configured from the service details modal.

Open:

```text
Services → service row → Details
```

or click the service name in the Services table if the UI opens the details modal from the name.

Inside the service details modal, use the section:

```text
SLI / SLO
```

Typical flow:

1. Open the service details modal.
2. Scroll to **SLI / SLO**.
3. Click **Add SLI**.
4. Select the SLI type, source and filters.
5. Save the SLI.
6. Click **Add SLO**.
7. Select the SLI created above.
8. Configure the target and evaluation window.
9. Save the SLO.

SLI must be created first. SLO is always attached to exactly one SLI.

## Where to view SLI and SLO

SLI/SLO is visible in three places.

### 1. Service details

Open:

```text
Services → service row → Details → SLI / SLO
```

This view shows SLI/SLO for one service:

```text
SLI name
SLO name
current value
target
status
window
error budget, when applicable
```

Use this view when investigating one service.

### 2. Services analytics

Open:

```text
Services → Analytics → SLI / SLO health
```

This view shows aggregate SLO health across services in the current group/team scope:

```text
Total SLOs
Met
At risk
Breached
No data
Services with SLOs
```

It also includes a table with latest SLO measurements:

```text
Service | SLI | SLO | Current | Target | Status | Window | Budget
```

Use this view to find breached or at-risk services quickly.

### 3. Service timeline

Open:

```text
Services → service row → Details → Timeline
```

SLI/SLO create, update and delete actions are written to the service timeline through the service catalog event adapter.

Timeline event types:

```text
service_sli.created
service_sli.updated
service_sli.deleted
service_slo.created
service_slo.updated
service_slo.deleted
```

Category:

```text
sli_slo
```

## Supported SLI types

### `alert_ack_latency`

Measures how quickly alert groups are acknowledged.

Source data:

```text
AlertGroup.first_seen_at
AlertGroup.acknowledged_at
```

Good event:

```text
acknowledged_at - first_seen_at <= SLO threshold
```

Typical SLO:

```text
95% of critical alert groups must be acknowledged within 15 minutes over 30 days.
```

Recommended SLO fields:

```json
{
  "target_percent_basis_points": 9500,
  "threshold_seconds": 900,
  "window_days": 30,
  "include_open_alerts": true,
  "enabled": true
}
```

### `alert_resolve_latency`

Measures how quickly alert groups are resolved.

Source data:

```text
AlertGroup.first_seen_at
AlertGroup.resolved_at
```

Good event:

```text
resolved_at - first_seen_at <= SLO threshold
```

Typical SLO:

```text
90% of critical alert groups must be resolved within 4 hours over 30 days.
```

Recommended SLO fields:

```json
{
  "target_percent_basis_points": 9000,
  "threshold_seconds": 14400,
  "window_days": 30,
  "include_open_alerts": true,
  "enabled": true
}
```

### `incident_availability`

Estimates availability from impact alert intervals.

Source data:

```text
AlertGroup.first_seen_at
AlertGroup.resolved_at
```

If `include_open_alerts` is enabled, open alert groups end at calculation time. Overlapping intervals are merged before downtime is calculated, so simultaneous incidents do not double-count downtime.

This SLI is intentionally named **incident-based availability**. It is not synthetic monitoring availability and it is not Prometheus availability. It answers:

```text
How much of the window did this service have active impact incidents?
```

Typical SLO:

```text
99.9% incident-based availability over 30 days, excluding maintenance windows.
```

Recommended SLO fields:

```json
{
  "target_percent_basis_points": 9990,
  "window_days": 30,
  "exclude_maintenance": true,
  "include_open_alerts": true,
  "enabled": true
}
```

### `incident_count`

Counts matching alert groups in the rolling window.

Typical SLO:

```text
No more than 3 P1/P2 impact incidents over 30 days.
```

Recommended SLO fields:

```json
{
  "threshold_count": 3,
  "window_days": 30,
  "include_open_alerts": true,
  "enabled": true
}
```

## SLI fields

SLI defines what to measure.

Common fields:

| Field | Meaning |
| --- | --- |
| `slug` | Stable identifier inside the service. |
| `name` | Human-readable SLI name. |
| `description` | Optional explanation. |
| `sli_type` | What IncidentRelay measures. |
| `source` | Where measurement data comes from. |
| `severity` | Optional severity filter for response SLI types, for example `critical`. |
| `priority` | Optional single priority filter, for example `p1`. For impact SLI types prefer `configuration.priority_scope`. |
| `configuration.priority_scope` | Priority list used by incident-based availability and incident count, for example `["p1", "p2"]`. Defaults to P1/P2 for impact SLI types. |
| `enabled` | Enables or disables this SLI. |

Supported `sli_type` values:

```text
alert_ack_latency
alert_resolve_latency
incident_availability
incident_count
```

Supported first-party source:

```text
incidentrelay_alert_groups
```

Future sources can be added later, for example Prometheus, blackbox checks, logs or external metrics APIs.

### Priority scope for impact SLI types

`incident_availability` and `incident_count` are impact-oriented SLI types. By default they use alert group priority, not alert severity:

```json
{
  "configuration": {
    "priority_scope": ["p1", "p2"]
  }
}
```

This means a P1/P2 warning alert can count as impact, while a P3 critical alert does not count as downtime for incident-based availability. Severity remains useful for response SLI types such as acknowledgement and resolution latency.

## SLO fields

SLO defines the target for an SLI.

Common fields:

| Field | Meaning |
| --- | --- |
| `sli_id` | SLI this SLO belongs to. |
| `name` | Human-readable SLO name. |
| `description` | Optional explanation. |
| `target_percent_basis_points` | Percent target stored as basis points. Used by latency and availability SLOs. |
| `threshold_seconds` | Time threshold in seconds. Used by ack and resolve latency SLOs. |
| `threshold_count` | Maximum allowed incident count. Used by incident count SLOs. |
| `window_days` | Rolling evaluation window. |
| `exclude_maintenance` | Excludes maintenance windows from incident availability downtime accounting. |
| `include_open_alerts` | Includes open alert groups in calculations. |
| `enabled` | Enables or disables this SLO. |

The internal `comparison` value is derived by the backend from the SLI type. Users do not need to select it in the UI.

Backend-derived comparison rules:

```text
alert_ack_latency        → percent_good_gte
alert_resolve_latency    → percent_good_gte
incident_availability    → percent_good_gte
incident_count           → value_lte
```

## Percent values and basis points

Percent targets are stored as basis points to avoid float drift.

```text
95%    = 9500
99%    = 9900
99.9%  = 9990
99.99% = 9999
```

The API response may also include human-readable percent values such as:

```text
target_percent
value_percent
```

## SLO statuses

### `met`

The current value satisfies the target and there are no pending in-window events that could still breach it.

### `at_risk`

The current measured value satisfies the target, but pending events still exist inside the configured threshold.

Example:

```text
An alert was created 5 minutes ago.
The ACK threshold is 15 minutes.
The alert is not acknowledged yet.
The SLO is still technically within target, but it can breach soon.
```

### `breached`

The current value does not satisfy the target.

### `no_data`

There are no matching events in the window or the SLO cannot be evaluated.

## Error budget

For `incident_availability`, IncidentRelay calculates error budget fields.

```text
budget_seconds = window_seconds * (100% - target%)
budget_consumed_seconds = downtime_seconds
budget_remaining_seconds = budget_seconds - budget_consumed_seconds
```

Example for a 30-day, 99.9% target:

```text
Window: 30 days = 2,592,000 seconds
Allowed downtime: 0.1% = 2,592 seconds = 43.2 minutes
```

If downtime exceeds the budget, the SLO status becomes `breached`.

## Maintenance windows

When `exclude_maintenance` is enabled, `incident_availability` subtracts maintenance windows from downtime accounting. This prevents planned maintenance from consuming error budget.

Latency and incident count SLOs currently use alert groups matching their SLI filter. They do not exclude maintenance from the denominator.

## UI examples

### Example 1: critical ACK latency

Create SLI:

```text
Name: Critical alert acknowledgement latency
SLI type: Alert acknowledgement latency
Source: IncidentRelay alert groups
Severity: critical
Enabled: yes
```

Create SLO:

```text
SLI: Critical alert acknowledgement latency
Name: 95% critical alerts acknowledged within 15 minutes
Target: 95%
Threshold: 15 minutes
Window: 30 days
Include open alerts: yes
Enabled: yes
```

### Example 2: incident-based availability

Create SLI:

```text
Name: P1/P2 incident availability
SLI type: Incident-based availability
Source: IncidentRelay alert groups
Priority scope: P1, P2
Enabled: yes
```

Create SLO:

```text
SLI: P1/P2 incident availability
Name: 99.9% P1/P2 incident-based availability over 30 days
Target: 99.9%
Window: 30 days
Exclude maintenance: yes
Include open alerts: yes
Enabled: yes
```

### Example 3: max critical incidents

Create SLI:

```text
Name: Critical incident count
SLI type: Impact incident count
Source: IncidentRelay alert groups
Severity: critical
Enabled: yes
```

Create SLO:

```text
SLI: Critical incident count
Name: No more than 3 critical incidents over 30 days
Max incidents: 3
Window: 30 days
Include open alerts: yes
Enabled: yes
```

## API overview

### SLIs

```text
GET    /api/services/<service_id>/slis
POST   /api/services/<service_id>/slis
PUT    /api/services/slis/<sli_id>
DELETE /api/services/slis/<sli_id>
```

### SLOs

```text
GET    /api/services/<service_id>/slos
POST   /api/services/<service_id>/slos
PUT    /api/services/slos/<slo_id>
DELETE /api/services/slos/<slo_id>
```

### Aggregate endpoints

```text
GET /api/services/sli-slo
GET /api/services/sli-slo/analytics
```

`/api/services/sli-slo/analytics` powers:

```text
Services → Analytics → SLI / SLO health
```

## API example: create ACK latency SLI and SLO

Create the SLI:

```http
POST /api/services/42/slis
Content-Type: application/json
```

```json
{
  "slug": "critical-ack-latency",
  "name": "Critical alert acknowledgement latency",
  "description": "How quickly critical alert groups are acknowledged.",
  "sli_type": "alert_ack_latency",
  "source": "incidentrelay_alert_groups",
  "severity": "critical",
  "enabled": true
}
```

Create the SLO:

```http
POST /api/services/42/slos
Content-Type: application/json
```

```json
{
  "sli_id": 10,
  "name": "95% critical alerts acknowledged within 15 minutes",
  "description": "Critical alerts should be acknowledged quickly by the on-call team.",
  "target_percent_basis_points": 9500,
  "threshold_seconds": 900,
  "window_days": 30,
  "include_open_alerts": true,
  "enabled": true
}
```

The SLO create response includes the first evaluation. Later list, details and analytics calls refresh the evaluation.

## API example: create incident availability SLO

Create SLI:

```json
{
  "slug": "critical-incident-availability",
  "name": "Critical incident availability",
  "sli_type": "incident_availability",
  "source": "incidentrelay_alert_groups",
  "severity": "critical",
  "enabled": true
}
```

Create SLO:

```json
{
  "sli_id": 11,
  "name": "99.9% incident-based availability over 30 days",
  "target_percent_basis_points": 9990,
  "window_days": 30,
  "exclude_maintenance": true,
  "include_open_alerts": true,
  "enabled": true
}
```

## API example: create incident count SLO

Create SLI:

```json
{
  "slug": "critical-incident-count",
  "name": "Critical incident count",
  "sli_type": "incident_count",
  "source": "incidentrelay_alert_groups",
  "severity": "critical",
  "enabled": true
}
```

Create SLO:

```json
{
  "sli_id": 12,
  "name": "No more than 3 critical incidents over 30 days",
  "threshold_count": 3,
  "window_days": 30,
  "include_open_alerts": true,
  "enabled": true
}
```

## Service details payload

`GET /api/services/<service_id>/details` includes an SLI/SLO block for the service details modal.

Expected top-level field:

```json
{
  "sli_slo": {
    "slis": [],
    "slos": [],
    "measurements": [],
    "summary": {
      "total": 0,
      "met": 0,
      "at_risk": 0,
      "breached": 0,
      "no_data": 0
    }
  }
}
```

## Analytics payload

`GET /api/services/sli-slo/analytics` returns latest SLO measurements for the current readable service scope.

Example shape:

```json
{
  "summary": {
    "total": 4,
    "met": 2,
    "at_risk": 1,
    "breached": 1,
    "no_data": 0,
    "services": 3
  },
  "items": [
    {
      "service_id": 42,
      "service_name": "Payments API",
      "sli_id": 10,
      "sli_name": "Critical alert acknowledgement latency",
      "sli_type": "alert_ack_latency",
      "slo_id": 20,
      "slo_name": "95% critical alerts acknowledged within 15 minutes",
      "window_days": 30,
      "target_percent": 95.0,
      "value_percent": 97.2,
      "status": "met",
      "good_count": 35,
      "bad_count": 1,
      "pending_count": 0,
      "total_count": 36,
      "measured_at": "2026-06-28T18:00:00Z"
    }
  ]
}
```

## Timeline events

SLI/SLO create, update and delete actions publish service timeline events through the service catalog event adapter.

Events:

```text
service_sli.created
service_sli.updated
service_sli.deleted
service_slo.created
service_slo.updated
service_slo.deleted
```

Category:

```text
sli_slo
```

These events are visible here:

```text
Services → service row → Details → Timeline
```

## Current limitations

IncidentRelay currently supports first-party SLIs based on alert groups and incident/status accounting. It does not yet calculate these external SLIs:

```text
Prometheus latency
request success rate
error rate
synthetic availability
real user monitoring availability
tracing-based SLIs
```

These can be added later as new SLI sources and evaluator branches without changing the basic SLI/SLO API model.
