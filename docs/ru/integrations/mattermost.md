---
title: Канал Mattermost
description: Настройка уведомлений Mattermost через webhook и Bot API.
---

# Канал Mattermost

Mattermost — это исходящий канал уведомлений.

IncidentRelay поддерживает два стиля доставки в Mattermost:

1. Режим входящего вебхука.
2. Режим Bot API с интерактивными кнопками и обновлениями сообщений.

Режим Bot API рекомендуется, когда вам нужны действия ACK/Resolve/Shelve.

## Режим входящего вебхука

Используйте этот режим, когда вам нужны только односторонние уведомления.

Типичная конфигурация:

```json
{
  "webhook_url": "https://mattermost.example.com/hooks/..."
}
```

## Режим Bot API

Используйте этот режим для:

- кнопка Acknowledge;
- кнопка Resolve;
- кнопки Shelve 1h / Unshelve;
- обновления сообщений после ACK/Resolve/Shelve;
- лучшей атрибуции пользователей.

Типичные поля конфигурации:

```json
{
  "base_url": "https://mattermost.example.com",
  "bot_token": "...",
  "channel_id": "...",
  "callback_secret": "change-me"
}
```

Правильно задайте `[server] public_base_url`, потому что кнопкам нужны URL колбэков, доступные для Mattermost.

## Mattermost user ID

У пользователя в профиле может быть Mattermost user ID. Это полезно для атрибуции, когда пользователь нажимает кнопки ACK/Resolve/Shelve.

## Кнопка теста

Тест канала отправляет тестовое уведомление через настроенный канал Mattermost. Он не доказывает, что реальный маршрут алерта совпадёт или что фильтры важности разрешат алерт.

## Устранение неполадок

Проверьте:

1. Канал включён.
2. Канал привязан к сопоставленному маршруту.
3. Фильтр важности разрешает уровень важности алерта.
4. Bot token или webhook URL корректны.
5. `public_base_url` доступен из Mattermost для кнопок.

## Shelving

Mattermost Bot API поддерживает подписанные действия **Shelve 1h** и **Unshelve**. Incoming webhook остаётся односторонним. Mattermost user ID должен быть связан с IncidentRelay user с responder-доступом. Подробнее: [Shelving](../usage/shelving.md).
