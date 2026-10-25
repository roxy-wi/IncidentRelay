# IncidentRelay — Change Intelligence

**Архитектурный RFC v1 (проект для реализации)**  
**Исходная кодовая база:** `release/2.3.1` (проверена 2026-10-11)  
**Статус:** архитектура предложена, реализация не начата  

## 1. Назначение и границы

Change Intelligence — самостоятельная подсистема, которая принимает унифицированные события изменений инфраструктуры и приложений, хранит историю операций, отображает их на странице **Operations → Changes** и находит объяснимые потенциальные связи с техническими AlertGroups и операционными Incidents.

GitLab, Jenkins, Terraform, Kubernetes, Ansible, CMDB и пользовательские скрипты отправляют **один и тот же стандартизированный JSON** на один HTTP endpoint. Ядро не обязано содержать адаптер для каждого продукта: преобразование специфического payload выполняется отправителем или необязательным внешним адаптером.

CI/CD-система может **не знать внутренних ID IncidentRelay**. Она вправе использовать стабильные slug команд и сервисов; backend разрешает их в числовые ID существующей инсталляции. Сервисы и их зависимости могут поступать из CMDB независимо от Change Events.

**Вне v1:** ITIL Change Requests, approval workflow, автоматический rollback, автоматическое создание AlertGroup/Incident из Change, AI Root Cause Analysis, реализация CMDB-синхронизатора и обязательная Plugin Platform. Change — не AlertGroup и не Incident. Успешный deployment тоже может стать причиной проблемы; статус изменения и причинная связь независимы.

## 2. Архитектурные инварианты

1. Один Change принадлежит **ответственной Team** (`owner_team_id` в БД), но непосредственно изменённые и затронутые сервисы могут принадлежать **любым Teams**, в том числе из других Groups.
2. В публичном API ответственная Team задаётся **ровно одним** полем: `owner_team_id` либо `owner_team_slug`. Slug разрешается в существующую Team перед проверкой полномочий.
3. Каждая ссылка на технический Service передаётся через **`service_id` либо `service_slug`**. Для slug используется Team namespace: `team_id` или `team_slug`. Если namespace опущен, берётся **owner Team**, а не выполняется глобальный поиск.
4. В актуальной модели `Team.slug` уникален глобально, а `Service.slug` уникален только внутри Team (`UNIQUE(team, slug)`). Поэтому один `service_slug` без Team допустим **только как сокращение для owner Team**.
5. После успешного разрешения ссылки канонические связи, корреляция и Service Timeline работают с **`service_id`**. Исходная ссылка по slug сохраняется отдельно для истории и диагностики; переименование slug не должно перепривязывать старое изменение к другому сервису.
6. Неизвестный slug сервиса в **известной Team** может быть сохранён как `pending_resolution` до синхронизации CMDB. Пока он не разрешён и не авторизован, корреляция и cross-team публикация по нему запрещены. Неизвестный `service_id` не ставится в ожидание.
7. `group_id` не передаётся в payload и не обязателен в модели Change. Существующий Group RBAC продолжает работать внутри IR через Team/Service.
8. Одна операция — один `Change` и множество неизменяемых `ChangeEvent`. Повторы идентичных событий идемпотентны; события могут приходить не по порядку.
9. Разделяются `changed` (непосредственное изменение), `reported_affected` (заявленное отправителем влияние) и `inferred_affected` (вывод по Dependencies). Автоматический вывод не становится подтверждённым фактом.
10. Отправитель не может получить доступ к чужой Team или создать доверенное влияние на её сервис одной лишь подстановкой slug либо ID.
11. Корреляция асинхронна; её сбой не отменяет сохранение ChangeEvent. Автоматический пересчёт не стирает ручное подтверждение или отклонение связи.
12. Change Events не меняют статусы Service/AlertGroup/Incident, не запускают уведомления, эскалацию, создание Incident или rollback.
13. Существующие `ServiceEvent`, `ServiceDependency`, `Incident`, `AlertGroup`, токены и RBAC используются повторно без нарушения действующих API.

## 3. Схема компонентов

```text
GitLab / Jenkins / Terraform / Kubernetes / Ansible / Custom
                         |
                         v
             POST /api/change-events
      Auth -> scopes -> source/team grants -> Pydantic
                         |
                         v
              Service Identity Resolver
       service_id OR (team namespace + service_slug)
                         |
                         v
                atomic DB transaction
        Change + ChangeEvent + ChangeServiceReference
           + ChangeService (if already resolved)
           + durable outbox/job record
                         |
                    HTTP 201/200
                         |
                         v
                   Scheduler worker
                /                   \
               v                     v
    Pending reference resolver    Impact / correlation
           |                        |
           |                        v
           |            ChangeImpact / ChangeAlertGroupCorrelation
           |                        |
           +-------> resolved ------+
           ^                        |
           |                        v
    CMDB creates/updates      Changes Inbox / Timeline /
      Service/Dependency      AlertGroup / Incident UI
```

HTTP `201` означает **событие сохранено**, а не «все slug разрешены» или «корреляция завершена». Разрешение ожидающих ссылок и корреляция выполняются повторяемыми фоновыми заданиями.

## 4. Модель данных

### 4.1. `Change` — каноническая операция

- `id`, `uid` (UUID);
- `owner_team_id` (FK Team; вычислен из `owner_team_id` или `owner_team_slug` запроса; при обычных событиях неизменяем);
- `source` (логическое пространство имён интеграции, например `terraform-prod`);
- `external_change_id` (значение API `change_id`);
- `kind` (`deployment`, `configuration`, `infrastructure`, `database`, `feature_flag`, `other`);
- `title`, `description`, `environment`, `external_url` (ограниченная длина);
- `status` (`unknown`, `running`, `succeeded`, `failed`, `rolled_back`, `cancelled`);
- `mapping_status` (`mapped`, `partially_mapped`, `unmapped`, `mapping_failed`);
- `started_at`, `completed_at`, `first_occurred_at`, `last_occurred_at`, `created_at`, `updated_at`;
- `revision` — монотонная ревизия агрегата для конкурентного обновления и фоновых задач.

**Уникальность:** `(owner_team_id, source, external_change_id)`.

`Change` является проекцией событий, а не источником неизменяемой истины. Статус операции независим от её возможного влияния на доступность сервисов.

### 4.2. `ChangeEvent` — неизменяемое событие

- `id`, `uid`, `change_id` (FK на Change);
- `external_event_id` (`event_id` в API), `event_type`;
- `occurred_at` (у отправителя), `received_at` (в IR), опциональный `source_sequence`;
- `actor_type`, `actor_label`, `external_url`, ограниченный `details`;
- нормализованный snapshot **полученных ссылок** на сервисы и исходная ограниченная форма запроса для диагностики;
- `request_digest`, `ingest_token_id` или безопасная идентичность принципала для аудита;
- `schema_version`.

**Уникальность:** `(owner_team_id, source, external_event_id)` через материализованные поля или эквивалентную уникальную constraint. Повтор с тем же digest возвращает существующее событие; тот же ID с иным содержимым — `409 Conflict`.

Типы: `change.started`, `change.updated`, `change.succeeded`, `change.failed`, `change.rolled_back`, `change.cancelled`. `kind` хранится отдельно, продуктовые метаданные — в `details`.

### 4.3. `ChangeServiceReference` — полученные идентификаторы и отложенное разрешение

Хранит каждую уникальную ссылку на сервис, переданную отправителем, включая те, для которых соответствующий Service ещё не существует.

- `change_id`, `first_event_id`, `relation_type` (`changed` / `reported_affected`);
- `ref_type` (`id` / `slug`), `requested_service_id`, `requested_service_slug`;
- `requested_team_id`, `requested_team_slug` либо вычисленный `owner_team_id`;
- `normalized_ref_key`: например `id:12` или `slug:infrastructure/postgresql-prod`;
- `resolved_service_id` (nullable FK), `resolution_status` (`resolved`, `pending_resolution`, `denied`, `invalid`);
- `verification_state` (`trusted`, `unverified`, `rejected`), `resolved_at`, `last_attempt_at`, `last_error_code`.

**Уникальность:** `(change_id, relation_type, normalized_ref_key)`. Это защищает от дубликатов при повторных событиях; разные идентификаторы одного и того же сервиса дополнительно объединяются в канонической связи `ChangeService`.

Исходные slug и Team namespace сохраняются даже после успешного разрешения. Для `pending_resolution` нет привязки к несуществующему Service и не создаётся мнимое влияние. Запросы разрешения не имеют права автоматически создавать Team/Service/Dependency.

### 4.4. `ChangeService` — каноническая связь

- `change_id`, `service_id` (FK на технический Service);
- `relation_type`: `changed` или `reported_affected`;
- `first_reference_id`, `verification_state`, `created_at`;
- опциональный snapshot исходных идентификаторов для диагностики смены slug.

**Уникальность:** `(change_id, service_id, relation_type)`. Владелец Service не обязан совпадать с `owner_team_id` Change. Все алгоритмы влияния и корреляции опираются на эту таблицу, **не на текст из payload**.

### 4.5. `ChangeImpact` — вычисляемая проекция

Предполагаемое косвенное влияние: `change_id`, `service_id`, `origin_service_id`, `dependency_path_snapshot`, `depth`, `reason`, `computed_at`, `engine_version`, `active`. Выводится по **обратному обходу** `ServiceDependency` от изменённых сервисов. Не смешивается с сообщёнными отправителем фактами. При изменении графа пересчитывается с сохранением evidence/version.

### 4.6. `ChangeAlertGroupCorrelation`

- `change_id`, `alert_group_id`, ключ конкретного firing/reopen-эпизода;
- `score` — релевантность, **не** вероятность первопричины;
- `reason`, ограниченный структурированный `evidence`, `engine_version`, `computed_at`;
- `review_status`: `suggested`, `confirmed`, `rejected`;
- `relation_type`: `potential_cause`, `cause`, `mitigation`, `context`;
- `reviewed_by`, `reviewed_at`, `updated_at`.

Уникальность учитывает Change, AlertGroup и эпизод. Автоматический перерасчёт не стирает ручное решение и не переносит его на новую вспышку.

### 4.7. `ChangeIncidentLink`

- `change_id`, `incident_id`;
- `relation_type`: `context`, `potential_cause`, `confirmed_cause`, `mitigation`;
- `linked_by`, `linked_at`, `removed_by`, `removed_at`.

Операционная связь не требует AlertGroup. Все изменения связей аудируются.

### 4.8. `ChangeJob` — durable outbox / work queue

- `job_type`, `entity_id`, `target_revision`, `state`, `attempts`, `next_attempt_at`;
- `lease_owner`, `lease_expires_at`, `last_error_class`, `created_at`.

Запись события, ссылок и outbox — **одна транзакция**. Нужны атомарный claim, lease, retry, уникальность логической работы и защита от устаревших заданий. Основные типы: `resolve_references`, `refresh_impacts`, `refresh_correlations`, `sync_service_timeline`.

## 5. Универсальный контракт API

```http
POST /api/change-events
Authorization: Bearer <changes:ingest token>
Content-Type: application/json
```

### 5.1. Рекомендуемый payload — только slugs, без внутренних ID IncidentRelay

```json
{
  "schema_version": 1,
  "event_id": "postgres-config-1842-applied",
  "change_id": "postgres-config-1842",
  "source": "terraform-production",
  "owner_team_slug": "infrastructure",
  "kind": "configuration",
  "event_type": "change.succeeded",
  "occurred_at": "2026-10-10T14:00:00Z",
  "title": "PostgreSQL connection settings updated",
  "environment": "production",
  "changed_services": [
    {"service_slug": "postgresql-prod"}
  ],
  "affected_services": [
    {"team_slug": "devops", "service_slug": "payments-api"},
    {"team_slug": "payments", "service_slug": "checkout-api"}
  ],
  "actor": {"type": "automation", "name": "terraform-ci"},
  "external_url": "https://ci.example/jobs/1842",
  "details": {"parameter": "max_connections", "commit": "abc123"}
}
```

`changed_services[0].service_slug` разрешается **только внутри `owner_team_slug=infrastructure`**. Cross-team затронутые сервисы указываются с явным `team_slug`. Pipeline не знает ни одного числового ID IR.

### 5.2. Альтернатива — числовые ID и смешанные ссылки

```json
{
  "schema_version": 1,
  "event_id": "postgres-config-1843-applied",
  "change_id": "postgres-config-1843",
  "source": "terraform-production",
  "owner_team_id": 2,
  "kind": "configuration",
  "event_type": "change.succeeded",
  "occurred_at": "2026-10-10T15:00:00Z",
  "title": "PostgreSQL settings updated",
  "changed_services": [
    {"service_id": 12}
  ],
  "affected_services": [
    {"service_id": 34},
    {"team_id": 9, "service_slug": "checkout-api"}
  ]
}
```

`changed_services` и `affected_services` — предпочтительные поля, принимающие список ссылок двух видов. Для простых числовых клиентов допускаются сокращения `changed_service_ids: [12]` и `affected_service_ids: [34,56]`. **Нельзя** одновременно указывать сокращённое и развёрнутое поле одной роли в одном событии — `422`.

### 5.3. Правила разрешения

| Вход | Разрешение |
|---|---|
| `owner_team_id` | Team по числовому ID |
| `owner_team_slug` | Team по уникальному `Team.slug` |
| `{ "service_id": 12 }` | Service по ID; если дополнительно передан Team namespace, проверяется совпадение владельца |
| `{ "service_slug": "postgresql-prod" }` | Service по `(owner_team_id, Service.slug)` |
| `{ "team_slug": "devops", "service_slug": "payments-api" }` | Сначала Team по slug, затем Service по `(team_id, slug)` |
| `{ "team_id": 9, "service_slug": "checkout-api" }` | Service по `(9, "checkout-api")` |

- В одном payload задаётся **ровно одно** из `owner_team_id` / `owner_team_slug`. В ссылке на сервис — ровно одно из `service_id` / `service_slug`. В Team namespace — не более одного из `team_id` / `team_slug`.
- Slug валидации должен соответствовать существующему API Service (строчные символы, цифры и дефис); Team slug проверяется по действующей модели Team. Глобального поиска одного `service_slug` по всем командам **нет**.
- Если `service_id` найден, но переданный Team namespace противоречит его владельцу, запрос отклоняется. Если slug указывает на удалённый/недоступный ресурс, доступ и публикация проверяются так же строго, как при ID.
- `owner_team_*` должен однозначно разрешаться уже при ingestion: иначе невозможно безопасно проверить владельца Change и токен. Несуществующая owner Team — ошибка; она **не создаётся автоматически**.
- Неизвестный `service_id` — ошибка валидации ссылки. Неизвестный `service_slug` в существующей Team — допустимое `pending_resolution` при выполнении проверок области полномочий. Неизвестная `team_slug` в ссылке на сервис — ошибка, а не повод угадать Team по глобальному Service slug.
- Для `changed` проверяем полномочия на изменение указанной области; для `reported_affected` чужой Team получаем непроверенное утверждение до доказательства через граф или grants. Само принятие pending-ссылки **не** предоставляет полномочий на сервис.
- При успешном сопоставлении сохраняем `service_id`; используем его в `ChangeService`, `ChangeImpact` и корреляции. Полученную slug-ссылку сохраняем в `ChangeServiceReference`.
- Удаление, перенос или переименование Service не перепривязывает исторически разрешённый Change к новому Service с тем же slug. Повторное использование slug должно контролироваться CMDB; при переименовании нужна корректировка источника/alias mapping, а не тихое переприсвоение истории.
- `event_id` повторно используется **только** с тем же нормализованным содержимым запроса. Изменение представления с ID на slug под тем же `event_id` может дать `409`, даже если обе ссылки ведут на один Service. Для новой информации нужен новый `event_id`.

Для уведомления о частичном сопоставлении ответ `201` включает безопасные счётчики `resolved_refs`, `pending_refs` и `correlation_status=queued`, но не раскрывает чужие сервисы. `200` возвращается при точном повторе; `400/422` — некорректная схема/неразрешимая идентичность, `401` — нет авторизации, `403` — запрещённая область, `409` — конфликт внешнего ID, `429` — rate limit.

### 5.4. Read/review API

```text
GET    /api/changes
GET    /api/changes/{id}
GET    /api/changes/{id}/events
GET    /api/changes/{id}/services
GET    /api/changes/{id}/correlations
POST   /api/changes/{id}/correlations/{correlation_id}/review
GET    /api/services/{service_id}/changes
GET    /api/alert-groups/{alert_group_id}/related-changes
GET    /api/incidents/{incident_id}/changes
POST   /api/incidents/{incident_id}/changes
DELETE /api/incidents/{incident_id}/changes/{link_id}
```

Чтение Changes поддерживает фильтр `service_id` **либо** `service_slug` с Team namespace, используя тот же resolver. RBAC проверяется для каждого эндпоинта и применяется в SQL **до** пагинации.

## 6. Интеграция с CMDB и позднее сопоставление сервисов

CMDB отвечает за создание/обновление `Team`, `Service` и `ServiceDependency` через собственный процесс синхронизации. Change Intelligence **не** создаёт сервисы или зависимости и **не** требует изменений CMDB-протокола. Синхронизация может произойти раньше или позже ChangeEvent.

### 6.1. Сценарий: Service уже создан CMDB

1. CMDB создаёт Team `infrastructure`, Service `postgresql-prod`, зависимость `payments-api → postgresql-prod`.
2. Terraform отправляет `owner_team_slug=infrastructure`, `changed_services=[{"service_slug":"postgresql-prod"}]`.
3. Resolver однозначно находит `service_id` по Team + slug. Исторический Change ссылается на ID и хранит исходный slug.
4. Correlation Engine обходит граф и может предложить связь с AlertGroup `payments-api`, независимо от его Team.

### 6.2. Сценарий: ChangeEvent пришёл раньше Service

1. Owner Team и Team namespace известны, но `Service.slug` ещё нет в каталоге.
2. ChangeEvent сохраняется; `ChangeServiceReference.status=pending_resolution`. В Changes Inbox владельца показываем **Unmapped/Pending mapping**.
3. Pending-ссылка не материализуется в `ChangeService`, не влияет на чужие Inbox и не участвует в корреляции.
4. CMDB создаёт Service. Событие изменения Service Catalog (при наличии hook) либо периодическая фоновая задача запускает повторное сопоставление по **той же Team + slug**.
5. После проверки **текущих** scope/grants ссылка становится разрешённой, записывается канонический `service_id` и ставятся задания на Influence/Correlation/Service Timeline — в том числе для AlertGroups, которые появились до синхронизации.
6. Если grant не позволяет действие, ссылка получает `denied`, не публикуется и требует административного исправления. Нет автоматического обхода RBAC из-за того, что запись была принята ранее.

Ожидающие ссылки имеют срок жизни, ограниченные попытки, причину ошибки и диагностический статус. Их нельзя бесконечно искать полным сканированием всей истории. Нужны индексы по Team namespace + slug и `pending_resolution`.

### 6.3. Изменение графа зависимостей

При добавлении, удалении или изменении `ServiceDependency` существующие Change остаются неизменными, а **производные** `ChangeImpact`/correlations можно пересчитать по ограниченному историческому окну. Версия/дата графа включаются в evidence, чтобы объяснение оставалось интерпретируемым.

**Правило стабильности slug:** пайплайнам следует использовать slug, управляемые CMDB, и не переиспользовать их для другой сущности. Для организаций с частыми переименованиями можно позже добавить явный `external_service_ref` или использовать существующий `Service.uid`, но это не требуется для v1.

## 7. Authentication, токены и RBAC

**Генерация токенов — существующий `Profile → API Tokens → Generate Token`** (`POST /api/profile/tokens`). Используются текущие механизмы случайного секрета, хранения только хеша, срока действия и отзыва. Route intake token не используется.

Новые scopes:

- `changes:ingest` — только `POST /api/change-events`;
- `changes:read` — просмотр Changes и истории;
- `changes:write` — ручные операции корреляции и связи с Incident.

`changes:ingest` **не наследуется** из legacy `resources:write`: машинному отправителю выдаётся явно. Админский `*` работает в рамках текущей модели, но не отменяет проверку team/source grants там, где она необходима. Для новых URL требуется явное scope mapping в `app/services/api_token_scopes.py` (по умолчанию неизвестные endpoint для API tokens закрыты).

В модели `ApiToken` уже имеется FK `team`, но текущие `Profile` UI и endpoint его не назначают. Добавить ограничение по Team при создании персонального токена и enforce в Change ingestion. Отправитель может задавать `owner_team_id` **или** `owner_team_slug`; после resolution оба обязаны соответствовать разрешённой владельцу токена Team. Для центральных CI нужны **явные**, отдельно управляемые grants на необходимые source/Teams/Services, а не привилегия от самого payload.

**Cross-team политика:**

1. Owner Team разрешается и авторизуется **перед** созданием Change. Нет доверия к самодекларируемым `source`, Team ID или slug.
2. `changed` требует прав заявлять изменение соответствующего Service или заранее выданного grant. Даже если Service задан только slug, проверяются права на его Team namespace и повторно — при отложенном разрешении.
3. Чужой `reported_affected` — неподтверждённая подсказка. Она не видна чужой Team и не считается доказательством влияния до подтверждения проверенным Dependency path либо разрешённым grant. Запрос не может получить список существующих чужих сервисов через сообщения об ошибках.
4. `inferred_affected` строится по серверному графу Dependencies; видимость появляется лишь в доступном пользователю scope.
5. Владелец Change видит полные данные, на которые у него есть права. Чужая затронутая Team видит **redacted projection**: доступный ей Service, время, безопасный тип связи. Без permission владельца нет сырых details, закрытых названий чужих Service, actor и URL.
6. Подтверждение/отклонение корреляции требует прав на соответствующий AlertGroup; это не даёт права редактировать исходный Change.
7. Группы остаются внутренними RBAC-границами IncidentRelay; `group_id` в публичном Change API не вводится.

**Отзыв токена / смена прав:** новые запросы немедленно запрещаются. Pending-ссылки перепроверяют текущие разрешения при сопоставлении и не становятся доверенными на основании старых прав.

## 8. Lifecycle и обработка out-of-order

- `event_id` обеспечивает идемпотентность; `change_id` связывает разные стадии одной операции.
- Состояние Change детерминированно вычисляется из событий с учётом достоверного `source_sequence`, `occurred_at` и стабильных tie-breaker-правил. `received_at` — аудит, не время фактического изменения.
- Запоздавший `change.started` после `change.succeeded` не переводит операцию обратно в `running`. `change.rolled_back` с более поздним фактическим временем может заменить `succeeded` на `rolled_back`.
- Сервисные ссылки на стадиях могут дополняться. Отсутствие списка сервисов в следующем событии **не означает** удаления ранее установленных связей; автоматическое удаление связей из-за пустого payload недопустимо.
- Новая ссылка по slug может остаться pending независимо от статуса операции; `mapping_status` отделён от `Change.status`.
- Неполные/неоднозначные переходы, чрезмерный clock skew и конфликты source sequence фиксируются диагностикой без молчаливого «исправления» истории.
- При корреляции учитывается начало текущего firing/reopen-эпизода AlertGroup, а не навсегда привязанный `first_seen_at` старой группы.

## 9. Change Intelligence / Correlation

1. Вход — успешно сопоставленные и авторизованные `changed` и доверенные `reported_affected` сервисы (**числовые ID**, даже если присланы slug).
2. По `ServiceDependency` выполняется обратный обход: `payments-api depends_on postgresql-prod` ⇒ изменение PostgreSQL **может повлиять** на `payments-api`.
3. `ChangeImpact` фиксирует путь, глубину, среду, версию графа и объяснение. Введены пределы обхода, количества кандидатов и времени исполнения.
4. Среди AlertGroups ищем подходящие эпизоды в настраиваемом интервале после изменения (начальное предложение — 2 часа). Change, произошедший **после** ошибки, может быть `mitigation`, а не предполагаемой причиной.
5. Вычисляется детерминированный relevance score на основе времени, Service, environment, типа и направления зависимости, качества evidence.
6. Сохраняются `ChangeAlertGroupCorrelation` и понятное объяснение. Подтверждённые/отклонённые связи не перезаписываются.
7. Корреляция запускается при новых ChangeEvents, новых/reopened AlertGroups, позднем сопоставлении slug после CMDB-sync и релевантных изменениях Dependencies.

**Нельзя:** трактовать score как вероятность root cause, вызывать rollback, менять Incident status либо запускать paging/escalation только из-за временного совпадения.

## 10. UI

**Operations → Changes** — самостоятельный Inbox, одна строка на Change.

- Поиск по ID, названию, source, внешнему ID, доступным сервисам и их `service_slug`.
- Фильтры: Team (owner **или** доступная затронутая), Service (ID или slug с Team namespace), `kind`, status, source, environment, даты, корреляция, `unmapped/pending`.
- Одна строка на Change при нескольких затронутых Teams; RBAC-фильтрация и `DISTINCT` выполняются сервером до пагинации и подсчёта.
- Change Details: история стадий, **Changed**, **Reported affected**, **Inferred impact**, состояния сопоставления slug, связанные AlertGroups/Incidents, evidence, внешние ссылки и безопасный JSON.
- Для `pending_resolution` — исходный slug/Team namespace, причина ожидания и момент последней попытки (в доступном владельцу scope); **без** кнопки «создать Service» автоматически.
- AlertGroup Details: Related Changes с reason/score/review. Incident Details: контекст изменения и его роль (`potential_cause` / `mitigation`).
- Service Timeline: существующий `ServiceEvent` (`category=change`, стабильный `dedup_key`, ссылка на канонический ChangeEvent), только после разрешения `service_id`. Не утверждаем, что inferred-affected Service был непосредственно изменён.
- Redacted view для чужих Teams: собственный сервис, безопасные тип/время/тип связи, без закрытой топологии, полного payload, actor и URL.

## 11. Технические требования и эксплуатация

- Pydantic v2 с валидацией альтернативных ID/slug форм, строгой взаимной исключительностью полей, ограничениями длины slug/строк/числа ссылок/HTTP body/`details`. Без глобального поиска Service.slug.
- `POST /api/change-events` **всегда требует токен**, даже если глобальная обязательность API auth отключена в конфигурации.
- Уникальные ключи на уровне БД; запись ChangeEvent, ссылок и outbox в одной транзакции. PostgreSQL использует атомарные upsert/row locks; SQLite — короткие транзакции и retry при блокировке.
- Durable scheduler jobs, атомарные claims/lease, экспоненциальные retries и dead-letter/diagnostics. Не требовать Redis/Celery и не держать задания только в памяти Flask.
- Индексы: `Change(owner_team_id,last_occurred_at)`, уникальные внешние IDs, `ChangeService(service_id,change_id)`, `ChangeServiceReference(resolution_status,requested_team_id,requested_service_slug)`, `ChangeImpact(service_id,active)`, `ChangeAlertGroupCorrelation(alert_group_id,review_status)`, `ChangeJob(state,next_attempt_at)`.
- При изменении Team/Service slug исторические разрешённые ссылки остаются на прежних `service_id`; pending пересопоставляется только при корректном текущем имени и полномочиях. Никакого неконтролируемого rebinding при повторном использовании slug.
- Проверки доступности и RBAC применяются **в SQL до LIMIT/OFFSET/cursor**, включая списки, счётчики, связанные корреляции и Explain.
- Никаких высококардинальных `change_id`, `event_id`, `service_id`, raw slug или произвольного `source` в Prometheus labels. Метрики: ingest accepted/duplicate/rejected; unresolved refs; resolution latency; outbox backlog; correlation duration/errors.
- Не логировать токены и весь произвольный `details`; безопасные URL-схемы, контент-экранирование, timeouts, rate limits и retention без потери доказательств, связанных с Incident.
- Локализация EN/RU/DE/FR/ES/ZH; OpenAPI, позитивные и security tests на PostgreSQL/SQLite. Старые `ServiceEvent(category=change)` не преобразуются без достоверного соответствия внешним Change IDs.

## 12. Порядок реализации

**Фаза 1 — Change Registry:** модели/миграции; `owner_team_id`/`owner_team_slug`; ID/slug service resolver и pending references; scopes, team/source grants; единый POST; дедупликация; GET API; Changes Inbox/Details; тесты безопасности и идемпотентности. Система полезна как история изменений ещё до корреляции.

**Фаза 2 — Change Intelligence:** обход Dependencies, cross-team impact с redaction, корреляция и объяснения, обработка поздних событий и CMDB-reconciliation, ручной review, метрики, безопасные background jobs.

**Фаза 3 — UI integrations:** Service Timeline, AlertGroup Related Changes, Incident links, полная документация отправки из CI/CD и CMDB-sync troubleshooting, e2e и regression tests. Специальные плагины под продукты не обязательны.

## 13. Критерии приёмки

1. ChangeEvent с одним `owner_team_slug` и `service_slug` успешно сохраняется и связывается с правильным Service **без ID**.
2. Один и тот же `service_slug` у двух Teams разрешается строго по `team_slug`/`team_id` либо owner Team; **никакого** случайного межкомандного связывания.
3. Один Change содержит комбинацию `service_id` и `(team_slug,service_slug)` в разных ссылках; каноническая `ChangeService` не содержит дубликатов.
4. Infrastructure Team меняет `postgresql-prod`; DevOps видит только безопасную карточку для зависимого `payments-api`, без закрытого payload Infrastructure Team.
5. Неизвестный slug в существующей Team сохраняется как pending и позднее сопоставляется после создания Service из CMDB, после чего пересчитывается влияние на уже существующие AlertGroups.
6. Неизвестный Team namespace, отсутствующий числовой Service ID и конфликт ID/Team проверяются как ошибки без раскрытия информации о чужих ресурсах.
7. Повтор того же `event_id` идентичен (`200`) или конфликтен (`409`); создание параллельными запросами не порождает дублей.
8. Операция с тремя ChangeEvents — **одна** строка Changes с корректным статусом при приходе событий не по порядку.
9. `reported_affected` с чужим slug не становится доверенным влиянием и не публикуется чужой Team лишь из-за заявления отправителя.
10. После переименования slug ранее разрешённый Change остаётся связанным со старым `service_id`, а не с новой сущностью, которой повторно назначили slug.
11. Корреляция работает при Change → AlertGroup и AlertGroup → Change, в том числе при поздней CMDB-синхронизации и повторном firing.
12. Ручное подтверждение/отклонение не стирается перерасчётом или сменой графа.
13. Перезапуск worker не теряет задания и не создаёт дубликатов; приём не зависит от доступности корреляции.
14. API token с `changes:ingest` не читает данные Changes и не редактирует Incident; отзыв/смена scope немедленно ограничивает новые запросы и pending-mapping.
15. Нет утечек через Inbox, фильтры, пагинацию, Change Details, Service Timeline, Explain и внешний URL.
16. Все миграции, scope grants, ID/slug resolver, конкурентность и фоновые задачи проверены на PostgreSQL и SQLite.

## 14. Соответствие существующему IncidentRelay

В `release/2.3.1` уже есть `Team.slug` (**глобально уникальный**), `Service.slug` (**уникальный внутри Team** через индекс `(team,slug)`), `Service.uid`, `ServiceEvent(category=change)` с `dedup_key`, `ServiceDependency`, `AlertGroupCorrelation` (это **AlertGroup ↔ AlertGroup**, а не Change ↔ AlertGroup), `Incident`, `IncidentAlertGroupLink`, `ApiToken.team`, `Profile → API Tokens`, `api_token_scopes.py`, `app/services/db_lock.py` и scheduler.

Существующий `Profile` endpoint выдачи токена пока не назначает `ApiToken.team`; для Change ingestion нужно доработать его безопасно. Существующий Service API уже использует числовой `team_id` и `slug` при создании Service, поэтому resolver по `(team_id, slug)` соответствует текущим ограничениям БД и не требует менять модель уникальности.

Предлагаемые новые файлы: `app/services/change_intelligence/` (включая `identity.py` и `reconciliation.py`), `app/modules/db/changes_repo.py`, `app/api/schemas/changes.py`, `app/views/changes_view.py`, `app/api/openapi/endpoints/changes.py`, `app/templates/pages/changes.html`, `app/static/js/pages/changes.js`, `app/static/css/changes.css`, миграции, переводы, тесты и документация.

**Итог:** унифицированный Change Events API принимает ID **или** человечески управляемые slug, но всё внутри IR опирается на авторизованные канонические ID. Независимая CMDB может создавать сервисы и зависимости, а Change Intelligence безопасно разрешает поздние ссылки, учитывает межкомандное влияние и сохраняет прозрачную историю расследования.
