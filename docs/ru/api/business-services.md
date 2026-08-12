# Business Services API

Базовый путь:

```text
/api/business-services
```

Все эндпоинты требуют аутентификации. Права на чтение/запись группы применяются в соответствии с текущими правилами RBAC IncidentRelay.

## Список бизнес-сервисов

```http
GET /api/business-services?group_id=<group_id>
```

Возвращает бизнес-сервисы, видимые текущему пользователю.

Для пользователей, не являющихся администраторами, `group_id` обязателен либо определяется по активной группе в зависимости от логики представления.

Ответ со списком включает пересчитанный статус и `components_count`.

Пример ответа:

```json
[
  {
    "id": 1,
    "group_id": 1,
    "group_name": "Production",
    "owner_team_id": 2,
    "owner_team_name": "Platform",
    "slug": "checkout",
    "name": "Checkout",
    "description": "Customer checkout flow",
    "status": "degraded",
    "status_source": "calculated",
    "status_message": "Affected components: Billing API. Calculated status: degraded, impact score=50",
    "status_updated_at": "2026-07-06T10:00:00Z",
    "manual_status": null,
    "manual_status_message": null,
    "manual_status_until": null,
    "manual_status_set_by_id": null,
    "manual_status_set_at": null,
    "manual_status_active": false,
    "criticality": "important",
    "tier": "tier_2",
    "public": true,
    "public_name": "Checkout",
    "public_description": "Customer checkout flow",
    "public_order": 100,
    "enabled": true,
    "components_count": 3
  }
]
```

## Создание бизнес-сервиса

```http
POST /api/business-services
```

Тело запроса:

```json
{
  "group_id": 1,
  "owner_team_id": 2,
  "slug": "checkout",
  "name": "Checkout",
  "description": "Customer checkout flow",
  "criticality": "important",
  "tier": "tier_2",
  "public": true,
  "public_name": "Checkout",
  "public_description": "Customer checkout flow",
  "public_order": 100,
  "labels": {},
  "metadata": {},
  "enabled": true
}
```

Обязательные поля:

```text
group_id
slug
name
```

## Получение сведений о бизнес-сервисе

```http
GET /api/business-services/{business_service_id}
```

Возвращает полный набор данных:

```text
Business Service
+ components
+ status_history
```

Эндпоинт пересчитывает бизнес-сервис перед сериализацией, если только не активно ручное переопределение.

Ответ включает поля эффективного влияния компонентов:

```json
{
  "id": 1,
  "slug": "checkout",
  "name": "Checkout",
  "status": "degraded",
  "status_source": "calculated",
  "components": [
    {
      "id": 10,
      "business_service_id": 1,
      "service_id": 25,
      "service_slug": "billing-api",
      "service_name": "Billing API",
      "service_status": "operational",
      "effective_status": "degraded",
      "effective_status_reason": "alert_group",
      "alert_impact_status": "degraded",
      "dependency_impact_status": "operational",
      "open_alert_groups": 1,
      "critical_open_alert_groups": 0,
      "upstream_issues_count": 0,
      "criticality": "required",
      "impact_weight": 100,
      "enabled": true
    }
  ],
  "status_history": []
}
```

## Обновление бизнес-сервиса

```http
PUT /api/business-services/{business_service_id}
```

Тело запроса использует те же поля, что и при создании.

Эндпоинт обновляет бизнес-сервис и возвращает сериализованный бизнес-сервис.

## Удаление бизнес-сервиса

```http
DELETE /api/business-services/{business_service_id}
```

Выполняет мягкое удаление бизнес-сервиса и отключает связанные активные записи в соответствии с реализацией репозитория.

## Пересчёт бизнес-сервиса

```http
POST /api/business-services/{business_service_id}/recalculate
```

Пересчитывает текущий статус на основе эффективного статуса компонентов и возвращает полный набор данных.

Ручное переопределение имеет приоритет, если оно активно.

Ответ:

```text
Business Service details payload
```

## Установка ручного переопределения статуса

```http
POST /api/business-services/{business_service_id}/manual-status
```

Тело запроса:

```json
{
  "status": "degraded",
  "message": "Customer impact is limited but visible.",
  "until": "2026-07-06T12:00:00Z"
}
```

Допустимые значения `status`:

```text
operational
degraded
partial_outage
major_outage
maintenance
```

`until` необязателен. Если он опущен, переопределение остаётся активным до тех пор, пока не будет снято вручную.

Эндпоинт возвращает полный набор данных, включая компоненты и историю статусов.

## Снятие ручного переопределения статуса

```http
DELETE /api/business-services/{business_service_id}/manual-status
```

Снимает ручное переопределение, пересчитывает бизнес-сервис и возвращает полный набор данных.

## Список компонентов

```http
GET /api/business-services/{business_service_id}/components
```

Возвращает компоненты бизнес-сервиса.

Каждый компонент включает поля сырого и эффективного статуса:

```json
[
  {
    "id": 10,
    "business_service_id": 1,
    "service_id": 25,
    "service_slug": "billing-api",
    "service_name": "Billing API",
    "team_id": 2,
    "team_slug": "platform",
    "team_name": "Platform",
    "service_status": "operational",
    "effective_status": "degraded",
    "effective_status_reason": "alert_group",
    "alert_impact_status": "degraded",
    "dependency_impact_status": "operational",
    "open_alert_groups": 1,
    "critical_open_alert_groups": 0,
    "upstream_issues_count": 0,
    "component_type": "technical_service",
    "criticality": "required",
    "impact_weight": 100,
    "position": 0,
    "status_rule": "inherit",
    "description": null,
    "enabled": true
  }
]
```

## Добавление компонента

```http
POST /api/business-services/{business_service_id}/components
```

Тело запроса:

```json
{
  "service_id": 25,
  "component_type": "technical_service",
  "criticality": "required",
  "impact_weight": 100,
  "position": 0,
  "status_rule": "inherit",
  "description": null,
  "enabled": true
}
```

Обязательные поля:

```text
service_id
```

После создания бизнес-сервис должен быть пересчитан, а ответ должен включать сериализованный компонент с полями эффективного влияния.

Поля влияния компонента включают:

```text
effective_status
effective_status_reason
own_impact_score
alert_impact_score
dependency_impact_score
effective_impact_score
service_impact_score
component_multiplier
weighted_impact_score
```

`service_impact_score` берётся из Service Impact v2. `weighted_impact_score` — это оценка компонента после применения критичности и веса влияния. Затем статус бизнес-сервиса использует комбинированные взвешенные оценки компонентов.

## Обновление компонента

```http
PUT /api/business-services/components/{component_id}
```

Тело запроса использует те же поля, что и при добавлении компонента.

Изменение критичности компонента, веса, состояния enabled или технического сервиса может изменить вычисленный статус бизнес-сервиса.

## Удаление компонента

```http
DELETE /api/business-services/components/{component_id}
```

Выполняет мягкое удаление или отключение компонента в соответствии с поведением репозитория.

После удаления компонента статус бизнес-сервиса должен быть пересчитан.

## История статусов

История статусов включается в полный набор данных.

Поля элемента истории:

```json
{
  "id": 1,
  "business_service_id": 1,
  "old_status": "operational",
  "new_status": "degraded",
  "status_source": "calculated",
  "message": "Affected components: Billing API. Calculated status: degraded, impact score=50",
  "impact_score": 50,
  "component_snapshot": [],
  "created_at": "2026-07-06T10:00:00Z"
}
```

## Интеграция с алертами

Влияние на бизнес-сервис обновляется хуками жизненного цикла алертов.

Когда группа алертов затрагивает непосредственный компонент бизнес-сервиса, связь имеет вид:

```text
component_alert
```

Когда алерт затрагивает вышестоящую зависимость компонента бизнес-сервиса, связь имеет вид:

```text
dependency_upstream_alert
```

Записи о влиянии на бизнес деактивируются, когда алерт больше не затрагивает бизнес-сервис.

## Ответы с ошибками

Типичные ответы с ошибками:

```json
{"error": "Business service not found"}
```

```json
{"error": "Access to this group is denied"}
```

```json
{"error": "Manual status expiration must be in the future"}
```

```json
{"error": "Technical service is required."}
```
