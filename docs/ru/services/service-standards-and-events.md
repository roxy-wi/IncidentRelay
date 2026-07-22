# Стандарты сервисов, готовность и события каталога

Этот документ описывает модель готовности каталога сервисов в IncidentRelay: стандарты сервисов, проверки готовности, внутрипроцессный адаптер событий каталога и API хронологии сервиса.

## Цели

Стандарты сервисов определяют, что сервис должен иметь, прежде чем он будет считаться операционно готовым. Стандарт применяется к сервисам с помощью селекторов `applies_to`. Готовность оценивает все стандарты, соответствующие сервису, и сохраняет агрегированное состояние готовности сервиса.

События каталога предоставляют единую внутреннюю точку входа для изменений каталога сервисов. Слой представления или сервиса выпускает доменное событие, а адаптер записывает события хронологии и запускает согласование готовности, когда это необходимо.

```text
Service/standard action
└── emit_service_catalog_event(...) or emit_group_service_catalog_event(...)
    ├── writes ServiceEvent when the event is service-scoped
    └── runs readiness reconciliation
```

`ServiceEvent` намеренно ограничен областью сервиса. Изменения уровня группы, такие как стандарты/проверки, не создают отдельной строки хронологии для каждого сервиса. Вместо этого они запускают согласование готовности для группы. Если пакет готовности сервиса создаётся или изменяется, оценщик готовности записывает события хронологии сервиса.

## Основные концепции

### Стандарт сервиса

Стандарт — это именованный набор проверок готовности для группы.

Важные поля:

| Поле | Описание |
| --- | --- |
| `group_id` | Группа, которой принадлежит стандарт. |
| `slug` | Стабильный уникальный идентификатор внутри группы. |
| `name` | Понятное человеку имя. |
| `description` | Необязательное пояснение. |
| `applies_to` | Объект-селектор, определяющий, к каким сервисам применяется стандарт. |
| `enabled` | Отключённые стандарты игнорируются оценкой готовности, если только они не указаны явно с `include_disabled=1`. |

### `applies_to`

`applies_to` — это объект. Пустой объект означает, что стандарт применяется ко всем сервисам в группе.

Поддерживаемые ключи селектора:

| Ключ | Значения |
| --- | --- |
| `kinds` | `technical`, `business` |
| `lifecycles` | `experimental`, `development`, `production`, `deprecated`, `retired` |
| `tiers` | `tier_1`, `tier_2`, `tier_3`, `tier_4` |
| `criticalities` | `low`, `medium`, `high`, `critical` |
| `environments` | `production`, `staging`, `development`, `testing`, `shared` |
| `service_types` | `api`, `web`, `database`, `queue`, `cache`, `worker`, `cron`, `network`, `storage`, `infrastructure`, `external`, `other` |

Пример:

```json
{
  "kinds": ["technical"],
  "lifecycles": ["production"],
  "tiers": ["tier_1", "tier_2"],
  "criticalities": ["critical", "high"]
}
```

### Проверка стандарта

Проверка — это одно требование внутри стандарта.

Важные поля:

| Поле | Описание |
| --- | --- |
| `standard_id` | Родительский стандарт. |
| `slug` | Стабильный идентификатор внутри стандарта. |
| `check_type` | Встроенный тип оценщика. |
| `configuration` | Настройки, специфичные для типа. |
| `weight` | Баллы, вносимые в оценку стандарта, от 1 до 100. |
| `severity` | `info`, `warning`, `critical`. |
| `required` | Обязательные сбои отслеживаются отдельно. |
| `position` | Порядок сортировки в выводе UI/оценки. |
| `enabled` | Отключённые проверки игнорируются. |

Поддерживаемые типы проверок:

| Тип | Назначение | Общая конфигурация |
| --- | --- | --- |
| `field_present` | Поле сервиса должно быть непустым. | `{ "field": "metadata.owner" }` |
| `field_equals` | Поле сервиса должно соответствовать ожидаемому значению. | `{ "field": "environment", "value": "production" }` |
| `owner_exists` | У сервиса должна быть хотя бы одна активная заинтересованная сторона по умолчанию. | `{}` |
| `active_rotation_exists` | У сервиса должна быть ротация по умолчанию с активными участниками. | `{}` |
| `escalation_policy_exists` | У сервиса должна быть политика эскалации по умолчанию. | `{ "require_rules": true }` |
| `notification_policy_exists` | У сервиса должна быть политика уведомлений. | `{ "require_rules": true, "require_channels": true }` |
| `service_channel_exists` | У сервиса/команды должен быть хотя бы один пригодный канал уведомлений. | `{}` |
| `route_exists` | Сервис должен быть целью хотя бы одного маршрута или правила сопоставления сервиса. | `{}` |
| `match_rule_exists` | У сервиса должно быть хотя бы одно включённое правило сопоставления сервиса. | `{}` |
| `runbook_exists` | У сервиса должны быть runbook'и. | `{ "minimum": 1 }` |
| `link_type_exists` | У сервиса должна быть ссылка определённого типа. | `{ "link_type": "dashboard" }` |
| `dependency_exists` | У сервиса должна быть хотя бы одна зависимость. | `{ "direction": "upstream" }` |
| `dependency_cycle_absent` | Граф зависимостей сервиса не должен содержать цикла. | `{}` |
| `metadata_value` | Ключ метаданных сервиса должен равняться значению. | `{ "key": "pci", "value": true }` |

### Состояние готовности

Состояние готовности — это текущий агрегат для одного сервиса.

Статусы:

| Статус | Значение |
| --- | --- |
| `ready` | Применимые проверки пройдены. |
| `warning` | Некоторые некритические/необязательные проверки не пройдены. |
| `not_ready` | Обязательные или критические проверки не пройдены. |
| `not_applicable` | К этому сервису не применяются включённые стандарты. |
| `unknown` | Готовность ещё не оценена или оценка неожиданно завершилась ошибкой. |

Состояние содержит оценку и счётчики сбоев:

```json
{
  "status": "not_ready",
  "score": 72,
  "standards_count": 1,
  "checks_count": 6,
  "failed_count": 2,
  "failed_required_count": 1,
  "failed_critical_count": 1,
  "batch_uid": "...",
  "evaluated_at": "2026-06-28T09:32:10Z"
}
```

## Встроенный пресет

Эндпоинт:

```text
POST /api/services/standards/presets/basic-operational
```

Пресет создаёт/восстанавливает `basic-operational-readiness` для группы. Он применяется к production-техническим сервисам и проверяет основные операционные требования:

- активный владелец / заинтересованная сторона по умолчанию;
- политика эскалации с правилами;
- политика уведомлений с правилами и каналами;
- покрытие маршрутом или сопоставлением;
- хотя бы один runbook;
- граф зависимостей без циклов.

Пресет выпускает событие каталога группы и согласует готовность для группы.

## Адаптер событий каталога

Адаптер находится в:

```text
app/services/service_catalog/events.py
```

Используйте его вместо прямого вызова функций хронологии и готовности из представлений.

### События уровня сервиса

```python
emit_service_catalog_event(
    service,
    category="configuration",
    event_type="service_runbook.created",
    title="Service runbook created",
    summary=runbook.title,
    source_ref=f"service_runbook:{runbook.id}",
    external_url=runbook.url,
    actor_user=current_user(),
    payload={"runbook": service_runbook_snapshot(runbook)},
    readiness_trigger="service_runbook_created",
)
```

Это записывает строку `ServiceEvent` и по умолчанию согласует готовность.

### События уровня группы

```python
emit_group_service_catalog_event(
    group_id,
    category="readiness",
    event_type="service_standard.updated",
    title="Service standard updated",
    actor_user=current_user(),
    before=before_snapshot,
    after=after_snapshot,
    readiness_trigger="standard_updated",
)
```

Это не записывает отдельную строку хронологии, потому что `ServiceEvent` ограничен областью сервиса. Оно согласует готовность группы.

### Ручное согласование готовности

```python
reconcile_service_catalog_readiness(
    service,
    trigger="manual_evaluate",
    actor_user=current_user(),
)
```

Используйте это для явных действий API/UI `Evaluate readiness`, когда не должно создаваться дополнительное доменное событие.

### Области готовности

| Область | Сценарий использования |
| --- | --- |
| `none` | Только событие хронологии, без обновления готовности. |
| `service` | Согласовать изменённый сервис. |
| `services` | Согласовать изменённый сервис плюс явно указанные затронутые ID сервисов. |
| `group` | Согласовать каждый читаемый/активный сервис в группе. |
| `dependency_component` | Согласовать сервисы в компоненте зависимостей. |

## Соглашения об именовании событий

Используйте стабильные имена с точками:

```text
service.created
service.updated
service.deleted
service_owner.created
service_owner.updated
service_owner.deleted
service_link.created
service_link.updated
service_link.deleted
service_runbook.created
service_runbook.updated
service_runbook.deleted
service_dependency.created
service_dependency.updated
service_dependency.deleted
service_dependency.downstream_created
service_dependency.downstream_updated
service_dependency.downstream_deleted
service_match_rule.created
service_match_rule.updated
service_match_rule.deleted
service_standard.created
service_standard.updated
service_standard.deleted
service_standard_check.created
service_standard_check.updated
service_standard_check.deleted
service_standard_preset.applied
readiness.evaluated
readiness.score_changed
```

Рекомендуемые категории:

| Категория | События |
| --- | --- |
| `configuration` | изменения сервиса, владельца, ссылки, runbook'а, зависимости |
| `routing` | изменения правил сопоставления сервиса |
| `readiness` | стандарты, проверки, оценка готовности |
| `status` | обновления статуса сервиса |
| `alerting` | будущие события каталога сервисов, вызванные алертами |

## API хронологии

Эндпоинт:

```text
GET /api/services/{service_id}/timeline
```

Параметры запроса:

| Параметр | Описание |
| --- | --- |
| `limit` | Количество возвращаемых событий, 1..200, по умолчанию 50. |
| `category` | Необязательный фильтр по категории. |
| `event_type` | Необязательный фильтр по типу события. |
| `before` | Курсорная метка времени из `next_cursor.before`. |
| `before_id` | Курсорный ID из `next_cursor.before_id`. |

Пример ответа:

```json
{
  "items": [
    {
      "id": 123,
      "uid": "...",
      "service_id": 10,
      "group_id": 1,
      "team_id": 2,
      "category": "configuration",
      "event_type": "service_runbook.created",
      "title": "Service runbook created",
      "summary": "RabbitMQ cluster partition",
      "source": "incidentrelay",
      "source_ref": "service_runbook:42",
      "external_url": "https://docs.example.com/runbooks/rabbitmq",
      "actor": {
        "type": "user",
        "user_id": 7,
        "display_name": "Alice",
        "email": "alice@example.com",
        "label": null
      },
      "severity": null,
      "status": null,
      "occurred_at": "2026-06-28T09:32:10Z",
      "recorded_at": "2026-06-28T09:32:10Z",
      "schema_version": 1,
      "payload": {
        "runbook": {
          "id": 42,
          "title": "RabbitMQ cluster partition"
        }
      }
    }
  ],
  "next_cursor": {
    "before": "2026-06-28T09:32:10Z",
    "before_id": 123
  }
}
```

## Сводка по API

### Стандарты

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/services/standards` | Список стандартов, видимых пользователю. |
| `POST` | `/api/services/standards` | Создать стандарт. |
| `GET` | `/api/services/standards/{standard_id}` | Получить один стандарт с проверками. |
| `PUT` | `/api/services/standards/{standard_id}` | Обновить стандарт. |
| `DELETE` | `/api/services/standards/{standard_id}` | Мягко удалить стандарт. |
| `POST` | `/api/services/standards/presets/basic-operational` | Создать/восстановить встроенный пресет. |

### Проверки

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/services/standards/{standard_id}/checks` | Список проверок. |
| `POST` | `/api/services/standards/{standard_id}/checks` | Создать проверку. |
| `GET` | `/api/services/standards/{standard_id}/checks/{check_id}` | Получить одну проверку. |
| `PUT` | `/api/services/standards/{standard_id}/checks/{check_id}` | Обновить проверку. |
| `DELETE` | `/api/services/standards/{standard_id}/checks/{check_id}` | Мягко удалить проверку. |

### Готовность

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/services/{service_id}/readiness` | Получить текущий пакет готовности. |
| `POST` | `/api/services/{service_id}/readiness/evaluate` | Принудительно оценить готовность. |

### События

| Метод | Путь | Описание |
| --- | --- | --- |
| `GET` | `/api/services/{service_id}/timeline` | Список событий хронологии сервиса. |

## Управление доступом

- Стандарты ограничены областью группы.
- Просмотр списка стандартов требует доступа на чтение к группе.
- Создание/обновление/удаление стандартов и проверок требует доступа на запись к группе.
- Готовность сервиса и хронология требуют доступа на чтение к команде сервиса.
- Ручная оценка готовности требует доступа на запись к команде сервиса.

## Ответы об ошибках

Распространённые коды ошибок:

| Ошибка | HTTP | Значение |
| --- | --- | --- |
| `validation_error` | 400 | Тело запроса не прошло валидацию схемы. |
| `service_standard_invalid` | 400 | Доменная валидация стандарта не пройдена. |
| `service_standard_check_invalid` | 400 | Доменная валидация проверки не пройдена. |
| `service_standard_not_found` | 404 | Стандарт не найден. |
| `service_standard_check_not_found` | 404 | Проверка не найдена. |
| `service_not_found` | 404 | Сервис не найден. |
| `group_not_found` | 404 | Группа не найдена. |
| `timeline_before_invalid` | 400 | Курсорная метка времени хронологии не является допустимым ISO 8601. |

## Контрольный список реализации

- Используйте `emit_service_catalog_event()` для изменений уровня сервиса.
- Используйте `emit_group_service_catalog_event()` для изменений стандарта/проверки/пресета.
- Используйте `reconcile_service_catalog_readiness()` для ручной оценки без отдельного доменного события.
- Оставляйте `write_audit(...)` в представлениях как журнал аудита безопасности/API.
- Не записывайте события стандартов уровня группы напрямую в хронологию каждого сервиса.
- Добавляйте снимки в `app/services/service_catalog/snapshots.py` при введении нового типа объекта каталога.
