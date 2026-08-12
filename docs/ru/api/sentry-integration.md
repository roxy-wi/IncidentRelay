---
title: Sentry Integration API
description: Подписанный эндпоинт вебхука Sentry, нормализация полезной нагрузки и коды ответов.
---

# Sentry integration API

Этот документ описывает поведение бэкенд-API IncidentRelay для входящей интеграции с Sentry.

## Эндпоинт

```http
POST /api/integrations/sentry/{route_id}
```

Этот эндпоинт принимает вебхуки Sentry Internal Integration.

В отличие от интеграций Alertmanager, Zabbix и Generic Webhook, эндпоинт Sentry не использует токен приёма IncidentRelay. Аутентификация основана на идентификаторе маршрута и проверке `Sentry-Hook-Signature`.

## Обязательные заголовки

| Заголовок | Обязателен | Описание |
| --- | --- | --- |
| `Content-Type: application/json` | Да | Sentry отправляет полезные нагрузки вебхуков в формате JSON. |
| `Sentry-Hook-Signature` | Да | HMAC-подпись, сгенерированная Sentry с использованием Client Secret внутренней интеграции. |
| `Sentry-Hook-Resource` | Рекомендуется | Имя ресурса Sentry, например `event_alert`, `metric_alert`, `issue`. |

## Требования к маршруту

Маршрут, определяемый по `{route_id}`, должен:

- существовать;
- иметь `source=sentry`;
- быть включённым;
- принадлежать активной команде и активной группе;
- иметь настроенный `integration_config.sentry.webhook_secret`.

Пример сохранённой конфигурации маршрута:

```json
{
  "sentry": {
    "webhook_secret": "client-secret-from-sentry"
  }
}
```

Сериализация API не должна возвращать секрет. Она должна возвращать только:

```json
{
  "sentry": {
    "has_webhook_secret": true,
    "webhook_path": "/api/integrations/sentry/42"
  }
}
```

## Проверка подписи

IncidentRelay валидирует запрос, вычисляя дайджест HMAC-SHA256 по сырому телу запроса с использованием секрета вебхука Sentry для данного маршрута.

Псевдокод:

```python
expected = hmac.new(
    secret.encode("utf-8"),
    raw_body,
    hashlib.sha256,
).hexdigest()

valid = hmac.compare_digest(expected, request.headers["Sentry-Hook-Signature"])
```

Сырое тело запроса должно использоваться точно в том виде, в каком оно было получено.

## Коды ответов

| Статус | Ошибка | Значение |
| --- | --- | --- |
| `404` | `route_not_found` | Для `{route_id}` не существует маршрута. |
| `400` | `route_source_mismatch` | Маршрут существует, но не имеет `source=sentry`. |
| `403` | `route_disabled` | Маршрут отключён или удалён. |
| `403` | `route_team_inactive` | Команда маршрута удалена или неактивна. |
| `403` | `route_group_inactive` | Группа маршрута удалена или неактивна. |
| `409` | `sentry_secret_not_configured` | У маршрута нет Client Secret для Sentry. |
| `403` | `sentry_signature_missing` | Запрос не содержит `Sentry-Hook-Signature`. |
| `403` | `sentry_signature_invalid` | Подпись не совпадает с телом и секретом. |
| `400` | `validation_error` | Тело запроса не является корректной полезной нагрузкой Sentry в формате JSON. |

## Нормализованный вывод алерта

Нормализатор возвращает список с одним объектом алерта IncidentRelay.

Пример нормализованного вывода для `event_alert.triggered`:

```json
{
  "source": "sentry",
  "team_slug": null,
  "external_id": "12345",
  "dedup_key": "sentry:issue:12345",
  "title": "ZeroDivisionError",
  "message": "division by zero",
  "severity": "critical",
  "status": "firing",
  "labels": {
    "alertname": "SentryIssueAlert",
    "severity": "critical",
    "sentry_resource": "event_alert",
    "sentry_action": "triggered",
    "organization_slug": "acme",
    "organization_name": "Acme",
    "project_slug": "backend-api",
    "project_name": "Backend API",
    "issue_id": "12345",
    "issue_short_id": "BACKEND-1",
    "event_id": "event-abc",
    "environment": "production",
    "level": "error",
    "sentry_url": "https://sentry.example.com/issues/12345/"
  },
  "payload": {}
}
```

## Сопоставление серьёзности

| Уровень/статус Sentry | Серьёзность IncidentRelay |
| --- | --- |
| `fatal` | `critical` |
| `critical` | `critical` |
| `error` | `critical` |
| `warning` | `warning` |
| `warn` | `warning` |
| `info` | `info` |
| `debug` | `info` |
| `resolved` | `info` |
| `ok` | `info` |
| unknown | `warning` |

## Сопоставление статусов

| Ресурс/действие Sentry | Статус IncidentRelay |
| --- | --- |
| `event_alert.triggered` | `firing` |
| `metric_alert.critical` | `firing` |
| `metric_alert.warning` | `firing` |
| `metric_alert.resolved` | `resolved` |
| `issue.created` | `firing` |
| `issue.unresolved` | `firing` |
| `issue.resolved` | `resolved` |
| `issue.ignored` | `resolved` |
| `issue.archived` | `resolved` |

## Ключи дедупликации

Алерты на основе issue:

```text
sentry:issue:<issue_id>
```

Метрические алерты:

```text
sentry:metric:<sentry_alert_id>
```

Запасной вариант:

```text
make_dedup_key("sentry", external_id, title, labels)
```

## Полезная нагрузка создания/обновления маршрута

Создание маршрута без секрета разрешено, чтобы пользователь мог сначала получить URL вебхука:

```json
{
  "team_id": 1,
  "name": "Sentry Backend",
  "source": "sentry",
  "rotation_id": null,
  "escalation_policy_id": null,
  "channel_ids": [],
  "matchers": {},
  "group_by": ["project_slug", "issue_id"],
  "integration_config": {},
  "enabled": true
}
```

Сохранение секрета позже:

```json
{
  "team_id": 1,
  "name": "Sentry Backend",
  "source": "sentry",
  "rotation_id": null,
  "escalation_policy_id": null,
  "channel_ids": [],
  "matchers": {},
  "group_by": ["project_slug", "issue_id"],
  "integration_config": {
    "sentry": {
      "webhook_secret": "client-secret-from-sentry"
    }
  },
  "enabled": true
}
```

При обновлении пустой секрет Sentry означает: сохранить существующий сохранённый секрет.

Переключение маршрута с `source=sentry` на другой источник должно очищать `integration_config`.
