# Трассировка объяснения алерта

Трассировка объяснения алерта (explain trace) фиксирует, как IncidentRelay обработал входящий алерт.

Она полезна, когда нужно понять, почему алерт был направлен в конкретную команду, сгруппирован в существующий инцидент, подавлен обслуживанием или заглушкой либо отклонён, потому что ни один маршрут не совпал.

## Когда создаются трассировки

IncidentRelay создаёт трассировку объяснения для каждого входящего алерта, обработанного функцией `upsert_alert()`.

Трассировка создаётся как для успешных, так и для остановленных путей обработки:

- группа алертов создана
- группа алертов переиспользована
- алерт обновлён
- алерт разрешён
- маршрутизация не удалась
- инцидент подавлен
- разрешённый алерт-сирота проигнорирован
- совпало обслуживание
- уведомление запланировано или подавлено

## Ответ Ingest API

Эндпоинты интеграций включают `trace_id` в ответ по каждому обработанному алерту.

Пример успешного ответа:

```json
[
  {
    "created": true,
    "id": 123,
    "group_id": 123,
    "alert_id": 456,
    "status": "firing",
    "outcome": "created",
    "processing_status": "completed",
    "reason": null,
    "trace_id": "4fd2a8c9-8c2f-44e8-96fd-77b7f03e72f2",
    "routing_error": null,
    "team_id": 1,
    "team_slug": "infra",
    "route_id": 10,
    "rotation_id": null,
    "assignee": null
  }
]
```

Пример ответа при неудачной маршрутизации:

```json
[
  {
    "created": false,
    "id": null,
    "group_id": null,
    "alert_id": null,
    "status": "firing",
    "outcome": "routing_failed",
    "processing_status": "stopped",
    "reason": "Alert did not match any active route.",
    "trace_id": "a1e26edb-5989-4a17-bf70-cf73154c2412",
    "routing_error": "Alert did not match any active route.",
    "team_id": null,
    "team_slug": null,
    "route_id": null,
    "rotation_id": null,
    "assignee": null
  }
]
```

Если маршрутизация не удалась для всех алертов в запросе, API возвращает HTTP `400`.

Если пакет содержит одновременно успешные и неуспешные элементы, API возвращает HTTP `207`.

## Эндпоинты API

### Список трассировок для группы алертов

```http
GET /api/alerts/{alert_group_id}/explain
```

Возвращает трассировки объяснения, связанные с существующей группой алертов.

Пример ответа:

```json
[
  {
    "id": 12,
    "trace_id": "4fd2a8c9-8c2f-44e8-96fd-77b7f03e72f2",
    "mode": "live",
    "group_id": 123,
    "alert_id": 456,
    "source": "alertmanager",
    "dedup_key": "disk-full-host1",
    "status": "completed",
    "outcome": "created",
    "reason": null,
    "input_summary": {},
    "result": {},
    "started_at": "2026-06-19T17:00:00",
    "finished_at": "2026-06-19T17:00:01",
    "steps": []
  }
]
```

### Получить одну трассировку с шагами

```http
GET /api/alerts/explain/{trace_id}
```

Возвращает одну трассировку с упорядоченными шагами обработки.

Пример ответа:

```json
{
  "id": 12,
  "trace_id": "4fd2a8c9-8c2f-44e8-96fd-77b7f03e72f2",
  "mode": "live",
  "group_id": 123,
  "alert_id": 456,
  "source": "alertmanager",
  "dedup_key": "disk-full-host1",
  "status": "completed",
  "outcome": "created",
  "reason": null,
  "input_summary": {},
  "result": {},
  "started_at": "2026-06-19T17:00:00",
  "finished_at": "2026-06-19T17:00:01",
  "steps": [
    {
      "id": 100,
      "position": 1,
      "stage": "intake",
      "code": "alert_received",
      "status": "success",
      "title": "Alert received",
      "message": null,
      "data": {},
      "created_at": "2026-06-19T17:00:00"
    }
  ]
}
```

## Интерфейс

Существующие группы алертов показывают данные объяснения в модальном окне деталей алерта.

Откройте:

```text
Alerts -> alert row -> Details -> Explain
```

Для трассировок, не связанных с группой алертов, например при неудачной маршрутизации, используйте:

```text
Alerts -> Explain trace
```

Вставьте `trace_id` из ответа Ingest API.

Также можно открыть трассировку напрямую по прямой ссылке:

```text
/alerts?trace_id=<trace_id>
```

или:

```text
/alerts?explain_trace_id=<trace_id>
```

После открытия трассировки параметр запроса удаляется из URL в браузере.

## Управление доступом

Трассировки, связанные с группой алертов, используют те же проверки доступа на чтение, что и группа алертов.

Трассировки-сироты — это трассировки без `group_id`. Их могут читать только администраторы.

## Хранение

Трассировки объяснения автоматически очищаются планировщиком.

Срок хранения по умолчанию:

```ini
[alerts]
alert_explain_trace_retention_days = 30
```

Интервал очистки по умолчанию:

```ini
[scheduler]
alert_explain_trace_cleanup_interval_seconds = 86400
```

Задайте для `alert_explain_trace_retention_days` положительное целое число.

## Устранение неполадок

### Ingest возвращает routing_failed

Откройте возвращённый `trace_id` и проверьте наличие:

- `alert_received`
- `route_not_matched`

Обычно это означает, что источник алерта, команда, матчеры маршрута, метки или состояние маршрута не совпадают с входящей полезной нагрузкой.

### Трассировка существует, но без группы алертов

Это ожидаемо для остановленных путей обработки, например:

- маршрутизация не удалась
- инцидент подавлен
- получен разрешённый алерт без существующей активной (firing) группы

### Вкладка Explain в деталях алерта пуста

Убедитесь, что у группы алертов есть хотя бы одна связанная трассировка:

```http
GET /api/alerts/{alert_group_id}/explain
```

Если возвращается пустой список, группа алертов, вероятно, была создана до включения Explain Trace.
