---
title: Универсальный вебхук и PagerDuty Events API v2
description: Настройка маршрута для универсального входящего вебхука, формат payload и совместимость с PagerDuty Events API v2.
---

# Интеграция через универсальный вебхук

Маршрут Webhook принимает два формата запроса на одном и том же эндпоинте:

1. Универсальный payload вебхука IncidentRelay.
2. События алертов, совместимые с PagerDuty Events API v2.

Эндпоинт:

```text
POST /api/integrations/webhook
```

## Настройка маршрута

Создайте маршрут с:

```text
Source: Webhook / PagerDuty Events API v2
```

Привяжите необходимые каналы уведомлений и скопируйте токен приёма маршрута.

Один и тот же токен используется по-разному каждым форматом:

| Формат | Аутентификация |
|---|---|
| Универсальный вебхук IncidentRelay | `Authorization: Bearer ROUTE_TOKEN` |
| Совместимый с PagerDuty Events API v2 | JSON-поле `routing_key: ROUTE_TOKEN` |

`routing_key` трактуется как секрет. IncidentRelay использует его для выбора маршрута и сохраняет `[REDACTED]` вместо токена в payload алерта.

## Универсальный формат IncidentRelay

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/webhook' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ROUTE_TOKEN' \
  -d '{
    "status": "firing",
    "external_id": "deploy-incident-42",
    "fingerprint": "deploy-api-prod-42",
    "title": "API deploy failed",
    "message": "Deployment failed on api-prod-1",
    "severity": "critical",
    "team": "infra",
    "event_link": "https://monitoring.example.com/events/deploy-incident-42",
    "labels": {
      "service": "api",
      "environment": "prod",
      "host": "api-prod-1"
    },
    "details": {
      "deploy_id": "42",
      "region": "eu-1"
    }
  }'
```

### Универсальные нормализованные поля

| Поле IncidentRelay | Источник |
|---|---|
| `source` | `webhook` |
| `team_slug` | `team`, `labels.team` или `labels.oncall_team` |
| `external_id` | `external_id` |
| `dedup_key` | `fingerprint` или сгенерированный из источника, внешнего ID, заголовка и меток |
| `title` | `title` |
| `message` | `message` |
| `severity` | `severity` |
| `labels` | `labels` плюс вспомогательные метки, такие как `event_link` |
| `payload` | Исходный payload, с секретом `routing_key`, скрытым при наличии |
| `status` | `status`, по умолчанию `firing` |

## Формат, совместимый с PagerDuty Events API v2

Системы, у которых уже есть экспортёр PagerDuty Events API v2, могут направить его на эндпоинт вебхука IncidentRelay.

Используйте токен приёма маршрута IncidentRelay как `routing_key`.

### Trigger

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/webhook' \
  -H 'Content-Type: application/json' \
  -d '{
    "routing_key": "ROUTE_TOKEN",
    "event_action": "trigger",
    "dedup_key": "database-prod-01",
    "payload": {
      "summary": "Production database is unavailable",
      "source": "db-prod-01",
      "severity": "critical",
      "component": "postgresql",
      "group": "production",
      "class": "database",
      "custom_details": {
        "service": "database",
        "environment": "prod",
        "host": "db-prod-01"
      }
    },
    "links": [
      {
        "href": "https://monitoring.example.com/incidents/db-prod-01",
        "text": "Open monitoring"
      }
    ]
  }'
```

Успешные PagerDuty-совместимые запросы возвращают HTTP `202`:

```json
{
  "status": "success",
  "message": "Event processed",
  "dedup_key": "database-prod-01"
}
```

### Acknowledge

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/webhook' \
  -H 'Content-Type: application/json' \
  -d '{
    "routing_key": "ROUTE_TOKEN",
    "event_action": "acknowledge",
    "dedup_key": "database-prod-01"
  }'
```

Соответствующая группа алертов IncidentRelay подтверждается (acknowledged). Поиск ограничен маршрутом вебхука, идентифицированным по `routing_key`.

### Resolve

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/webhook' \
  -H 'Content-Type: application/json' \
  -d '{
    "routing_key": "ROUTE_TOKEN",
    "event_action": "resolve",
    "dedup_key": "database-prod-01"
  }'
```

Соответствующая группа алертов IncidentRelay и её дочерние алерты разрешаются.

Неизвестные или уже разрешённые значения `dedup_key` принимаются как успешные no-op-операции. Это сохраняет поведение асинхронных последующих событий, ожидаемое PagerDuty-совместимыми отправителями.

### Сопоставление полей PagerDuty

| Поле PagerDuty | Поле IncidentRelay |
|---|---|
| `routing_key` | Токен приёма маршрута вебхука; не хранится в открытом виде |
| `event_action=trigger` | `status=firing` |
| `event_action=acknowledge` | Подтвердить соответствующую группу алертов |
| `event_action=resolve` | Разрешить соответствующую группу алертов |
| `dedup_key` | `dedup_key` и `external_id` |
| `payload.summary` | `title` |
| `payload.severity` | Нормализованный severity |
| `payload.source` | Метка `source` |
| `payload.component` | Метка `component` |
| `payload.group` | Метка `group` |
| `payload.class` | Метка `class` |
| `payload.custom_details` | Скалярные значения копируются в метки; полный объект сохраняется в payload |
| Первый `links[].href` | `labels.event_link` |
| `client` | Метка `pagerduty_client` |

Severity PagerDuty нормализуется с использованием псевдонимов IncidentRelay. Например, `error` становится `critical`.

`payload.summary`, `payload.source` и `payload.severity` обязательны для `trigger`. `dedup_key` обязателен для `acknowledge` и `resolve`.

## Назначение сервиса

После того как маршрут принимает событие, IncidentRelay может привязать его к сервису двумя способами:

1. Выбрать сервис по умолчанию на маршруте.
2. Настроить правила сопоставления сервисов.

Стандартные поля PagerDuty и скалярные `custom_details` становятся метками, поэтому их можно использовать в правилах сопоставления сервисов.

Пример:

```json
{
  "labels": {
    "component": "postgresql",
    "environment": {
      "op": "regex",
      "value": "^(prod|production)$"
    }
  }
}
```

## Ссылки на события

Универсальный формат поддерживает следующие псевдонимы:

```text
event_link
event_url
alert_url
source_url
dashboard_url
runbook_url
```

Для PagerDuty-совместимых запросов первый непустой `links[].href` сохраняется как `labels.event_link`. `client_url` используется как запасной вариант.
