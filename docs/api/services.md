---
title: Services API
description: Service inventory, match rules, links, runbooks, impact and analytics endpoints.
---

# Services API

Service management endpoints are available under:

```text
/api/services
```

They cover:

- services;
- service match rules;
- service links;
- service runbooks;
- service dependencies;
- service analytics;
- service impact.

Services describe the logical affected system.

Routes answer how an alert entered IncidentRelay, and services answer what system is broken.

## Common service endpoints

```text
GET /api/services
POST /api/services
GET /api/services/{service_id}
PUT /api/services/{service_id}
DELETE /api/services/{service_id}
```

## Service match rules

```text
GET /api/services/match-rules
GET /api/services/{service_id}/match-rules
POST /api/services/{service_id}/match-rules
PUT /api/services/match-rules/{rule_id}
DELETE /api/services/match-rules/{rule_id}
```

## Service links and runbooks

```text
GET /api/services/links
GET /api/services/{service_id}/links
POST /api/services/{service_id}/links
GET /api/services/runbooks
GET /api/services/{service_id}/runbooks
POST /api/services/{service_id}/runbooks
```

## Analytics and impact

```text
GET /api/services/analytics
GET /api/services/impact
```

Display order for service and team names in API consumers and UI:

```text
name -> slug -> "-"
```

## Service impact v2

```text
GET /api/services/impact
GET /api/services/{service_id}/impact
```

Returns current computed service impact.

Impact is a point-in-time calculation. It answers:

- what is affected right now;
- why it is affected;
- which service is the root cause;
- how dependency impact propagated;
- which downstream services can be affected by this service.

Query parameters:

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `team_id` | integer | `null` | Limit impact to one team. |
| `service_id` | integer | `null` | Return impact for one service while still calculating the readable dependency graph. |
| `include_disabled` | boolean | `false` | Include disabled services. |
| `include_operational` | boolean | `true` | Include operational services. |
| `include_explanation` | boolean | `true` | Include human-readable explanation. |
| `include_root_causes` | boolean | `true` | Include root cause services. |
| `include_blast_radius` | boolean | `true` | Include downstream blast radius. |
| `include_paths` | boolean | `true` | Include dependency paths. |
| `max_depth` | integer | `5` | Dependency traversal depth, clamped by validation. |
| `limit` | integer | `100` | Maximum returned items. |
| `sort` | string | `effective_status` | One of `service`, `status`, `effective_status`, `blast_radius`, `criticality`, `tier`. |
| `order` | string | `desc` | `asc` or `desc`. |

Response:

```json
{
  "version": 2,
  "items": [
    {
      "service_id": 42,
      "service_slug": "billing-api",
      "service_name": "Billing API",
      "team_id": 7,
      "team_slug": "payments",
      "team_name": "Payments",
      "own_status": "operational",
      "alert_impact_status": "operational",
      "dependency_impact_status": "major_outage",
      "effective_status": "major_outage",
      "primary_reason": "upstream_dependency",
      "open_alert_groups": 0,
      "critical_open_alert_groups": 0,
      "upstream_issues_count": 1,
      "root_causes": [
        {
          "service_id": 10,
          "service_slug": "postgresql-prod",
          "service_name": "PostgreSQL Prod",
          "reason": "alert_group",
          "status": "operational",
          "effective_status": "major_outage",
          "severity": "critical",
          "open_alert_groups": 1,
          "critical_open_alert_groups": 1,
          "path": []
        }
      ],
      "explanation": {
        "primary_reason": "upstream_dependency",
        "primary_source_service_id": 10,
        "primary_source_service_slug": "postgresql-prod",
        "primary_source_service_name": "PostgreSQL Prod",
        "title": "Billing API is impacted by PostgreSQL Prod",
        "message": "The effective status is major_outage because an upstream dependency is unhealthy.",
        "rules": [],
        "paths": []
      },
      "blast_radius": {
        "direct_downstream": 2,
        "transitive_downstream": 5,
        "critical_downstream": 3,
        "tier_1_downstream": 2,
        "affected_downstream": 5,
        "paths": [],
        "cycle_detected": false,
        "depth_limited": false
      },
      "cycle_detected": false,
      "depth_limited": false
    }
  ],
  "summary": {
    "total": 1,
    "affected": 1,
    "critical": 1,
    "by_effective_status": {
      "major_outage": 1
    },
    "cycle_detected": 0,
    "depth_limited": 0
  },
  "filters": {
    "team_id": null,
    "service_id": null,
    "include_disabled": false,
    "include_operational": true,
    "max_depth": 5,
    "limit": 100,
    "sort": "effective_status",
    "order": "desc"
  }
}
```

Important notes:

- Impact v2 is based on `AlertGroup`, not raw `Alert` events.
- `service_id` filters returned items only. The dependency graph is still calculated using readable services in scope.
- `root_causes` explains where the impact started.
- `explanation.paths` explains how impact propagated.
- `blast_radius` explains which downstream services can be affected.

## Service analytics v2

```text
GET /api/services/analytics
```

Returns historical service analytics for a selected time window.

Analytics answers:

- how many grouped alerts happened in the period;
- how many raw alerts were received;
- which services are noisy;
- current impact for each service;
- maintenance suppression counters;
- response-time metrics when timestamp fields are available.

Query parameters:

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `team_id` | integer | `null` | Limit analytics to one team. |
| `service_id` | integer | `null` | Return analytics for one service while still calculating impact using the readable dependency graph. |
| `days` | integer | `30` | Analytics window, `1..365`. |
| `include_disabled` | boolean | `false` | Include disabled services. |
| `include_operational` | boolean | `true` | Include operational services. |
| `include_series` | boolean | `true` | Include daily time series. |
| `include_noise` | boolean | `true` | Include raw alert/noise metrics. |
| `include_response` | boolean | `true` | Include MTTA/MTTR fields when available. |
| `include_maintenance` | boolean | `true` | Include maintenance suppression counters. |
| `include_impact` | boolean | `true` | Include current Impact v2 widget per service. |
| `limit` | integer | `100` | Maximum returned items. |
| `sort` | string | `open_alert_groups` | One of `service`, `open_alert_groups`, `critical_open_alert_groups`, `raw_alerts`, `dedup_ratio`, `mtta`, `mttr`, `blast_radius`. |
| `order` | string | `desc` | `asc` or `desc`. |

Response:

```json
{
  "version": 2,
  "window": {
    "days": 30,
    "since": "2026-05-09T00:00:00Z",
    "until": "2026-06-08T00:00:00Z"
  },
  "items": [
    {
      "service_id": 42,
      "service_slug": "billing-api",
      "service_name": "Billing API",
      "team_id": 7,
      "team_slug": "payments",
      "team_name": "Payments",
      "service_status": "operational",
      "service_criticality": "critical",
      "service_environment": "production",
      "service_tier": "tier_1",
      "enabled": true,
      "alert_groups": {
        "total": 12,
        "open": 3,
        "firing": 2,
        "acknowledged": 1,
        "resolved": 8,
        "silenced": 1,
        "critical_open": 1,
        "by_status": {},
        "by_severity": {},
        "first_seen_at": "2026-05-12T10:00:00Z",
        "last_seen_at": "2026-06-08T08:00:00Z"
      },
      "noise": {
        "raw_alerts": 240,
        "alert_groups": 12,
        "dedup_ratio": 20.0,
        "top_alertnames": [
          {
            "alertname": "BillingApiDown",
            "count": 120
          }
        ]
      },
      "response": {
        "acknowledged_groups": 4,
        "resolved_groups": 8,
        "mtta_seconds_avg": null,
        "mtta_seconds_p50": null,
        "mtta_seconds_p95": null,
        "mttr_seconds_avg": null,
        "mttr_seconds_p50": null,
        "mttr_seconds_p95": null
      },
      "maintenance": {
        "windows": 2,
        "suppressed_alert_groups": 5
      },
      "impact": {
        "effective_status": "major_outage",
        "primary_reason": "upstream_dependency",
        "upstream_issues_count": 1,
        "root_causes": 1,
        "blast_radius": {
          "direct_downstream": 2,
          "transitive_downstream": 5,
          "critical_downstream": 3,
          "tier_1_downstream": 2
        }
      },
      "last_alert_at": "2026-06-08T08:00:00Z"
    }
  ],
  "summary": {
    "services": 1,
    "affected_services": 1,
    "open_alert_groups": 3,
    "critical_open_alert_groups": 1,
    "raw_alerts": 240,
    "by_effective_status": {
      "major_outage": 1
    },
    "top_noisy_services": []
  },
  "series": {
    "alert_groups_by_day": [],
    "raw_alerts_by_day": [],
    "impact_by_day": []
  },
  "filters": {
    "team_id": null,
    "service_id": null,
    "days": 30,
    "include_disabled": false,
    "include_operational": true,
    "include_series": true,
    "include_noise": true,
    "include_response": true,
    "include_maintenance": true,
    "include_impact": true,
    "limit": 100,
    "sort": "open_alert_groups",
    "order": "desc"
  }
}
```

Important notes:

- Analytics v2 is period-based.
- `AlertGroup` is used for grouped operational analytics.
- raw `Alert` is used for noise and raw alert volume.
- Impact inside analytics is a current Impact v2 widget, not historical impact.
- `series.impact_by_day` is reserved for future impact snapshot history.

