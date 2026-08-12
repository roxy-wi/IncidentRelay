---
title: Escalation Policies API
description: Справочник API по политикам эскалации IncidentRelay и правилам политик
---

# Escalation Policies API

Эндпоинты политик эскалации требуют токена аутентифицированного пользователя.

```http
Authorization: Bearer USER_OR_API_TOKEN
```

Токены приёма маршрута (route intake token) предназначены только для интеграций входящих алертов и не могут использоваться для управления политиками.

## Список политик

```http
GET /api/escalation-policies
GET /api/escalation-policies?team_id=1
```

Ответ:

```json
[
  {
    "id": 1,
    "team_id": 1,
    "team_name": "Cloud OPS",
    "team_slug": "cloud",
    "group_id": 2,
    "group_slug": "infra",
    "name": "Critical escalation",
    "description": "Critical alerts chain",
    "enabled": true,
    "repeat_count": 1,
    "rules": [],
    "permissions": {
      "can_read": true,
      "can_write": true,
      "can_respond": true
    },
    "created_at": "2026-05-26T17:07:32.342717",
    "updated_at": "2026-05-26T17:07:32.342719"
  }
]
```

## Создание политики

```http
POST /api/escalation-policies
```

Запрос:

```json
{
  "team_id": 1,
  "name": "Critical escalation",
  "description": "Critical alerts chain",
  "enabled": true,
  "repeat_count": 1
}
```

Статус ответа:

```text
201 Created
```

## Получение политики

```http
GET /api/escalation-policies/{policy_id}
```

Возвращает одну политику с правилами.

## Обновление политики

```http
PUT /api/escalation-policies/{policy_id}
```

Запрос:

```json
{
  "team_id": 1,
  "name": "Critical escalation",
  "description": "Critical alerts chain",
  "enabled": true,
  "repeat_count": 1
}
```

## Удаление политики

```http
DELETE /api/escalation-policies/{policy_id}
```

Удаляет или отключает политику в зависимости от реализации бэкенда. Существующие алерты сохраняют своё сохранённое состояние политики.

## Создание правила

```http
POST /api/escalation-policies/{policy_id}/rules
```

Запрос с целью-ротацией:

```json
{
  "position": 1,
  "delay_seconds": 300,
  "target_type": "rotation",
  "target_id": 10,
  "enabled": true
}
```

Запрос с целью-пользователем:

```json
{
  "position": 2,
  "delay_seconds": 600,
  "target_type": "user",
  "target_id": 42,
  "enabled": true
}
```

Правила вычисляются по `position` в порядке возрастания.

## Обновление правила

```http
PUT /api/escalation-policies/rules/{rule_id}
```

Запрос:

```json
{
  "position": 2,
  "delay_seconds": 600,
  "target_type": "rotation",
  "target_id": 11,
  "enabled": true
}
```

## Удаление правила

```http
DELETE /api/escalation-policies/rules/{rule_id}
```

## Интеграция с маршрутами

Маршруты могут использовать либо прямую ротацию, либо политику эскалации.

Режим простой ротации:

```json
{
  "team_id": 1,
  "name": "alertmanager-critical",
  "source": "alertmanager",
  "rotation_id": 10,
  "escalation_policy_id": null,
  "channel_ids": [3, 4],
  "matchers": {
    "labels": {
      "severity": "critical"
    }
  },
  "group_by": ["alertname", "instance"],
  "enabled": true
}
```

Режим политики эскалации:

```json
{
  "team_id": 1,
  "name": "alertmanager-critical",
  "source": "alertmanager",
  "rotation_id": null,
  "escalation_policy_id": 1,
  "channel_ids": [3, 4],
  "matchers": {
    "labels": {
      "severity": "critical"
    }
  },
  "group_by": ["alertname", "instance"],
  "enabled": true
}
```

Если задан `escalation_policy_id`, то настройки командной эскалации на основе напоминаний игнорируются для алертов, созданных этим маршрутом.

## Поля алерта

Ответы по алертам включают состояние политики, если алерт был создан через маршрут с политикой.

```json
{
  "id": 123,
  "status": "firing",
  "escalation_mode": "policy",
  "escalation_policy_id": 1,
  "escalation_policy_name": "Critical escalation",
  "escalation_rule_id": 5,
  "escalation_rule_position": 2,
  "escalation_rule_target_type": "rotation",
  "next_escalation_at": "2026-05-27T12:30:00",
  "last_escalated_at": "2026-05-27T12:20:00",
  "escalation_repeat_count": 0,
  "team_escalation_enabled": true,
  "team_escalation_after_reminders": 2
}
```

## Ответы с ошибками

Типичные ошибки:

| HTTP-статус | Ошибка | Значение |
|---:|---|---|
| `400` | `rotation_team_mismatch` | Целевая ротация правила принадлежит другой команде |
| `400` | `user_team_mismatch` | Целевой пользователь правила не является участником команды политики |
| `400` | `escalation_policy_team_mismatch` | Маршрут использует политику из другой команды |
| `403` | `permission_denied` | У пользователя нет прав на запись |
| `404` | `not_found` | Политика, правило или цель не найдены |
| `409` | `conflict` | Дублирующаяся политика или позиция правила |
