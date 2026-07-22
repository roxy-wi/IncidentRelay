---
title: Datadog
description: Отправка алертов и восстановлений мониторов Datadog в IncidentRelay через интеграцию Datadog Webhooks.
---

# Интеграция с Datadog

IncidentRelay принимает уведомления мониторов Datadog через нативный входящий маршрут.

Эндпоинт:

```text
POST /api/integrations/datadog
```

## Создание маршрута IncidentRelay

Создайте маршрут с параметрами:

```text
Source: Datadog
```

Прикрепите необходимые каналы уведомлений, сохраните маршрут и скопируйте его токен приёма.

## Настройка Datadog Webhooks

В Datadog откройте **Integrations → Webhooks**, создайте вебхук и укажите его URL:

```text
https://incidentrelay.example.com/api/integrations/datadog
```

Настройте пользовательские заголовки в формате JSON:

```json
{
  "Authorization": "Bearer INCIDENTRELAY_ROUTE_TOKEN"
}
```

Настройте пользовательскую полезную нагрузку JSON:

```json
{
  "alert_title": "$ALERT_TITLE",
  "text_only_msg": "$TEXT_ONLY_MSG",
  "alert_id": "$ALERT_ID",
  "alert_cycle_key": "$ALERT_CYCLE_KEY",
  "aggreg_key": "$AGGREG_KEY",
  "alert_transition": "$ALERT_TRANSITION",
  "alert_type": "$ALERT_TYPE",
  "alert_priority": "$ALERT_PRIORITY",
  "alert_scope": "$ALERT_SCOPE",
  "alert_metric": "$ALERT_METRIC",
  "event_type": "$EVENT_TYPE",
  "event_id": "$ID",
  "hostname": "$HOSTNAME",
  "link": "$LINK",
  "tags": "$TAGS",
  "date_posix": "$DATE_POSIX"
}
```

Не включайте form-кодирование. Отправляйте полезную нагрузку в формате JSON.

Добавьте упоминание вебхука в каждый монитор Datadog, который должен уведомлять IncidentRelay:

```text
@webhook-incidentrelay
```

Datadog повторяет доставку вебхука при внутренних ошибках и ответах `5xx`. Проверьте полезную нагрузку перед широким включением, поскольку клиентские ошибки `4xx` не считаются временными сбоями.

## Жизненный цикл и дедупликация

IncidentRelay использует поля в следующем порядке:

```text
ALERT_CYCLE_KEY
AGGREG_KEY
explicit dedup_key or fingerprint
generated key from monitor/event identity and scope
```

`ALERT_CYCLE_KEY` предпочтителен, поскольку Datadog сохраняет его стабильным от первоначального срабатывания до восстановления.

Сопоставление переходов:

| Переход Datadog | Статус IncidentRelay |
|---|---|
| `Triggered`, `Re-Triggered` | `firing` |
| `Warn`, `Re-Warn` | `firing` |
| `No Data`, `Re-No Data` | `firing` |
| `Renotify` | `firing` |
| `Recovered` | `resolved` |

Если `alert_transition` пропущен, `alert_type=success` трактуется как разрешённый. Остальные значения по умолчанию считаются активными (firing).

## Сопоставление важности

Явное поле `severity` имеет приоритет. В остальных случаях IncidentRelay использует приоритет монитора, а затем `ALERT_TYPE`.

| Значение Datadog | Важность IncidentRelay |
|---|---|
| `P1` или `error` | `critical` |
| `P2` | `high` |
| `P3` | `medium` |
| `P4` или `warning` | `warning` |
| `P5` или `info` | `info` |

## Метки

Теги Datadog и `ALERT_SCOPE` преобразуются в метки, пригодные для матчеров.

Пример входных данных:

```text
env:prod,service:payments,team:sre,monitor
```

Нормализованные метки:

```json
{
  "env": "prod",
  "service": "payments",
  "team": "sre",
  "monitor": "true"
}
```

IncidentRelay также добавляет метаданные-метки, такие как:

```text
datadog_alert_id
datadog_event_id
datadog_alert_cycle_key
datadog_aggreg_key
datadog_alert_transition
datadog_alert_type
datadog_alert_priority
datadog_scope
datadog_event_type
datadog_metric
host
event_link
```

Эти метки можно использовать в матчерах маршрутов, правилах сопоставления сервисов, политиках приоритетов, заглушках, политиках уведомлений и аналитике.

## Тестовый запрос

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/datadog' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ROUTE_TOKEN' \
  -d '{
    "alert_title": "[Triggered] API latency is high",
    "text_only_msg": "p95 latency exceeded 2 seconds",
    "alert_id": "1234",
    "alert_cycle_key": "cycle-1234-prod-api",
    "alert_transition": "Triggered",
    "alert_type": "error",
    "alert_priority": "P1",
    "alert_scope": "env:prod,service:api",
    "hostname": "api-01",
    "link": "https://app.datadoghq.com/monitors/1234",
    "tags": "env:prod,service:api,team:sre"
  }'
```

Отправьте ту же полезную нагрузку с:

```json
{
  "alert_transition": "Recovered"
}
```

и тем же `alert_cycle_key`, чтобы разрешить существующий алерт.

## Устранение неполадок

- `401 Route intake token is required`: проверьте пользовательский заголовок `Authorization`.
- `400 Route source must be datadog`: токен принадлежит маршруту с другим источником.
- Срабатывание и восстановление создают отдельные алерты: убедитесь, что обе полезные нагрузки содержат один и тот же непустой `ALERT_CYCLE_KEY`.
- Сопоставление сервисов не работает: проверьте нормализованные метки в деталях алерта и сравните их с матчером сервиса.
- Datadog не вызывает эндпоинт: убедитесь, что сообщение монитора включает настроенное упоминание `@webhook-...`.
