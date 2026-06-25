---
title: Matcher Suggestions API
description: Load known matcher names and values from recent alerts.
---

# Matcher Suggestions API

The matcher suggestions endpoint supports the shared matcher editor and can also be used by external administration tools.

```text
GET /api/matchers/suggestions
```

Authentication is required. The caller must have read access to the selected team.

## Query parameters

| Parameter | Required | Default | Description |
|---|---:|---:|---|
| `team_id` | yes | — | Team used for RBAC and alert sampling |
| `route_id` | no | — | Limit the sample to one route |
| `service_id` | no | — | Limit the sample to one service |
| `limit` | no | `200` | Recent alerts to inspect, maximum `500` |
| `values_limit` | no | `20` | Values returned per matcher name, maximum `50` |

Example:

```text
GET /api/matchers/suggestions?team_id=4&service_id=12&limit=100
```

Example response:

```json
{
  "team_id": 4,
  "route_id": null,
  "service_id": 12,
  "sample_size": 37,
  "sample_limit": 100,
  "values_limit": 20,
  "labels": {
    "alertname": ["DiskFull", "HighLatency"],
    "environment": ["production", "staging"],
    "severity": ["critical", "warning"]
  },
  "fields": {
    "source": ["alertmanager"],
    "status": ["firing", "resolved"],
    "priority": ["p1", "p3"]
  }
}
```

The endpoint returns observed values only. It does not evaluate a matcher or report which alerts would match it.
