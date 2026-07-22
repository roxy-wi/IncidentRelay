---
title: Интеграция с Sentry
description: Подписанные вебхуки Sentry для issue, метрик-алертов и жизненного цикла.
---

# Интеграция с Sentry

IncidentRelay может получать подписанные вебхуки от Sentry Internal Integrations и превращать алерты по issue, метрические алерты и события жизненного цикла issue из Sentry в алерты IncidentRelay.

Интеграция с Sentry привязана к маршруту: у каждого маршрута Sentry есть свой URL вебхука и свой секрет вебхука Sentry. Секрет хранится в настройках интеграции маршрута и никогда не возвращается API.

## Поддерживаемые события Sentry

IncidentRelay поддерживает следующие ресурсы вебхуков Sentry:

| Ресурс Sentry | Типичное действие | Статус IncidentRelay | Примечания |
| --- | --- | --- | --- |
| `event_alert` | `triggered` | `firing` | Сработало действие правила алерта по issue. |
| `metric_alert` | `critical` | `firing` | Метрический алерт перешёл в критическое состояние. |
| `metric_alert` | `warning` | `firing` | Метрический алерт перешёл в состояние предупреждения. |
| `metric_alert` | `resolved` | `resolved` | Метрический алерт восстановлен. |
| `issue` | `created` | `firing` | Событие жизненного цикла issue. |
| `issue` | `unresolved` | `firing` | Issue переоткрыт или регрессировал. |
| `issue` | `resolved` | `resolved` | Issue был разрешён в Sentry. |
| `issue` | `ignored` | `resolved` | Issue был проигнорирован или архивирован в Sentry. |

Для алертов по issue IncidentRelay использует id issue из Sentry как ключ дедупликации. Это позволяет более позднему событию `issue.resolved` разрешить тот же алерт IncidentRelay, который был создан событием `event_alert.triggered`.

## Прежде чем начать

Вам понадобится:

- команда IncidentRelay и права на управление маршрутами;
- публичный HTTPS URL для IncidentRelay, до которого может достучаться Sentry;
- права администратора или менеджера организации Sentry для создания Internal Integration;
- полностью развёрнутая реализация интеграции с Sentry, включая миграцию `integration_config`.

Не используйте устаревший Sentry Webhook Plugin для этой интеграции. Используйте Sentry Internal Integration, потому что IncidentRelay проверяет заголовок `Sentry-Hook-Signature`, отправляемый вебхуками Internal Integration.

## Шаг 1: Создайте маршрут Sentry в IncidentRelay

Откройте **Routes** и создайте новый маршрут:

| Поле | Рекомендуемое значение |
| --- | --- |
| Name | `Sentry Backend`, `Sentry Frontend` или другое понятное имя |
| Source | `Sentry` |
| Team | Команда, которой должны принадлежать алерты Sentry |
| Service | Опционально, но рекомендуется |
| Group by | `[
"project_slug",
"issue_id"
]` для алертов по issue |
| Matchers | Опциональный матчер меток, например по проекту или окружению |
| Enabled | Включено |

Пример матчеров:

```json
{
  "labels": {
    "project_slug": "backend-api",
    "environment": "production"
  }
}
```

Рекомендуемый group by для алертов по issue:

```json
["project_slug", "issue_id"]
```

Рекомендуемый group by для метрических алертов:

```json
["project_slug", "sentry_alert_id"]
```

После создания маршрута IncidentRelay показывает URL вебхука, похожий на:

```text
https://incidentrelay.example.com/api/integrations/sentry/42
```

Скопируйте этот URL. Вы вставите его в Sentry.

На этом этапе маршрут может существовать без секрета Sentry. Входящие вебхуки Sentry будут отклоняться, пока секрет не будет настроен.

## Шаг 2: Создайте Sentry Internal Integration

В Sentry откройте настройки организации и создайте Internal Integration.

Настройте:

| Настройка Sentry | Значение |
| --- | --- |
| Name | `IncidentRelay` или имя, специфичное для маршрута, например `IncidentRelay Backend` |
| Webhook URL | URL, скопированный из IncidentRelay, например `https://incidentrelay.example.com/api/integrations/sentry/42` |
| Alert Rule Action | Включено |

Включите ресурсы вебхуков, необходимые для вашего потока алертов:

- `event_alert` для правил алертов по issue Sentry;
- `metric_alert` для правил метрических алертов Sentry и событий восстановления метрик;
- `issue` для событий разрешения, игнорирования и переоткрытия жизненного цикла.

Сохраните Sentry Internal Integration.

## Шаг 3: Скопируйте Sentry Client Secret в IncidentRelay

После создания Internal Integration Sentry показывает учётные данные интеграции.

Скопируйте **Client Secret** и вставьте его в маршрут IncidentRelay:

1. Откройте маршрут Sentry в IncidentRelay.
2. Нажмите **Edit**.
3. Вставьте значение в **Sentry webhook secret**.
4. Сохраните маршрут.

IncidentRelay хранит секрет в `route.integration_config.sentry.webhook_secret` и использует его для проверки входящих вебхуков.

API предоставит только:

```json
{
  "integration_config": {
    "sentry": {
      "has_webhook_secret": true,
      "webhook_path": "/api/integrations/sentry/42"
    }
  }
}
```

Он не вернёт сырой секрет.

## Шаг 4: Добавьте IncidentRelay в правила алертов Sentry

Создайте или отредактируйте правила алертов Sentry.

Для алертов по issue:

1. Откройте проект Sentry.
2. Перейдите в **Alerts**.
3. Создайте или отредактируйте правило алерта по issue.
4. В разделе действий выберите действие интеграции IncidentRelay.
5. Сохраните правило.

Для метрических алертов:

1. Откройте проект Sentry.
2. Перейдите в **Alerts**.
3. Создайте или отредактируйте правило метрического алерта.
4. Выберите действие интеграции IncidentRelay.
5. Сохраните правило.

Когда срабатывает правило алерта Sentry, Sentry отправляет подписанный вебхук в IncidentRelay. IncidentRelay проверяет подпись и нормализует событие во внутренний алерт.

## Как работает маршрутизация

События Sentry нормализуются с `source=sentry` и метками, такими как:

```json
{
  "alertname": "SentryIssueAlert",
  "sentry_resource": "event_alert",
  "sentry_action": "triggered",
  "organization_slug": "acme",
  "project_slug": "backend-api",
  "project_name": "Backend API",
  "issue_id": "12345",
  "issue_short_id": "BACKEND-1",
  "event_id": "event-abc",
  "environment": "production",
  "level": "error",
  "sentry_url": "https://sentry.example.com/issues/12345/"
}
```

Вы можете маршрутизировать по любой из этих меток.

Распространённые примеры матчеров:

Маршрутизировать только production-алерты из проекта:

```json
{
  "labels": {
    "project_slug": "backend-api",
    "environment": "production"
  }
}
```

Маршрутизировать любой production-алерт Sentry:

```json
{
  "labels": {
    "environment": "production"
  }
}
```

Маршрутизировать только метрические алерты:

```json
{
  "labels": {
    "sentry_resource": "metric_alert"
  }
}
```

## Дедупликация и поведение разрешения

Алерты по issue используют:

```text
sentry:issue:<issue_id>
```

Метрические алерты используют:

```text
sentry:metric:<sentry_alert_id>
```

Это означает:

- повторные срабатывания алертов по issue Sentry обновляют тот же алерт IncidentRelay;
- `issue.resolved` разрешает существующий алерт IncidentRelay по тому же issue;
- `metric_alert.resolved` разрешает существующий метрический алерт;
- payload issue и метрик Sentry могут использовать разные ресурсы, при этом разрешая корректный алерт.

## Модель безопасности

Вебхуки Sentry не используют токен приёма IncidentRelay.

Вместо этого IncidentRelay проверяет:

- id маршрута из URL: `/api/integrations/sentry/{route_id}`;
- источник маршрута — `sentry`;
- маршрут и команда включены;
- `Sentry-Hook-Signature` совпадает с телом запроса и Sentry Client Secret маршрута.

Если секрет отсутствует или недействителен, вебхук отклоняется.

## Ссылки

- Sentry Integration Platform: https://docs.sentry.io/integrations/integration-platform/
- Sentry webhooks: https://docs.sentry.io/integrations/integration-platform/webhooks/
- Sentry issue alert webhooks: https://docs.sentry.io/integrations/integration-platform/webhooks/issue-alerts/
- Sentry alert rule action component: https://docs.sentry.io/integrations/integration-platform/ui-components/alert-rule-action/
