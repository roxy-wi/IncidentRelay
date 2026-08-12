# Heartbeats API

Heartbeat'ы управляются по пути `/api/heartbeats`. Эндпоинты ping публичны и защищены токеном; эндпоинты управления требуют обычной аутентификации IncidentRelay.

## Создание heartbeat

```http
POST /api/heartbeats
```

Обязательные поля:

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

`route_id` должен указывать на включённый маршрут с `source=heartbeat`.

Ответ на создание один раз включает `token` и `ping_url`. Существующие токены больше никогда не возвращаются.

## Heartbeat завершения по расписанию

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

Недельные расписания используют `schedule_weekday`, где понедельник — `0`, а воскресенье — `6`. Месячные расписания используют `schedule_monthday` от `1` до `31`.

## Ping heartbeat

```http
GET /api/heartbeats/ping/<token>
```

или:

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

Ping обновляет `last_seen_at`, записывает событие heartbeat и автоматически разрешает текущий просроченный алерт, когда `auto_resolve=true`.

## Ручная проверка просроченных

```http
POST /api/heartbeats/check-overdue
```

Планировщик запускает её автоматически, но эндпоинт полезен для тестов и операционной проверки.

## Пауза/возобновление

```http
POST /api/heartbeats/{id}/pause
POST /api/heartbeats/{id}/resume
```

Приостановленные проверки принимают ping'и, но не создают просроченных алертов.

## Мультиинстансный heartbeat

Используйте отслеживание инстансов, когда одна и та же задача выполняется на многих хостах или производителях.

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

Ping со значением инстанса:

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

Статический режим принимает только настроенных производителей:

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

Список состояний инстансов:

```http
GET /api/heartbeats/{id}/instances
```

Отключить устаревший инстанс:

```http
POST /api/heartbeats/{id}/instances/{instance_id}/disable
```
