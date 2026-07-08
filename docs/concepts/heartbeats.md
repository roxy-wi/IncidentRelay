# Heartbeats

Heartbeats are dead-man-switch checks. They page when an expected success ping stops arriving.

Unlike an active HTTP/TCP check, a heartbeat proves that the producing system was able to complete its own work and deliver a signal into IncidentRelay. This is useful for monitoring paths that cannot be checked reliably from outside IncidentRelay:

- Prometheus Watchdog through Alertmanager;
- backup jobs that must finish every night;
- ETL pipelines that must send a successful completion marker;
- log shippers or agents that must report periodically;
- any cron or batch process where silence is the failure mode.

## Modes

IncidentRelay supports two heartbeat modes.

### Interval ping

The source must ping IncidentRelay every fixed interval. IncidentRelay marks the heartbeat overdue when:

```text
last_seen_at + expected_interval + grace_period < now
```

This is best for Watchdog-style alerts and agents that run continuously.

### Scheduled completion

The source must ping IncidentRelay before a scheduled deadline such as every day at `03:00` or every Monday at `08:00`. This is best for ETL, backup, billing and reporting jobs.

A scheduled heartbeat is overdue when the current expected window has passed and no successful ping was received for that window.

## Alert behavior

When a heartbeat becomes overdue, IncidentRelay creates a normal alert group with:

```text
source = heartbeat
alertname = HeartbeatOverdue
dedup_key = heartbeat:<uid>
```

The alert goes through the regular IR route, priority, escalation, notification, maintenance and service-impact pipeline. When a ping returns, IncidentRelay can automatically resolve the current overdue alert.

## Routes

Heartbeats use routes with source `heartbeat`. This keeps delivery behavior consistent with other IR alerts: the route decides notification channels, rotation or escalation policy, and optional matcher allow-lists.

## Ping URLs

Each heartbeat has a secret token and a ping URL:

```text
GET  /api/heartbeats/ping/<token>
POST /api/heartbeats/ping/<token>
```

The token is shown only when the heartbeat is created or regenerated. Store it in the producing system, not in documentation or source control.

Example:

```bash
curl -fsS https://incidentrelay.example.com/api/heartbeats/ping/<token>
```

For ETL jobs, send the ping only after successful completion and data-quality checks.
