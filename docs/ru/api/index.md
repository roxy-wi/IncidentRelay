---
title: API
description: Обзор API IncidentRelay, аутентификация и группы эндпоинтов.
---

# API

Swagger UI доступен по адресу:

```text
/docs
```

OpenAPI JSON доступен по адресу:

```text
/api/openapi.json
```

Используйте токены приёма маршрута для эндпоинтов входящих интеграций и персональные API-токены для автоматизации в контексте пользователя.

## Browser push API

Эндпоинты профиля браузерных push-уведомлений привязаны к пользователю и требуют аутентификации:

```text
GET    /api/profile/push/vapid-public-key
GET    /api/profile/push/subscriptions
POST   /api/profile/push/subscriptions
DELETE /api/profile/push/subscriptions/{subscription_id}
POST   /api/profile/push/test
```

Эндпоинт действия push-уведомления публичен по замыслу и использует одноразовый токен действия из полезной нагрузки уведомления:

```text
POST /api/push/actions
```

Подробнее: [Браузерные push-уведомления](../usage/browser-push.md).

## Дополнительная документация по API

1. [Services API](services.md)
2. [Escalation Policies API](escalation-policies.md)
3. [Matcher Suggestions API](matchers.md)
4. [Sentry Integration API](sentry-integration.md)
5. [Заметки по Voice Call OpenAPI](voice-call-openapi.md)
6. [Бизнес-сервисы](business-services.md)

- [Heartbeats API](heartbeats.md)
