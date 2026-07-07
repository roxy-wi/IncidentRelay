---
title: Services
description: Service inventory, ownership, dependencies, impact and analytics.
---

# Services

Services represent technical systems affected by alerts: APIs, websites, databases, queues, workers, cron jobs, infrastructure components, external dependencies and other logical systems.

A service is owned by a team and can be connected to routes, rotations, escalation policies, links, runbooks, dependencies, maintenance windows, impact calculations and analytics.

## Why services exist

Routes answer where an incoming alert should go. Services answer what is affected.

This separation makes it possible to:

- group alerts by affected system;
- show service-specific runbooks and links;
- calculate dependency impact;
- understand blast radius;
- build analytics by affected system;
- connect incidents and maintenance windows to technical systems.

## Service metadata

Common service fields:

- name and slug;
- owning team;
- type, environment, criticality and tier;
- current status and status message;
- default rotation and escalation policy;
- labels, tags and metadata;
- enabled/disabled state.

## Service links

Service links attach useful URLs to a service:

- dashboards;
- metrics;
- logs;
- traces;
- repositories;
- documentation;
- status pages;
- wiki pages.

Links help responders move from an alert or incident to the correct operational context.

## Runbooks

Runbooks attach response instructions to a service.

Runbooks can include optional matchers so a service can have generic and alert-specific instructions.

Example use cases:

- database outage procedure;
- API latency investigation;
- queue backlog mitigation;
- deployment rollback steps.

## Dependencies

Dependencies describe relationships between services.

A dependency has:

  * `depends_on_service_id`
  * `dependency_type` — `hard`, `soft`, `external`, `informational`
  * `criticality` — `required`, `important`, `optional`
  * `correlation_enabled` — whether this dependency can be used for alert correlation.
  * `propagation_delay_seconds` — expected delay window for related alerts.

Dependencies are used by service impact views to show whether a service may be affected by upstream incidents.

Dependencies can also be used for dependency-aware alert correlation. Correlation stores relationships between active alert groups, adds possible root cause / downstream impact context to notifications and writes correlation lifecycle events to alert timelines.

Read more: [Dependency-aware Alert Correlation](alert-correlation.md).

## Service Impact v2

Service Impact v2 calculates the current effective status for every readable service.

Impact combines:

- the service own status and own status score;
- open grouped alerts scored by incident priority, with severity as fallback;
- upstream dependency impact propagated through dependency multipliers;
- disabled state;
- cycle and depth-limit detection.

Impact is intentionally based on `AlertGroup`, not raw alert events. A grouped alert represents the operational state that users acknowledge, resolve, silence and investigate.

Each impact item contains:

- `own_status` and `own_impact_score` — the service status itself;
- `alert_impact_status` and `alert_impact_score` — impact caused by open grouped alerts;
- `dependency_impact_status` and `dependency_impact_score` — impact propagated from upstream services;
- `effective_status` and `effective_impact_score` — the final computed status and score;
- `primary_reason` — why the final status was selected;
- `root_causes` — services where the problem originated;
- `explanation` — human-readable explanation and dependency paths;
- `blast_radius` — downstream services that can be affected by this service.

### Root causes

A root cause is the service where impact started.

Examples:

- a service with a critical firing alert group;
- a service with manual `major_outage` own status;
- a disabled service;
- a service in maintenance status.

Downstream services reference the same root cause through dependency paths.

### Dependency paths

A dependency path explains how impact propagated.

Example:

```text
Frontend Web -> Billing API -> PostgreSQL Prod
```

If `PostgreSQL Prod` has a critical firing alert group and `Billing API` depends on it as `hard / required`, `Billing API` can become `major_outage`.

If `Frontend Web` depends on `Billing API` as `soft / important`, the propagated score is reduced by the dependency multiplier and can become `partial_outage` instead of `major_outage`.

### Alert impact scoring

Open grouped alerts are scored in this order:

```text
explicit incident priority -> impact score
else alert severity -> impact score
```

Default `p3` fields without a resolved priority record or manual priority flag are treated as unset, so old/raw alerts can still fall back to severity. Once priority is explicitly resolved or manually set, priority becomes the authoritative signal.

Default scores:

| Signal | Score | Typical status |
|---|---:|---|
| P1 | 100 | major_outage |
| P2 | 75 | partial_outage |
| P3 | 45 | degraded |
| P4 | 20 | operational with low impact score |
| P5 | 5 | operational with informational impact |
| severity=critical | 80 | major_outage |
| severity=high/error | 65 | partial_outage |
| severity=warning | 40 | degraded |

### Dependency impact scoring

Dependency propagation multiplies the upstream effective score. Examples:

| Dependency | Multiplier |
|---|---:|
| hard / required | 1.00 |
| hard / important | 0.85 |
| soft / required | 0.75 |
| soft / important | 0.55 |
| external / optional | 0.20 |
| informational | 0.00 |

A hard required dependency on an upstream `major_outage` keeps score 100. A soft important dependency on score 100 becomes score 55 and maps to `partial_outage`.

### Blast radius

Blast radius answers the reverse question:

```text
Which downstream services can be affected if this service is unhealthy?
```

It contains:

- direct downstream count;
- transitive downstream count;
- critical downstream count;
- tier 1 downstream count;
- optional paths;
- cycle/depth flags.

## Service Analytics v2

Service Analytics v2 is historical and period-based.

It answers:

- which services had the most grouped alerts;
- which services are noisy by raw alert count;
- which services have open or critical open alert groups;
- which services are currently affected by impact;
- which services have maintenance suppression activity;
- response metrics such as MTTA/MTTR when timestamp fields are available.

Analytics uses two alert layers:

| Layer | Purpose |
| --- | --- |
| `AlertGroup` | Grouped operational analytics: open, firing, acknowledged, resolved, silenced, critical open. |
| `Alert` | Raw/noise analytics: raw alert count, dedup ratio, top alertnames. |

### Impact vs Analytics

Impact and Analytics answer different questions.

| Feature | Question | Time model |
| --- | --- | --- |
| Impact v2 | What is affected right now and why? | Current computed state |
| Analytics v2 | What happened during the selected period? | Historical window |

Analytics includes a current Impact v2 widget per service, but this is not historical impact. Historical impact trends require impact snapshots and are reserved under `series.impact_by_day`.

## Service details

The service details panel uses an aggregated details endpoint:

```text
GET /api/services/{service_id}/details
```

The response is designed as an expandable contract for operators and analytics. It contains:

- service metadata and permissions;
- grouped alert summary based on `AlertGroup`;
- current Impact v2 block;
- active or upcoming maintenance windows;
- service links;
- runbooks;
- upstream and downstream dependencies;
- recent service status history;
- a versioned `analytics` block.

The `analytics` block is intentionally versioned. New widgets such as MTTR, noise, acknowledgement latency, incident count, SLO burn rate or raw alert event volume should be added under `analytics.widgets`, `analytics.breakdowns`, `analytics.series` or `analytics.extensions` instead of changing existing fields.
