---
title: API Event Orchestration
description: Создание, версионирование, проверка, симуляция, публикация и наблюдение за правилами Event Orchestration через API IncidentRelay.
---

# API Event Orchestration

Event Orchestration — это версионируемый слой обработки событий между нормализаторами интеграций и существующим жизненным циклом алертов.

Сгенерированный документ OpenAPI доступен по адресу `/api/openapi.json`, а Swagger UI — по адресу `/docs`.

Описание с точки зрения UI, процедуру безопасного внедрения и практические примеры см. в [руководстве пользователя Event Orchestration](../usage/event-orchestration.md).

## Аутентификация и разрешения

Все эндпоинты плоскости управления требуют JWT или персональный API-токен:

```http
Authorization: Bearer <token>
```

Фактический доступ ограничивается группой оркестрации:

| Роль в группе | Доступ |
| --- | --- |
| `viewer` | Просмотр оркестраций, версий и выполнений |
| `editor` | Просмотр, создание, редактирование, проверка, симуляция, повторное выполнение, публикация и откат |
| `user_admin` | Просмотр оркестраций и выполнений |
| Глобальный администратор | Все разрешения, включая удаление и управление webhook-действиями |

Каждый ответ оркестрации содержит объект `permissions`, чтобы клиенты могли скрывать действия, недоступные текущему пользователю.

## Жизненный цикл

Новая оркестрация создаётся отключённой и содержит один редактируемый черновик.

```text
Создание -> редактирование черновика -> проверка -> симуляция -> публикация
                                                    |
                                                    +-> неизменяемая версия
```

Опубликованные версии неизменяемы. При откате историческое определение копируется в новую версию, после чего публикуется именно новая версия; историческая запись никогда не редактируется.

Основные эндпоинты:

```text
GET    /api/event-orchestrations
POST   /api/event-orchestrations
GET    /api/event-orchestrations/{orchestration_id}
PATCH  /api/event-orchestrations/{orchestration_id}
DELETE /api/event-orchestrations/{orchestration_id}

POST   /api/event-orchestrations/{orchestration_id}/draft
PUT    /api/event-orchestrations/{orchestration_id}/draft
POST   /api/event-orchestrations/{orchestration_id}/validate
POST   /api/event-orchestrations/{orchestration_id}/publish
POST   /api/event-orchestrations/{orchestration_id}/rollback
PATCH  /api/event-orchestrations/{orchestration_id}/runtime

GET    /api/event-orchestrations/{orchestration_id}/versions
GET    /api/event-orchestrations/{orchestration_id}/versions/{version_id}
POST   /api/event-orchestrations/{orchestration_id}/simulate
POST   /api/event-orchestrations/{orchestration_id}/replay
GET    /api/event-orchestrations/{orchestration_id}/executions
GET    /api/event-orchestrations/{orchestration_id}/shadow-metrics
```

Эндпоинт каталога редактора возвращает сервисы, команды, маршруты, политики, источники нормализаторов и webhook-действия в пределах группы, а также фактические разрешения:

```text
GET /api/event-orchestrations/catalog?group_id=1
```

## Создание оркестрации

Для оркестрации уровня сервиса требуется `service_id`. Для глобальной оркестрации это поле указывать нельзя.

```json
{
  "group_id": 1,
  "name": "Production routing",
  "description": "Normalize production alerts before lifecycle processing",
  "scope": "global",
  "compatibility_mode": "hybrid"
}
```

## Условия

Дерево условий представляет собой либо одно конечное условие, либо одну логическую группу:

```json
{
  "all": [
    {
      "field": "labels.environment",
      "operator": "equals",
      "value": "production"
    },
    {
      "any": [
        {
          "field": "event.severity",
          "operator": "equals",
          "value": "critical"
        },
        {
          "field": "labels.priority",
          "operator": "in",
          "value": ["p1", "p2"]
        }
      ]
    }
  ]
}
```

Логические ключи:

- `all` — AND;
- `any` — OR;
- `none` — NOT: ни один из дочерних элементов не должен совпасть.

Схема OpenAPI `OrchestrationCondition` содержит точное перечисление операторов, поддерживаемых запущенной версией.

## Действия

Правила выполняют детерминированные встроенные действия. Они могут изменять поля и метки событий, извлекать переменные, выбирать маршрутизацию и политики, менять группировку, подавлять, отбрасывать или приостанавливать обработку, добавлять заметки либо ставить настроенный webhook в очередь.

Пример черновика:

```json
{
  "rules": [
    {
      "name": "Route critical production alerts",
      "enabled": true,
      "condition_tree": {
        "all": [
          {
            "field": "labels.environment",
            "operator": "equals",
            "value": "production"
          },
          {
            "field": "event.severity",
            "operator": "equals",
            "value": "critical"
          }
        ]
      },
      "actions": [
        {"type": "set_team", "team_id": 4},
        {"type": "set_priority", "value": "P1"},
        {"type": "set_label", "name": "orchestrated", "value": "true"}
      ],
      "processing_mode": "continue",
      "children": []
    }
  ],
  "comment": "Route critical production alerts"
}
```

Выполнение произвольных команд shell, Python, SSH и контейнеров не поддерживается.

## Проверка, симуляция и публикация

Проверка применяется к текущему черновику:

```text
POST /api/event-orchestrations/{orchestration_id}/validate
```

Симуляция принимает либо одно нормализованное событие, либо один необработанный payload интеграции. Она не создаёт алерты, не меняет состояние production и не выполняет webhook'и.

```json
{
  "normalized_event": {
    "source": "webhook",
    "title": "Database unavailable",
    "severity": "critical",
    "labels": {"environment": "production"}
  },
  "compare_with_active": true
}
```

Публикация создаёт неизменяемую версию:

```json
{
  "comment": "Reviewed and ready for production",
  "confirm_catch_all_drop": false
}
```

Правила безусловного отбрасывания требуют явного подтверждения.

## Метаданные авторов

В ответах с версиями разделяются участвовавшие пользователи:

- `created_by` — создал запись версии;
- `updated_by` — последним изменил определение черновика;
- `published_by` — опубликовал неизменяемую версию.

Каждому полю соответствует значение `*_id`. Объекты пользователей содержат `id`, `username`, необязательное поле `display_name` и готовое для отображения поле `label`.

## Режимы выполнения

```json
{
  "mode": "shadow",
  "compatibility_mode": "hybrid"
}
```

Режимы выполнения:

- `disabled` — оркестрация не выполняется;
- `shadow` — решения записываются, но не могут менять поведение production;
- `active` — опубликованные решения применяются.

Чтобы включить режим `shadow` или `active`, необходима опубликованная версия.

## Webhook-действия

Для переиспользуемых webhook-действий предусмотрен отдельный API:

```text
GET    /api/orchestration-webhook-actions?group_id=1
POST   /api/orchestration-webhook-actions
PATCH  /api/orchestration-webhook-actions/{action_id}
DELETE /api/orchestration-webhook-actions/{action_id}
GET    /api/orchestration-webhook-actions/{action_id}/executions
```

Секретные `headers` доступны только для записи. IncidentRelay шифрует их и никогда не возвращает в ответах API. Записи выполнений содержат только отредактированные фрагменты ответов и безопасный текст ошибок.
