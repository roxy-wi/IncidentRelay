# Service Impact history

Service Impact history shows how service impact changed over time. Use it when the current Impact tab answers only part of the question and you need to understand what was affected during an incident, how long the impact lasted, or which services are repeatedly affected.

You can find it in:

```text
Services → Impact → History
```

The **Current** tab shows the live Service Impact calculation. The **History** tab shows saved snapshots of that calculation.

## What a snapshot is

A snapshot is a saved point-in-time copy of the Service Impact view. It captures the current Impact v2 calculation and stores both:

- summary counters for the whole snapshot;
- one row per service included in the calculation.

Snapshots are not new alerts and do not change service status. They are historical records used for analytics and investigation.

## How snapshots are created

Snapshots can be created in two ways:

- automatically by the scheduler;
- manually with **Capture snapshot** in the History tab.

Manual snapshots are useful before or after a maintenance window, during an incident, or after changing dependencies so you can compare the impact model later.

## What data is used to build a snapshot

A snapshot is built from the same data as **Services → Impact → Current**.

The calculation reads:

- services visible in the selected scope;
- each service's own status, such as `operational`, `degraded`, `partial_outage`, `major_outage`, `maintenance`, `disabled`, or `unknown`;
- enabled service dependencies, including dependency type and criticality;
- open alert groups linked to services;
- alert group severity and status;
- service metadata used by Impact, such as team, tier and criticality;
- the selected Impact options, such as max depth, include operational services, include disabled services, root causes, paths and blast radius.

Only open alert groups are counted for alert impact. In the current implementation, open means:

```text
firing or acknowledged
```

Resolved alert groups are historical alert data, but they do not contribute to the current impact calculation when the snapshot is captured.

## What is stored in a snapshot

The snapshot header stores overall counters, for example:

- total services in the calculation;
- affected services;
- major outage, partial outage, degraded, maintenance and unknown counts;
- services affected by their own status;
- services affected by upstream dependencies;
- services affected by alert groups;
- total open alert groups;
- total critical open alert groups;
- total upstream issues;
- cycle and depth-limit counters;
- selected filters and calculation options.

Each service row stores the service-level result, for example:

- service name, slug and team;
- service tier and criticality;
- own status;
- alert impact status;
- dependency impact status;
- effective status;
- primary reason;
- open alert group counters;
- upstream issue count;
- root causes;
- explanation;
- blast radius;
- original Impact row payload.

Names are stored together with ids so old snapshots remain readable even if a service or team is renamed later.

## How to read the History tab

The History tab contains three main areas.

### Historical affected services

This chart shows how many services were affected in each time bucket. Use it to see when impact started, when it peaked and when it returned to normal.

### Historical impact reasons

This chart shows why services were affected. Common reasons are:

- **own status** — the service itself was degraded, in outage, in maintenance or unknown;
- **alert group** — open alert groups on the service changed its impact;
- **upstream dependency** — the service was affected by a dependency;
- **disabled** — the service was disabled.

### Historically affected services

This table ranks services by how often they appeared as affected in snapshots. Use it to find noisy services, fragile dependencies, or services that repeatedly inherit impact from upstream systems.

## Choosing the time range

Use the period selector to choose the analysis window:

- last 7 days;
- last 30 days;
- last 90 days;
- last 365 days.

A shorter window is better for incident investigation. A longer window is better for trend analysis and service quality reviews.

## How access works

History follows the same service visibility rules as the current Impact view. Users only see snapshot data for teams and services they are allowed to read.

A global snapshot can still be partially visible: if it contains 100 services but the user can read only one team, the History tab shows only the rows visible to that user.

## Retention

Old snapshots are removed by retention cleanup. The default retention is intended to keep long-term operational history without growing the database forever.

Recommended defaults:

```ini
[services]
impact_snapshot_enabled = true
impact_snapshot_interval_seconds = 300
impact_snapshot_retention_days = 365
```

With these settings, IncidentRelay stores a snapshot every five minutes and keeps one year of history.

## Typical use cases

Use Service Impact history to answer questions like:

- Which services were affected during the incident yesterday?
- Did the impact come from alerts, own service status, or dependencies?
- Which service was the likely upstream source of repeated impact?
- How often is this service affected by dependencies?
- Did the dependency model improve after we changed it?
- Which teams own the most frequently affected services?

## Limitations

A snapshot is only as accurate as the service catalog at the time it is captured. If services are missing dependencies or alert groups are not linked to services, the history will not show the full impact picture.

Snapshots are periodic. If an issue starts and resolves between two scheduled snapshots, it may not appear in history unless a user captures a manual snapshot during the issue.
