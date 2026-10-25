---
title: OpenSearch Alerting
description: Приём уведомлений OpenSearch Alerting через Custom Webhook.
---

# Интеграция с OpenSearch Alerting

IncidentRelay принимает JSON из **OpenSearch Alerting** на endpoint:

```text
POST /api/integrations/opensearch
```

Это источник технических алертов, **не** Change Events и не интеграция с CI/CD.

## Настройка

1. Создайте Route с источником **OpenSearch Alerting** и привяжите команду,
   необходимые каналы уведомлений, ротацию и сервис.
2. Скопируйте intake token маршрута.
3. В OpenSearch **Notifications** создайте канал типа **Custom webhook** с URL
   `https://incidentrelay.example.com/api/integrations/opensearch`.
4. Добавьте заголовки:

   ```text
   Content-Type: application/json
   Authorization: Bearer <route-intake-token>
   ```

5. В **Alerting → Monitors → Triggers → Actions** выберите канал и задайте
   шаблон тела сообщения (пример для query-level monitor):

   ```json
   {
     "monitor_id": "{{ctx.monitor.id}}",
     "trigger_id": "{{ctx.trigger.id}}",
     "severity": "{{ctx.trigger.severity}}",
     "status": "ACTIVE"
   }
   ```

   Для bucket-level монитора передавайте стабильный `bucket_key` для каждой
   корзины отдельным webhook. Если добавляете имена и текст через Mustache,
   убедитесь, что они корректно экранируются как JSON.

## Дедупликация и восстановление

Идентичность сигнала: `monitor_id + trigger_id + bucket_key` с учётом токена
маршрута. Изменение текста, severity, заголовка и `alert_id` не создаёт нового
ключа. Уровни OpenSearch `1`–`5` соответствуют critical/high/medium/warning/info.

`ACTIVE` обрабатывается как firing. Явное `COMPLETED`, `recovered` или
`resolved` — как resolved. Для восстановления нужно отдельное сообщение с теми
же идентификаторами. **Не все виды OpenSearch мониторов предоставляют
автоматическую отправку recovery-события**. В bucket-level сценариях можно
использовать `ctx.completedAlerts` для генерации таких сообщений в поддерживаемых
режимах. Отсутствие событий никогда не считается восстановлением.

В новых версиях OpenSearch каналы Notifications заменяют старые Destinations.
Помните, что OpenSearch может хранить заголовки Custom webhook в открытом виде
внутри кластера; защищайте и периодически обновляйте токен.

Документация: [OpenSearch Alerting actions](https://docs.opensearch.org/latest/observing-your-data/alerting/actions/).
