# Heartbeats API

Heartbeats are managed under `/api/heartbeats`. Ping endpoints are public by token; management endpoints require normal IncidentRelay authentication.

## Create heartbeat

```http
POST /api/heartbeats
```

Required fields:

```json
{
  "team_id": 1,
  "route_id": 10,
  "name": "Prometheus Watchdog",
  "slug": "prometheus-watchdog",
  "mode": "interval",
  "expected_interval_seconds": 60,
  "grace_period_seconds": 120,
  "severity": "critical",
  "priority_slug": "p2",
  "enabled": true,
  "auto_resolve": true
}
```

`route_id` must point to an enabled route with `source=heartbeat`.

The create response includes `token` and `ping_url` once. Existing tokens are never returned again.

## Scheduled completion heartbeat

```json
{
  "team_id": 1,
  "route_id": 10,
  "service_id": 25,
  "name": "Daily revenue ETL",
  "slug": "daily-revenue-etl",
  "mode": "scheduled",
  "schedule_kind": "daily",
  "schedule_time": "03:00",
  "timezone": "UTC",
  "grace_period_seconds": 900,
  "priority_slug": "p2"
}
```

Weekly schedules use `schedule_weekday` where Monday is `0` and Sunday is `6`. Monthly schedules use `schedule_monthday` from `1` to `31`.

## Ping heartbeat

```http
GET /api/heartbeats/ping/<token>
```

or:

```http
POST /api/heartbeats/ping/<token>
Content-Type: application/json

{
  "status": "completed",
  "run_id": "revenue-etl-2026-07-07",
  "message": "Loaded revenue aggregates",
  "payload": {
    "rows_loaded": 1289340,
    "duration_seconds": 2211
  }
}
```

A ping updates `last_seen_at`, records a heartbeat event, and auto-resolves the current overdue alert when `auto_resolve=true`.

## Manual overdue check

```http
POST /api/heartbeats/check-overdue
```

The scheduler runs this automatically, but the endpoint is useful for tests and operational verification.

## Pause/resume

```http
POST /api/heartbeats/{id}/pause
POST /api/heartbeats/{id}/resume
```

Paused checks accept pings but do not create overdue alerts.

## Multi-instance heartbeat

Use instance tracking when the same job runs on many hosts or producers.

```json
{
  "team_id": 1,
  "route_id": 10,
  "name": "MySQL backup fleet",
  "slug": "mysql-backup-fleet",
  "mode": "scheduled",
  "schedule_kind": "daily",
  "schedule_time": "03:00",
  "timezone": "UTC",
  "grace_period_seconds": 900,
  "instance_tracking_enabled": true,
  "instance_key": "instance",
  "expected_instances_mode": "auto",
  "auto_discovery_ttl_days": 30
}
```

Ping with an instance value:

```http
POST /api/heartbeats/ping/<token>
Content-Type: application/json

{
  "status": "completed",
  "instance": "server-1.example.com",
  "payload": {
    "duration_seconds": 742
  }
}
```

Static mode accepts only the configured producers:

```json
{
  "instance_tracking_enabled": true,
  "instance_key": "instance",
  "expected_instances_mode": "static",
  "expected_instances": [
    "server-1.example.com",
    "server-2.example.com"
  ]
}
```

List instance state:

```http
GET /api/heartbeats/{id}/instances
```

Disable an obsolete instance:

```http
POST /api/heartbeats/{id}/instances/{instance_id}/disable
```
