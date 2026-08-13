---
title: Каналы уведомлений на основе вебхуков
description: Discord, Microsoft Teams и универсальные каналы на вебхуках.
---

# Каналы уведомлений на основе вебхуков

Каналы уведомлений на основе вебхуков отправляют исходящие HTTP-запросы во внешние сервисы.

На этой странице рассматриваются:

```text
discord
teams
webhook
```

Не путайте исходящие каналы-вебхуки с входящей [интеграцией через универсальный вебхук](generic-webhook.md).

У Slack также есть режим доставки через входящий webhook, но настройка Slack, действия Bot API и Socket Mode описаны отдельно: [Канал Slack](slack.md).

## Discord

Канал Discord использует URL вебхука Discord.

Типовая конфигурация:

```json
{
  "webhook_url": "https://discord.com/api/webhooks/..."
}
```

## Microsoft Teams

Канал Microsoft Teams использует URL вебхука Teams.

Типовая конфигурация:

```json
{
  "webhook_url": "https://..."
}
```

## Универсальный исходящий вебхук

Универсальный исходящий вебхук отправляет полезную нагрузку уведомлений IncidentRelay на произвольный HTTP-эндпоинт.

Типовая конфигурация:

```json
{
  "webhook_url": "https://example.com/incidentrelay/notifications"
}
```

## Фильтр по важности

Все каналы на основе вебхуков поддерживают `notify_on_severities`:

```json
{
  "webhook_url": "https://example.com/hook",
  "notify_on_severities": ["critical", "high"]
}
```
