---
title: Центр уведомлений
description: Ожидающие запросы ответственных и уведомления об инцидентах для пользователей.
---

# Центр уведомлений

Центр уведомлений показывает ожидающие действия пользователя, связанные с инцидентами.

Текущий центр уведомлений включает ожидающие запросы ответственных за инцидент. Запрос ответственного отображается для пользователей, которым разрешено выступать в роли целевого ответственного.

## Эндпоинт

```http
GET /api/notification-center
```

Пример ответа:

```json
{
  "unread_count": 1,
  "items": [
    {
      "id": "responder-request-15",
      "type": "responder_request",
      "title": "Responder requested",
      "body": "Admin: Please help with database checks",
      "created_at": "2026-06-17T10:00:00Z",
      "expires_at": "2026-06-17T10:30:00Z",
      "url": "/alerts/14784",
      "incident_id": 14784,
      "incident": {
        "id": 14784,
        "incident_id": 14784,
        "title": "DiskFull",
        "status": "firing",
        "priority": {
          "slug": "p1"
        },
        "team_name": "Platform Team",
        "service_name": "PostgreSQL"
      },
      "responder": {
        "id": 15,
        "target": {
          "type": "user",
          "id": 42,
          "label": "Alice Smith"
        },
        "status": "requested"
      },
      "actions": [
        {
          "id": "accept",
          "label": "Accept",
          "status": "accepted",
          "method": "PUT",
          "url": "/api/incidents/14784/responders/15"
        },
        {
          "id": "decline",
          "label": "Decline",
          "status": "declined",
          "method": "PUT",
          "url": "/api/incidents/14784/responders/15"
        }
      ]
    }
  ]
}
```

## Жизненный цикл запроса ответственного

Когда запрос ответственного принят, отклонён, разрешён или истёк, он исчезает из центра уведомлений.

Подробнее: [Ответственные за инцидент](responders.md).
