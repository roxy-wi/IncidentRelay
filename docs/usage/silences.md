---
title: Silences
description: Suppress notifications for matching alerts with silence rules.
---

# Silences

Silences temporarily suppress alert notifications for planned maintenance, noisy alerts or known incidents that do not need paging.

A silence belongs to one team and uses the shared IncidentRelay matcher format. When an incoming alert matches an active silence, IncidentRelay marks it as silenced and skips normal notifications.

## How matching works

All conditions in a silence matcher object use **AND** semantics. An empty object matches every alert in the team and should only be used intentionally.

```json
{}
```

Match a specific alert on one instance:

```json
{
  "alertname": "DiskFull",
  "instance": "host1.example.com"
}
```

The structured label form is equivalent:

```json
{
  "labels": {
    "alertname": "DiskFull",
    "instance": "host1.example.com"
  }
}
```

See [Alert Matchers](../concepts/matchers.md) for the complete shared format, value operators and matcher editor behavior.

## Matcher examples

### Silence warning CPU alerts

```json
{
  "alertname": "HighCPU",
  "severity": "warning"
}
```

### Silence critical alerts for a service

```json
{
  "service": "billing-api",
  "severity": "critical"
}
```

### Silence a group of hosts by regex

```json
{
  "instance": {
    "regex": "^web-[0-9]+\\.example\\.com$"
  }
}
```

### Silence Kubernetes alerts by namespace

```json
{
  "namespace": "staging"
}
```

### Exclude one value

```json
{
  "environment": {
    "not": "production"
  }
}
```

### Match one of several values

```json
{
  "severity": ["warning", "info"]
}
```

## Matcher suggestions

The shared matcher editor can load known label names and observed values from recent alerts in the selected team.

Suggestions help avoid spelling mistakes, but they do not save the silence or guarantee that future alerts will use the same labels. Review the generated JSON before saving.

## Statuses

| Status | Meaning |
|---|---|
| Active | The silence is enabled and the current time is between `starts_at` and `ends_at`. |
| Scheduled | The silence is enabled, but `starts_at` is in the future. |
| Expired | The silence ended. Expired silences are hidden after the retention window by default. |
| Disabled | The silence was manually disabled and remains visible for review. |

## Existing unresolved alerts

By default, a Silence affects only alert occurrences received while the Silence is active. Alerts that were already firing continue their current notification and escalation flow.

Enable **Apply to existing unresolved alerts** only when the Silence should also suppress matching firing alerts immediately. This is useful for emergency alert storms, but it is intentionally disabled by default because responders may already be working on an existing incident.

By default, **Reactivate silenced alerts when this Silence ends** is enabled. When the final matching Silence ends or is disabled, alerts that were created or retroactively suppressed by that Silence become active again. IncidentRelay then starts the normal notification flow for alerts that were never notified, or sends an update for alerts that had already produced notifications. Acknowledged alert groups keep their acknowledged state.

Disable this option only when affected alerts should remain silenced after the Silence ends. Those alerts will not be reactivated automatically. To release them later, edit the Silence, enable this option and save it. The setting applies independently to each Silence.

Overlapping Silences are handled independently. An alert remains silenced while another matching Silence application still holds it, including a Silence configured not to reactivate affected alerts automatically.

## Expired silence history

Expired silences are hidden after they are older than the configured retention window. By default, expired silences disappear from the normal list 30 days after `ends_at`.

Enable expired history on the Silences page to find older entries for audits and troubleshooting.

## Disabled silences

Disabling a silence does not delete it. A disabled silence remains visible so users can understand why it no longer applies.

Use disabled silences for review and audit history. Use expired silences for time-based lifecycle.

## Recommended matcher strategy

Keep silences as narrow as possible.

Prefer:

```json
{
  "alertname": "DiskFull",
  "instance": "host1.example.com"
}
```

Avoid broad matchers unless the maintenance window is intentional:

```json
{
  "severity": "critical"
}
```

A broad silence can suppress unrelated incidents.

## Common labels

The exact labels depend on the incoming integration payload.

| Label | Example |
|---|---|
| `alertname` | `DiskFull` |
| `severity` | `critical` |
| `instance` | `host1.example.com` |
| `job` | `node-exporter` |
| `service` | `billing-api` |
| `namespace` | `production` |
| `cluster` | `prod-eu-1` |

Alertmanager matchers usually target values from `alerts[].labels`. For Zabbix or generic webhook payloads, use the labels stored on the resulting alert.

## Troubleshooting

If a silence does not match an alert:

1. Check the alert labels in the alert details page.
2. Confirm each matcher name exists in the stored alert labels or normalized context.
3. Confirm exact values use the same spelling and case.
4. Test regular expressions against the actual stored value.
5. Confirm the silence is active, enabled and belongs to the same team as the alert.
6. Confirm the alert was received while the silence was active.

If too many alerts are silenced, add labels such as `alertname`, `instance`, `service`, `namespace` or `severity` to narrow the matcher.
