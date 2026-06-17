---
title: Silences
description: Suppress notifications for matching alerts with silence rules.
---

# Silences

Silences temporarily suppress alert notifications for planned maintenance, noisy alerts, or known incidents that do not need paging.

A silence belongs to a team and matches alerts by their labels. When an incoming alert matches an active silence, IncidentRelay marks it as silenced and does not send normal notifications for it.

## How matching works

A silence contains one or more matchers. A silence matches an alert only when **all** matchers match the alert labels.

For example, this silence:

```json
{
  "matchers": [
    {
      "name": "alertname",
      "value": "DiskFull",
      "is_regex": false
    },
    {
      "name": "instance",
      "value": "host1",
      "is_regex": false
    }
  ]
}
```

matches only alerts where:

```text
alert.labels.alertname = DiskFull
alert.labels.instance = host1
```

If any matcher does not match, the silence does not apply.

## Matcher fields

| Field | Description |
|---|---|
| `name` | Alert label name, for example `alertname`, `severity`, `instance`, `namespace`, or `service`. |
| `value` | Expected label value or regular expression. |
| `is_regex` | When `false`, the value must match exactly. When `true`, the value is treated as a regular expression. |

## Matcher examples

### Silence one alert by name

Use this when a specific alert is noisy across a team.

```json
{
  "matchers": [
    {
      "name": "alertname",
      "value": "DiskFull",
      "is_regex": false
    }
  ]
}
```

### Silence one instance

Use this during maintenance on a single host.

```json
{
  "matchers": [
    {
      "name": "instance",
      "value": "host1.example.com",
      "is_regex": false
    }
  ]
}
```

### Silence a specific alert on one instance

Use multiple matchers when the silence must be narrow.

```json
{
  "matchers": [
    {
      "name": "alertname",
      "value": "HighCPU",
      "is_regex": false
    },
    {
      "name": "instance",
      "value": "host1.example.com",
      "is_regex": false
    }
  ]
}
```

### Silence all warning CPU alerts

Use this when only a specific severity should be suppressed.

```json
{
  "matchers": [
    {
      "name": "alertname",
      "value": "HighCPU",
      "is_regex": false
    },
    {
      "name": "severity",
      "value": "warning",
      "is_regex": false
    }
  ]
}
```

### Silence critical alerts for a service

Use service labels when the same service may run on many hosts.

```json
{
  "matchers": [
    {
      "name": "service",
      "value": "billing-api",
      "is_regex": false
    },
    {
      "name": "severity",
      "value": "critical",
      "is_regex": false
    }
  ]
}
```

### Silence a group of hosts by regex

Use regular expressions for host groups or naming patterns.

```json
{
  "matchers": [
    {
      "name": "instance",
      "value": "^web-[0-9]+\\.example\\.com$",
      "is_regex": true
    }
  ]
}
```

### Silence Kubernetes pods by namespace

Use Kubernetes labels when alerts include namespace metadata.

```json
{
  "matchers": [
    {
      "name": "namespace",
      "value": "staging",
      "is_regex": false
    }
  ]
}
```

### Silence all alerts from a staging namespace except by time window

Silences do not support negative matchers. To silence staging only, match the namespace exactly and set the required time window.

```json
{
  "matchers": [
    {
      "name": "namespace",
      "value": "staging",
      "is_regex": false
    }
  ]
}
```

## Statuses

| Status | Meaning |
|---|---|
| Active | The silence is enabled and the current time is between `starts_at` and `ends_at`. |
| Scheduled | The silence is enabled, but `starts_at` is in the future. |
| Expired | The silence ended. Expired silences are hidden after the retention window by default. |
| Disabled | The silence was manually disabled and remains visible for review. |

## Expired silence history

Expired silences are hidden after they are older than the configured retention window. By default, expired silences disappear from the normal list after 30 days from `ends_at`.

Users can still search old expired silences by enabling the expired history option on the Silences page.

This keeps the default page clean while still allowing audits and troubleshooting.

## Disabled silences

Disabling a silence should not permanently delete it from the UI. A disabled silence remains visible so users can understand why a silence no longer applies.

Use disabled silences for review and audit history. Use expired silences for time-based lifecycle.

## Recommended matcher strategy

Keep silences as narrow as possible.

Prefer:

```json
{
  "matchers": [
    {
      "name": "alertname",
      "value": "DiskFull",
      "is_regex": false
    },
    {
      "name": "instance",
      "value": "host1.example.com",
      "is_regex": false
    }
  ]
}
```

Avoid broad matchers like this unless the maintenance window is intentional:

```json
{
  "matchers": [
    {
      "name": "severity",
      "value": "critical",
      "is_regex": false
    }
  ]
}
```

A broad silence can suppress unrelated incidents.

## Common labels

The exact labels depend on the incoming integration payload. Common labels include:

| Label | Example |
|---|---|
| `alertname` | `DiskFull` |
| `severity` | `critical` |
| `instance` | `host1.example.com` |
| `job` | `node-exporter` |
| `service` | `billing-api` |
| `namespace` | `production` |
| `cluster` | `prod-eu-1` |

For Alertmanager payloads, matchers usually target values from `alerts[].labels`.

For Zabbix or generic webhook payloads, use the labels that IncidentRelay stores on the resulting alert.

## Troubleshooting

If a silence does not match an alert:

1. Check the alert labels in the alert details page.
2. Confirm each matcher name exists in the alert labels.
3. Confirm exact matchers use the exact same value.
4. For regex matchers, test the expression against the actual label value.
5. Confirm the silence is active, enabled, and belongs to the same team as the alert.
6. Confirm the alert was created after the silence became active, or resend the alert if needed.

If too many alerts are silenced, narrow the matchers by adding labels such as `alertname`, `instance`, `service`, `namespace`, or `severity`.
