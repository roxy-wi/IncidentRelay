---
title: Data Retention
description: Configure automatic retention for resolved alert history and diagnostic traces.
---

# Data Retention

IncidentRelay 2.1 adds a single retention policy section for database records that can grow continuously over time.

Retention of resolved alert history is disabled by default. Configure it in `[retention]`:

```ini
[retention]
alert_days = 30
# explain_trace_days = 30
# orchestration_execution_days = 30
cleanup_interval_seconds = 86400
batch_size = 500
```

| Option | Default | Description |
|---|---:|---|
| `alert_days` | `0` | Days to retain resolved alert groups and alerts. `0` keeps them indefinitely. |
| `explain_trace_days` | `alert_days` | Optional Explain Trace override. An explicit `0` keeps standalone traces indefinitely; traces linked to deleted alert history are still removed by cascade. |
| `orchestration_execution_days` | `alert_days` | Optional retention override for general Event Orchestration execution traces. An explicit `0` keeps them indefinitely. |
| `cleanup_interval_seconds` | `86400` | How often the single retention scheduler job runs. |
| `batch_size` | `500` | Maximum number of alert groups or standalone alerts deleted in one transaction. |

If `explain_trace_days` or `orchestration_execution_days` is omitted, it inherits `alert_days`. This makes one setting sufficient for the usual case while still allowing shorter or longer diagnostic retention when required.

## Alert history

Alert retention starts at `resolved_at`, not alert creation time. A group is eligible only when:

- the alert group status is `resolved`;
- `resolved_at` is older than the retention cutoff;
- every alert still attached to the group is also `resolved`.

When an eligible group is deleted, its dependent history is deleted through database foreign-key cascades. This includes alert lifecycle events, comments, notification delivery records, responder and stakeholder state, silence/maintenance applications, correlation rows, Explain Trace records, and other group-owned records. Alerts contained by the group are deleted explicitly before the group itself.

Old standalone alerts with no group are also removed when their status is `resolved` and their `resolved_at` is older than the cutoff.

Active, acknowledged, silenced, reactivated, or otherwise non-terminal incidents are never selected by this cleanup. Audit log records are retained because they intentionally store scalar object identifiers rather than owning alert records.

## Explain Trace

Explain Trace inherits `alert_days` unless `explain_trace_days` is explicitly configured. For example:

```ini
[retention]
alert_days = 90
explain_trace_days = 30
```

Here resolved alert history is retained for 90 days while standalone Explain Trace records are pruned after 30 days. A trace linked to alert history is always removed when its owning alert/group is deleted, even if the trace-specific period is longer.

## Event Orchestration execution traces

General Event Orchestration execution traces inherit `alert_days` unless `orchestration_execution_days` is configured. The existing special retention rules for dropped events, terminal pending events, and webhook executions remain independent and may remove those records earlier.

## Scheduler behavior

IncidentRelay uses one `retention_cleanup_job` and one distributed database lock for the 2.1 retention pass. A run performs alert-history cleanup, Explain Trace cleanup, and Event Orchestration retention cleanup together.

Deletion of alert history is batched to avoid one very large transaction. For SQLite and PostgreSQL, deleting rows makes database pages reusable by future writes but does not necessarily shrink the database file immediately. Returning already allocated disk space to the operating system should use the database engine's normal maintenance procedure during an appropriate maintenance window.

## Upgrade from 2.0

New configuration should use only `[retention]`.

For compatibility, IncidentRelay 2.1 still reads the old `[alerts] alert_explain_trace_retention_days` value when `retention.explain_trace_days` is absent. It also accepts the previous cleanup interval settings as fallbacks when `retention.cleanup_interval_seconds` is absent. New `[retention]` values always take precedence.
