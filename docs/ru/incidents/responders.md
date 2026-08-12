---
title: Ответственные за инцидент
description: Запрос дополнительных ответственных для активных инцидентов и управление ими.
---

# Ответственные за инцидент

Ответственные за инцидент (responders) — это люди, команды, ротации или политики эскалации, явно привлечённые для помощи с активным инцидентом.

Ответственные отличаются от назначенного (assignee) инцидента:

- **Назначенный (Assignee)** — это основной владелец инцидента.
- **Ответственный (Responder)** — это дополнительный участник, которого попросили помочь.
- Принятие запроса ответственного **не** назначает инцидент этому пользователю автоматически.

## Типы целей

Запрос ответственного может быть нацелен на один из следующих объектов:

| Тип цели | Обязательное поле |
|---|---|
| `user` | `target_user_id` |
| `team` | `target_team_id` |
| `rotation` | `target_rotation_id` |
| `escalation_policy` | `target_escalation_policy_id` |

Для выбранного `target_type` должен быть указан только один идентификатор цели.

## Запросить ответственного

```http
POST /api/incidents/{incident_id}/responders
```

Тело запроса:

```json
{
  "target_type": "user",
  "target_user_id": 42,
  "message": "Please help with database checks",
  "expires_after_minutes": 30
}
```

Ответ:

```json
{
  "id": 15,
  "incident_id": 14784,
  "group_id": 14784,
  "target_type": "user",
  "target_user_id": 42,
  "target_team_id": null,
  "target_rotation_id": null,
  "target_escalation_policy_id": null,
  "target": {
    "type": "user",
    "id": 42,
    "label": "Alice Smith",
    "user": {
      "id": 42,
      "username": "alice",
      "display_name": "Alice Smith",
      "email": "alice@example.com"
    }
  },
  "requested_by_id": 1,
  "requested_by": {
    "id": 1,
    "username": "admin",
    "display_name": "Admin",
    "email": "admin@example.com"
  },
  "accepted_by_id": null,
  "accepted_by": null,
  "declined_by_id": null,
  "declined_by": null,
  "status": "requested",
  "message": "Please help with database checks",
  "response_message": null,
  "notification_status": "sent",
  "notification_error": null,
  "requested_at": "2026-06-17T10:00:00Z",
  "responded_at": null,
  "expires_at": "2026-06-17T10:30:00Z",
  "created_at": "2026-06-17T10:00:00Z",
  "updated_at": "2026-06-17T10:00:00Z"
}
```

## Список ответственных за инцидент

```http
GET /api/incidents/{incident_id}/responders
```

Возвращает все запросы ответственных для инцидента.

Пример ответа:

```json
[
  {
    "id": 15,
    "incident_id": 14784,
    "group_id": 14784,
    "target_type": "user",
    "target_user_id": 42,
    "target": {
      "type": "user",
      "id": 42,
      "label": "Alice Smith",
      "user": {
        "id": 42,
        "username": "alice",
        "display_name": "Alice Smith",
        "email": "alice@example.com"
      }
    },
    "status": "requested",
    "message": "Please help with database checks",
    "response_message": null,
    "requested_at": "2026-06-17T10:00:00Z",
    "responded_at": null,
    "expires_at": "2026-06-17T10:30:00Z"
  }
]
```

## Обновить статус ответственного

```http
PUT /api/incidents/{incident_id}/responders/{responder_id}
```

Тело запроса:

```json
{
  "status": "accepted",
  "response_message": "I am joining"
}
```

Допустимые статусы:

| Статус | Описание |
|---|---|
| `accepted` | Ответственный принял запрос. |
| `declined` | Ответственный отклонил запрос. |
| `resolved` | Запрос ответственного был разрешён вручную. |
| `expired` | Запрос ответственного истёк. Обычно устанавливается планировщиком. |

Пример ответа:

```json
{
  "id": 15,
  "incident_id": 14784,
  "group_id": 14784,
  "target_type": "user",
  "target_user_id": 42,
  "target": {
    "type": "user",
    "id": 42,
    "label": "Alice Smith"
  },
  "requested_by_id": 1,
  "accepted_by_id": 42,
  "accepted_by": {
    "id": 42,
    "username": "alice",
    "display_name": "Alice Smith",
    "email": "alice@example.com"
  },
  "declined_by_id": null,
  "declined_by": null,
  "status": "accepted",
  "message": "Please help with database checks",
  "response_message": "I am joining",
  "requested_at": "2026-06-17T10:00:00Z",
  "responded_at": "2026-06-17T10:05:00Z",
  "expires_at": "2026-06-17T10:30:00Z"
}
```

## Центр уведомлений

Ожидающие запросы ответственных отображаются в центре уведомлений.

Подробнее: [Центр уведомлений](notification-center.md).

## Разрешения

Запросы ответственных могут создавать пользователи, которые могут реагировать на инциденты команды.

Статус ответственного могут обновлять пользователи, которые могут выступать в роли целевого ответственного:

- целевой пользователь;
- пользователь, которому разрешено реагировать за целевую команду;
- пользователь, которому разрешено реагировать за команду целевой ротации;
- пользователь, которому разрешено реагировать за команду целевой политики эскалации.

Случайный наблюдатель, не являющийся целью, не может принять или отклонить запрос ответственного другого пользователя.

## События таймлайна

Действия ответственных записываются в таймлайн инцидента.

| Тип события | Пример сообщения |
|---|---|
| `responder_requested` | `Responder requested: Alice Smith. Please help with this incident.` |
| `responder_accepted` | `Alice Smith accepted responder request. I am joining` |
| `responder_declined` | `Alice Smith declined responder request. Busy now` |
| `responder_expired` | `Responder request expired for Alice Smith` |

## Браузерное push-уведомление

Когда для целевого ответственного настроены браузерные push-уведомления, IncidentRelay отправляет push-уведомление о запросе ответственного.

Уведомление должно включать достаточно контекста, чтобы действовать, не открывая сначала инцидент:

- заголовок инцидента;
- приоритет;
- запрашивающий;
- команда;
- сервис, если доступен;
- сообщение запроса;
- ссылка на инцидент.

Сбой доставки push не мешает созданию запроса ответственного. В этом случае `notification_status` и `notification_error` описывают результат доставки.
