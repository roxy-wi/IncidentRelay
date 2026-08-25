---
title: New Relic
description: Отправка уведомлений New Relic Alerts Workflow в IncidentRelay через нативный webhook-маршрут.
---

# Интеграция с New Relic

IncidentRelay принимает уведомления New Relic issue из **Alerts → Workflows** через нативный входящий маршрут.

Эндпоинт:

```text
POST /api/integrations/new-relic
```

## Создание маршрута IncidentRelay

Создайте маршрут:

```text
Source: New Relic
```

Для нового маршрута New Relic по умолчанию используется группировка:

```json
["new_relic_issue_id"]
```

Подключите нужные каналы уведомлений, сохраните маршрут и скопируйте его intake token.

## Настройка webhook destination в New Relic

В New Relic откройте **Alerts → Destinations**, создайте destination типа **Webhook** и укажите URL:

```text
https://incidentrelay.example.com/api/integrations/new-relic
```

Включите авторизацию **Bearer Token** и укажите intake token маршрута IncidentRelay.

Затем создайте или измените **Alerts Workflow**, выберите созданный webhook destination и используйте JSON message template:

```handlebars
{
  "issue_id": {{json issueId}},
  "title": {{json issueTitle}},
  "state": {{json state}},
  "status": {{json status}},
  "priority": {{json priority}},
  "issue_url": {{json issuePageUrl}},
  "condition_name": {{#if accumulations.conditionName}}{{json accumulations.conditionName.[0]}}{{else}}null{{/if}},
  "policy_name": {{#if accumulations.policyName}}{{json accumulations.policyName.[0]}}{{else}}null{{/if}},
  "entity_guid": {{#if entitiesData.entities.[0].id}}{{json entitiesData.entities.[0].id}}{{else}}null{{/if}},
  "entity_name": {{#if entitiesData.entities.[0].name}}{{json entitiesData.entities.[0].name}}{{else}}null{{/if}},
  "entity_type": {{#if entitiesData.types.[0]}}{{json entitiesData.types.[0]}}{{else}}null{{/if}},
  "labels": {{#if accumulations.rawTag}}{{json accumulations.rawTag}}{{else}}{}{{/if}}
}
```

Перед активацией workflow используйте **Send test notification**.

## Lifecycle и дедупликация

`issueId` — предпочтительный идентификатор. Рекомендуемый шаблон передаёт его как `issue_id`, а IncidentRelay использует его как external id и deduplication key.

Поэтому уведомления одного New Relic issue обновляют один алерт IncidentRelay, а не создают новый алерт при каждом update.

Следующие состояния считаются закрытыми:

```text
closed
resolved
recovered
inactive
```

Остальные состояния считаются `firing`. Непустой `issueClosedAt` в нативном/custom payload также переводит алерт в `resolved`.

## Severity

Приоритет/важность New Relic нормализуется стандартным механизмом IncidentRelay:

| New Relic | IncidentRelay |
|---|---|
| `CRITICAL` | `critical` |
| `HIGH` | `high` |
| `MEDIUM` | `medium` |
| `WARNING` | `warning` |
| `LOW` | `low` |

Если priority и severity отсутствуют, используется `info`.

## Labels

Рекомендуемый template отправляет `accumulations.rawTag` в `labels`. Значения тегов New Relic могут быть массивами; IncidentRelay берёт первое непустое значение, чтобы label можно было использовать в matchers.

Также добавляются служебные labels:

```text
new_relic_issue_id
new_relic_condition
new_relic_policy
new_relic_entity_guid
new_relic_entity_name
new_relic_entity_type
new_relic_priority
new_relic_state
new_relic_status
event_link
```

Label `team` или `oncall_team` может использоваться стандартным механизмом маршрутизации по команде.

## Совместимость с native Workflow payload

Normalizer также понимает распространённые поля New Relic напрямую:

```text
issueId
issueTitle
issuePageUrl
priority
state
status
accumulations.conditionName
accumulations.policyName
accumulations.rawTag
entitiesData.entities
entitiesData.types
```

Custom template всё равно рекомендуется: он делает контракт интеграции явным и упрощает диагностику.

## Тестовый запрос

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/new-relic' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ROUTE_TOKEN' \
  -d '{
    "issue_id": "issue-example-1",
    "title": "API latency is high",
    "state": "ACTIVATED",
    "status": "CREATED",
    "priority": "CRITICAL",
    "issue_url": "https://one.newrelic.com/redirects/issue/issue-example-1",
    "condition_name": "API latency",
    "policy_name": "Production API",
    "entity_name": "checkout-api",
    "labels": {
      "environment": "production",
      "service": "checkout",
      "team": "sre"
    }
  }'
```

Отправьте тот же `issue_id` со значениями:

```json
{
  "state": "CLOSED",
  "status": "CLOSED"
}
```

чтобы закрыть существующий алерт.

## Troubleshooting

- `401 Route intake token is required`: проверьте Bearer Token в New Relic webhook destination.
- `400 Route source must be new_relic`: token принадлежит маршруту с другим source.
- Open и close создают разные alerts: убедитесь, что все workflow notifications передают один и тот же `issueId` как `issue_id`.
- Не работает route/service matching: проверьте нормализованные labels в Alert details и сравните их с matcher.
- New Relic не сохраняет webhook template: используйте preview и убедитесь, что результат является валидным JSON.
