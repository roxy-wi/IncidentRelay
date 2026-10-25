---
title: Kibana Alerting
description: Приём алертов Kibana через Webhook connector.
---

# Интеграция с Kibana Alerting

Kibana отправляет JSON на endpoint:

```text
POST /api/integrations/kibana
```

## Настройка

1. Создайте Route с источником **Kibana Alerting**, задайте команду и каналы,
   скопируйте intake token.
2. В **Stack Management → Connectors** создайте Webhook connector с методом
   `POST` и URL `https://incidentrelay.example.com/api/integrations/kibana`.
3. В заголовках укажите:

   ```text
   Content-Type: application/json
   Authorization: Bearer <route-intake-token>
   ```

4. В правиле Kibana выберите **For each alert** (не summary) и добавьте
   webhook action со следующим JSON:

   ```json
   {
     "rule_id": "{{rule.id}}",
     "alert_id": "{{alert.id}}",
     "space_id": "{{rule.spaceId}}",
     "rule_name": "{{rule.name}}",
     "message": "{{context.reason}}",
     "rule_url": "{{rule.url}}",
     "status": "active"
   }
   ```

5. **Для восстановления добавьте отдельный recovery action** с теми же
   `rule_id`, `alert_id`, `space_id` и значением `"status": "recovered"`.
   Наличие recovery action и доступных переменных зависит от типа правила.

Дедупликация использует `space_id + rule_id + alert_id` и маршрут. `active`
означает firing, `recovered` — resolved. Повторные уведомления изменяют один
дочерний Alert, а отсутствие webhook не означает восстановление.

Дополнительные поля: `labels`, `team`, `severity`, `title`, `message`,
`rule_url`, `flapping`, `action_group`. Для некоторых правил
`context.reason` отсутствует — соответствующее поле можно убрать.

Обрабатываются только события **с идентификаторами конкретного alert**;
summary без `rule_id` и `alert_id` не поддерживается.

Подробнее: [Kibana rule action variables](https://www.elastic.co/docs/explore-analyze/alerting/alerts/rule-action-variables).
