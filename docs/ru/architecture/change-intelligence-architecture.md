# IncidentRelay — Change Intelligence

**Архитектурный RFC v1.1 (контракт реализации)**

**Исходная кодовая база:** `release/2.5.0` (проверена 2026-10-28)

**Статус:** хранение этапа 1 реализовано; этапы 2–10 запланированы


## Согласованные решения — 28 октября 2026

- Отдельная история AlertGroupEpisode, которую записывают новые lifecycle-операции, без реконструкции прошлых циклов. Публичный приём Change Events включается после приёмки полного пути от события до связи с алертом.
- Постоянная интеграция, зарегистрированные source/Team/Service grants и сменяемые машинные токены.
- Отзыв токена запрещает новые запросы; принятая работа использует текущие grants интеграции.
- Source выбирает timestamp или sequence. Timestamp — occurred_at отправителя, никогда received_at.
- Побеждает последнее финальное событие в выбранном порядке; разные итоги с равным временем дают явный конфликт до более позднего финального события.
- Автоматика предлагает только возможные причины; mitigation в v1 ручная.

Хранение первого этапа реализовано в рабочем дереве; см. [миграцию и проверки](change-intelligence-stage-1.md). Runtime-поведение и API этапов 2–10 остаются планом и не включены.

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
14. Корреляция и ручной review привязаны к постоянному AlertGroupEpisode, а не только к повторно используемой AlertGroup.
15. Pending-ссылка закрепляет числовой namespace_team_id; переименование Team и ротация токена не меняют её владельца.
16. Worker публикует только с актуальными lease, requested generation и ревизиями входов; ручные решения отделены от вычисляемых полей.

## 3. Схема компонентов

```text
GitLab / Jenkins / Terraform / Kubernetes / Ansible / Custom
                         |
                         v
             POST /api/change-events
      Auth -> Pydantic -> registered source/team grants
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

- `id`, `uid` (UUID), `integration_id`, `source_id` (FK `ChangeSource`);
- `owner_team_id`, `external_change_id` (`change_id` API); имя отправителя хранится в `ChangeSource.source`; владелец и идентичность source неизменяемы;
- `kind`: `deployment`, `configuration`, `infrastructure`, `database`, `feature_flag`, `other`;
- `kind`, `environment` — неизменяемая идентичность операции; для другой операции/повторного запуска нужен новый `change_id`;
- ограниченные `title`, `description`, `external_url`;
- `status`: `unknown`, `running`, `succeeded`, `failed`, `rolled_back`, `cancelled`;
- `lifecycle_conflict` и ограниченные диагностические коды; при конфликте финальных исходов `status=unknown`;
- `mapping_status`: `mapped`, `partially_mapped`, `unmapped`, `mapping_failed`;
- `ordering_mode` (`timestamp` / `sequence`), скопированный из зарегистрированного source при создании и неизменяемый для этого Change;
- `started_at`, `completed_at`, `first_occurred_at`, `last_occurred_at`, `created_at`, `updated_at`;
- `revision`, увеличиваемая при новом принятом событии или изменении проекции сопоставления/полномочий; точный повтор и чтение её не меняют.

**Уникальность:** `(source_id, external_change_id)`. Source однозначно связывает `(owner_team_id, source)` с одной интеграцией (§4.10), сохраняя публичное пространство имён. Payload не может переносить операцию другому владельцу или интеграции.

Change — восстанавливаемая проекция. Порядок событий, конфликты итогов и обновление полей определены в §8. Успешное выполнение не означает отсутствия вредного влияния.

### 4.2. `ChangeEvent` — неизменяемая история

- `id`, `uid`, `change_id`, `source_id`, `external_event_id` (`event_id` API), `event_type`;
- `occurred_at` (время события у отправителя), `received_at` (время приёма IR), `source_sequence` по §8;
- ограниченные `actor_type`, `actor_label`, `details`, а также явный snapshot присланных полей проекции с различением отсутствующего поля и null;
- нормализованные полученные ссылки на сервисы и ограниченный диагностический snapshot запроса с удалёнными секретами;
- `request_digest`, `integration_id`, nullable `ingest_token_id` для аудита использованного секрета, `schema_version`.

**Уникальные ключи:** `(source_id, external_event_id)` и `(change_id, source_sequence)` для непустого sequence. Event ID относится ровно к одной операции. Использование его с другим `change_id` даёт `409`, даже если остальные поля совпали. При retention нужно сохранять компактную запись идентичности/digest на документированный срок допустимых повторов, чтобы старое событие не создавало новую работу.

Для идемпотентности хешируется валидированное присланное содержимое, включая `change_id`, без токена, `received_at` и последующих результатов сопоставления. Используются канонический порядок JSON-ключей, UTC-время с микросекундной точностью, нормализация сокращённых полей и отсортированные множества ссылок без дублей. ID и slug остаются разными представлениями. Избыточная точность времени отклоняется, а не округляется молча. Digest вычисляется до удаления секретов; исходные секреты и вторая полная неочищенная копия payload не сохраняются.

Точный авторизованный повтор возвращает прежнее событие (`200`), не увеличивает revision и не создаёт задания; другой digest даёт `409`. Даже для повтора проверяются текущие права на владельца/source. Устаревший неразрешимый owner slug даёт ошибку идентичности, а не обход авторизации через глобальный поиск event ID. История сохраняет канонические ID; отправителям, которым нужны повторы независимо от переименований, следует изначально использовать ID владельца.

Типы: `change.started`, `change.updated`, `change.succeeded`, `change.failed`, `change.rolled_back`, `change.cancelled`. Последующие изменения полномочий или сопоставления не меняют события и исходные ссылки.

### 4.3. `ChangeServiceReference` — полученные идентификаторы и отложенное разрешение

- `change_id`, `first_event_id`, `relation_type` (`changed` / `reported_affected`);
- `ref_type` (`id` / `slug`), исходные `requested_service_id` / `requested_service_slug` и `requested_team_id` / `requested_team_slug`;
- **`namespace_team_id` (обязательный FK Team)**, разрешённый и авторизованный при приёме, даже если Service пока неизвестен;
- `normalized_ref_key`: `id:12` или `slug:team-id:9/postgresql-prod`; namespace определяется каноническим ID Team, а не изменяемым slug;
- nullable `resolved_service_id`, `resolution_status`: `resolved`, `pending_resolution`, `denied`, `invalid`, `expired`;
- `verification_state`: `trusted`, `unverified`, `rejected`; evidence/версия проверки, `resolved_at`, `last_attempt_at`, `attempts`, `expires_at`, `last_error_code`.

**Уникальность:** `(change_id, relation_type, normalized_ref_key)`. Разные полученные формы ссылки сохраняются, но сходятся в одной канонической связи ChangeService. Уже разрешённая ссылка автоматически не перепривязывается.

Поиск pending выполняется строго по `(namespace_team_id, requested_service_slug)` при активной Team и неудалённом Service. Переименование/повторное использование Team slug не меняет ID; удаление или перенос namespace не запускает поиск другой Team. Перенос Service из закреплённого namespace требует явной проверки, а не перепривязки. Переименование ожидаемого Service slug требует нового события/ссылки; угадывания alias в v1 нет. Истечение срока/отказ видны владельцу; после исправления grants возможен явный повтор с аудитом и новой генерацией задания.

Создание Team/Service/Dependency остаётся вне подсистемы. Ограниченное повторное сопоставление описано в §6, одинаковые ответы для неавторизованных ссылок — в §7.

### 4.4. `ChangeService` — каноническая связь

- `change_id`, `service_id` (FK на технический Service);
- `relation_type`: `changed` или `reported_affected`;
- `first_reference_id`, `verification_state`, evidence проверки и `input_stamp`, `created_at`, `updated_at`;
- опциональный snapshot исходных идентификаторов для диагностики смены slug.

**Уникальность:** `(change_id, service_id, relation_type)`. Владелец Service не обязан совпадать с `owner_team_id` Change. Все алгоритмы влияния и корреляции опираются на эту таблицу, **не на текст из payload**.

### 4.5. `ChangeImpact` — вычисляемая проекция

Поля: `change_id`, `service_id`, `origin_service_id`, ограниченный `dependency_path_snapshot`, `depth`, `reason`, `computed_at`, `engine_version`, `input_stamp`, `active`. Уникальность: `(change_id, origin_service_id, service_id)`; несколько путей — ограниченный evidence, а не дубли строк влияния.

Обратный обход начинается с авторизованных канонических changed-сервисов и доверенных reported-affected сервисов. Доверие через граф должно опираться на авторизованный changed-сервис; присланные утверждения не подтверждают друг друга. Сохраняются snapshot использованного пути и ревизия графа; более поздний граф — новое evidence, а не доказательство существования этой топологии во время события. Текущие проекции заменяемы, но snapshots ручных решений сохраняются. Ревизии и правила обхода определены в §4.11 и §9.

### 4.6. `ChangeAlertGroupCorrelation`

- `change_id`, `episode_id` (FK `AlertGroupEpisode`; родитель эпизода определяет AlertGroup);
- `score` (релевантность, не вероятность), `reason`, ограниченный `evidence`, `input_stamp`, `engine_version`, `computed_at`, `active`;
- `review_status`: `suggested`, `confirmed`, `rejected`;
- `relation_type`: `potential_cause`, `confirmed_cause`, `mitigation`, `context`;
- `reviewed_by`, `reviewed_at`, неизменяемый snapshot evidence ручного решения, `row_version`, `updated_at`.

Уникальность: `(change_id, episode_id)`. Автоматика обновляет только вычисляемые поля и предлагает `potential_cause`; поля ручного решения не меняет. Review использует `row_version`, проверяет право реагировать на AlertGroup и читать хотя бы безопасную проекцию Change, атомарно пишет аудит. Устаревший review получает `409`. Изменение evidence может сделать предложение неактивным, но не удалить решение и не перенести его в другой эпизод. `mitigation` и `context` в v1 создаются вручную, в том числе без автоматического предложения.

### 4.7. `ChangeIncidentLink`

- `change_id`, `incident_id`, `relation_type`: `context`, `potential_cause`, `confirmed_cause`, `mitigation`;
- `linked_by`, `linked_at`, `removed_by`, `removed_at`, `row_version`.

Одна активная связь на `(change_id, incident_id)`; удаление мягкое, повторное добавление восстанавливает связь с записью истории в аудит. POST требует права реагировать на Incident и читать контекст Change; изменение роли/удаление проверяет `row_version`. Используется действующий контракт транзакции/CAS Incident: событие Incident, связь и аудит записываются атомарно. Повторное добавление той же роли — `200`, новая/восстановленная связь — `201`, устаревшее или конфликтующее изменение — `409`. Статус и уведомления Incident не меняются; AlertGroup не обязателен.

### 4.8. `ChangeJob` — durable outbox / очередь работы

- `job_type`, `entity_id`, `state` (`pending`, `running`, `done`, `dead`);
- `requested_generation`, `claimed_generation`, `completed_generation`;
- `target_revision`, `graph_revision`, `auth_revision`, `engine_version` (набор `input_stamp`);
- `lease_owner`, новый при каждом захвате `lease_token`, `lease_expires_at`;
- `attempts`, `next_attempt_at`, `last_error_class`, ограниченный discovery `cursor`, `created_at`, `updated_at`.

Уникальность: `(job_type, entity_id)`. Повторное планирование атомарно увеличивает `requested_generation`, а не создаёт неограниченные дубли. У выполняющегося задания lease сохраняется, новая генерация остаётся ожидающей до завершения/перехвата. Новую работу запрашивает изменение ревизии, а не точный повтор ingestion. Типы: `resolve_references`, `refresh_impacts`, `refresh_correlations`, `sync_service_timeline`, а также ограниченные discovery-задания для нового эпизода или ревизии каталога.

**Протокол фиксации:**

1. Ingestion записывает ChangeEvent, ссылки, ревизию агрегата и запрос задания одной транзакцией. Изменения эпизода/каталога сохраняют discovery-задание в своей транзакции; discovery надёжно создаёт задания затронутых Changes до подтверждения собственного завершения.
2. Claim атомарно выбирает готовую/просроченную работу, выдаёт новый lease token и фиксирует генерацию. PostgreSQL использует короткую транзакцию/row lock (`SKIP LOCKED` при конкуренции workers), SQLite — `BEGIN IMMEDIATE` с ограниченным повтором при busy. Вычисления выполняются вне write-транзакции.
3. Input stamp читается до загрузки зависимостей/сопоставлений. Изменения графа и прав увеличивают свои ревизии в транзакции изменения. Нельзя пометить старый snapshot новой ревизией, прочитанной после вычисления.
4. Публикация — одна короткая транзакция: проверить тот же непросроченный lease token, неизменность requested generation и актуальность input stamp, затем записать проекции/timeline и завершить генерацию. Сравниваемые строки ревизий блокируются/перепроверяются до commit; проверки только в памяти приложения недостаточно.
5. При несовпадении результат отбрасывается. Потерявший lease worker не может публиковать, подтверждать завершение, продлевать lease нового владельца или менять его retry-состояние. Ещё владеющий заданием worker планирует актуальную генерацию; recovery/discovery обеспечивает сохранность работы. Истечение lease не разрешает перезаписывать чужой результат.
6. Timeline использует уникальный `(service_id, source='change_intelligence', dedup_key)` из UUID события и роли связи. Проекции и подтверждение задания записываются одной DB-транзакцией: сбой не оставляет неподтверждённого неидемпотентного эффекта. Внешние уведомления не отправляются.
7. Повторяются только временные ошибки, с ограниченным экспоненциальным backoff/jitter. Ошибки валидации/прав остаются видимыми у ссылок, исчерпанные задания — в `dead`; ручной повтор аудируется и создаёт новую генерацию. Метрики показывают backlog, возраст старейшей работы и класс ошибки без payload/секретов.

Единый порядок блокировок: строка состояния графа → строка интеграции/прав → Changes по ID → задания. Claim/reclaim блокирует только задания. Действующий lifecycle сохраняет порядок Incident → AlertGroup → эпизод; эти транзакции лишь добавляют discovery и не берут graph/Change locks. Discovery записывает задания Changes до блокировки строки собственного подтверждения, исключая обратный порядок job → Change. Сетевых вызовов и обхода графа под этими блокировками нет.

### 4.9. `AlertGroupEpisode` — постоянная история технических циклов

Хранение добавлено на этапе 1: `id`, `uid`, `alert_group_id`, `ordinal`, nullable `started_at`, nullable `ended_at`, `state` (`open`, `resolved`, `merged`), `start_quality` (`exact`, `unknown`), nullable `start_event_id`, `end_event_id`, `created_at`. Уникальность `(alert_group_id, ordinal)` и не более одного открытого эпизода группы (частичное уникальное ограничение PostgreSQL/SQLite). Добавляется nullable `AlertGroup.current_episode_id`; после перехода writers на этапе 2 у активной группы он указывает на её открытый эпизод. Этап 1 оставляет указатели существующих групп NULL. ID эпизода не меняется при acknowledge, shelving и повторном intake.

- Создание новой активной группы создаёт первый эпизод атомарно с первым дочерним Alert и событием lifecycle. Настоящее повторное использование `resolved → active` создаёт следующий эпизод и нового ребёнка в той же транзакции. Повтор reopen не создаёт второй эпизод или второго ребёнка.
- Acknowledged → firing, unshelve, изменение severity/assignee остаются в прежнем эпизоде. Reopen операционного Incident сам по себе не открывает технический эпизод. Для группы, созданной сразу из resolved-входа, открытый эпизод не выдумывается.
- Resolve/merge закрывает текущий эпизод в транзакции закрытия группы, `current_episode_id` очищается. Повторный resolve уже закрытой группы — no-op и не может закрывать ещё не зафиксированный новый эпизод. Merge закрывает эпизод исходной группы, не превращая его в эпизод целевой.
- Контракт обязателен для всех технических записывающих путей: intake/recovery, ручных действий/callbacks, heartbeat, orchestration, merge и удаления ресурсов. Ошибка БД откатывает группу, ребёнка, эпизод, lifecycle event и discovery-задание вместе. Действующее поведение AlertGroup/Incident API и уведомлений сохраняется.
- Этап 1 создаёт только хранение: прошлые циклы не восстанавливаются, эпизоды, Changes и discovery-задания из старых алертов/событий не создаются. При переходе всех lifecycle writers на этапе 2 уже активная группа получает один текущий эпизод с `started_at=NULL, start_quality=unknown`, без разбора старых событий и подстановки `first_seen_at`. Это фиксация текущего состояния, а не восстановленная история. Повтор инициализации сохраняет существующие эпизоды. Временная автокорреляция пропускает неизвестное начало; новые циклы записываются по фактическим lifecycle-переходам. Прежние закрытые циклы не импортируются. Новая сразу терминальная группа также не создаёт вымышленного известного начала.
- Evidence ручного review и история, связанная с Incident, защищают соответствующие Changes/events/эпизоды от retention. Очистка сначала удаляет только допустимые непроверенные производные строки, затем родителей; каскад не уничтожает сохраняемые доказательства расследования. Новые FK и правила retention входят в миграцию эпизодов.

### 4.10. Постоянная интеграция, sources и grants

Модели хранения добавлены на этапе 1; администрирование и машинная авторизация реализуются на этапе 3:

- `ChangeIntegration`: `id`, `uid`, имя, `active`, `auth_revision`, даты аудита. Машинный принципал не зависит от персональной учётной записи и отдельного секрета.
- `ChangeSource`: `id`, `integration_id`, `owner_team_id`, `source`, `active`, стандартный `ordering_mode`. Уникальность `(owner_team_id, source)` закрепляет namespace за одним отправителем. Отзыв grant/токена не освобождает namespace другой интеграции; смена source/владельца требует нового namespace, а не переписывания истории. Изменение режима порядка действует только на новые Changes.
- `ChangeGrant`: `source_id`, `capability` (`reference`, `changed`, `reported_affected`), `target_team_id`, опциональный `target_service_id`, нормализованный `target_key` (`team:9` или `service:12`), `active`. Уникальность `(source_id, capability, target_key)` не зависит от особенностей NULL в разных БД. `reference` разрешает непроверенное утверждение и поиск идентичности в своём scope, но не доверенную публикацию; остальные capabilities также разрешают поиск своей цели. Grant на Service действует только пока тот принадлежит закреплённой Team. Grant на Team явно охватывает будущие Services этой Team и допускает pending-ссылки своей capability; grant только на Service — нет.
- `ApiToken` расширяется nullable `change_integration_id`. Токены интеграции имеют только `changes:ingest`, не получают персональные полномочия `user/group/team`, не создают токены и не обращаются к другим API. Переиспользуются генерация секрета, хранение хеша, срок действия и отзыв; второе хранилище секретов не вводится. Действующее поведение персональных токенов сохраняется.

Активный зарегистрированный source разрешает интеграции присылать операции для этого владельца/source, но не заявлять любые изменения всех его сервисов. Доверенные утверждения задаются явными ChangeGrants, в том числе для сервисов owner Team. В v1 интеграциями, sources, grants и машинными токенами управляют только администраторы инсталляции; ingest-токен не выдаёт себе права. Каждое изменение аудируется. Изменения grants/активности source и влияющего на полномочия состояния Team/Service транзакционно увеличивают auth revision затронутых интеграций.

Ротация/отзыв токена запрещает **новые запросы** с этим секретом; принятая работа принадлежит интеграции и продолжается по её текущим grants. Отключение интеграции/source или отзыв нужного grant блокирует новое сопоставление/публикацию. Удаление/ротация секрета не удаляет неизменяемые события. Права чтения отделены от ingestion в §7.

### 4.11. Ревизия графа и входы проекций

Добавляется `ChangeGraphState` с одной монотонной строкой `revision` для v1. Создание/изменение/удаление Dependency и существенные изменения Service (владелец, environment, enabled/deleted) увеличивают её и ставят ограниченную invalidation/discovery-работу той же транзакцией. Глобальная ревизия выбрана как простое решение; ревизии отдельных компонент — возможная будущая оптимизация.

Поскольку stamp глобальный, каждая ревизия графа запускает постраничный обход **всех Changes в автоматическом горизонте и всех running Changes**, а не только предположительно затронутых: иначе несвязанные строки навсегда останутся устаревшими. Обход объединяется в одно discovery-задание по ID состояния графа с requested generation и durable cursor. Фиксируется верхняя граница Change ID, обход идёт по ID; каждый ограниченный batch атомарно ставит задания Changes и сдвигает cursor с проверкой lease/generation. Новая ревизия перезапускает генерацию/cursor; приём нового Change имеет собственное задание. Обход прав охватывает все ещё публикуемые Changes затронутой интеграции. Повторы отдельных ссылок остаются индексируемыми по namespace/slug.

Полный набор входов вычисления: `(Change.revision, ChangeGraphState.revision, ChangeIntegration.auth_revision, engine_version)` и requested generation задания. Сопоставление/верификация увеличивает Change.revision; новые эпизоды имеют собственный durable discovery-триггер. Новый запрос, пришедший во время вычисления, не теряется при подтверждении прежней генерации. Ручной review использует собственную row_version и неизменяемый snapshot evidence; автопересчёт эти поля не записывает.

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
- Для `changed` нужен grant changed; для каждой ссылки `reported_affected` требуется хотя бы право reference в её области. До подтверждения через граф или явный grant reported-affected утверждение остаётся непроверенным (§7.2). Само принятие pending-ссылки **не** предоставляет полномочий на сервис.
- При успешном сопоставлении сохраняем `service_id`; используем его в `ChangeService`, `ChangeImpact` и корреляции. Полученную slug-ссылку сохраняем в `ChangeServiceReference`.
- Удаление, перенос или переименование Service не перепривязывает исторически разрешённый Change к новому Service с тем же slug. Повторное использование slug должно контролироваться CMDB; при переименовании отправитель исправляет будущие ссылки; автоматический alias mapping не входит в v1 и не меняет историю молча.
- `event_id` повторно используется **только** с тем же нормализованным содержимым запроса. Изменение представления с ID на slug под тем же `event_id` может дать `409`, даже если обе ссылки ведут на один Service. Для новой информации нужен новый `event_id`.

Ответ `201` включает безопасные счётчики ссылок и `correlation_status=queued` при включённом engine, иначе `not_enabled`. Счётчики охватывают только доступные интеграции категории; непроверенные чужие утверждения не раскрывают существование сервисов. `200` возвращается при точном повторе; `400/422` — некорректная схема/неразрешимая идентичность, `401` — нет авторизации, `403` — запрещённая область, `409` — конфликт внешнего ID, `429` — rate limit.

### 5.4. Read/review API

```text
GET    /api/changes
GET    /api/changes/{id}
GET    /api/changes/{id}/events
GET    /api/changes/{id}/services
GET    /api/changes/{id}/correlations
POST   /api/changes/{id}/correlations
POST   /api/changes/{id}/correlations/{correlation_id}/review
GET    /api/services/{service_id}/changes
GET    /api/alert-groups/{alert_group_id}/related-changes
GET    /api/incidents/{incident_id}/changes
POST   /api/incidents/{incident_id}/changes
PATCH  /api/incidents/{incident_id}/changes/{link_id}
DELETE /api/incidents/{incident_id}/changes/{link_id}
```

Чтение Changes поддерживает фильтр `service_id` **либо** `service_slug` с Team namespace, используя тот же resolver. Для каждого endpoint проверяются RBAC и явные scopes §7, SQL-фильтр применяется **до** пагинации. Ручное создание корреляции передаёт episode_id и relation_type; review/смена роли/удаление используют row_version. Выбор Change для вложенной связи возвращает только разрешённую полную или безопасную проекцию, без чужих исходных данных.

## 6. Интеграция с CMDB и позднее разрешение Service

CMDB независимо создаёт Team, Service и ServiceDependency через действующие API каталога; Change Intelligence ничего из этого не создаёт. Новый продуктовый CMDB-протокол не требуется. Source/grant должен разрешать namespace ещё до принятия ссылки.

### 6.1. Service уже существует

Разрешаются owner Team и зарегистрированный source, закрепляется target namespace_team_id, затем Service ищется по ID или `(namespace_team_id, service_slug)`. Сохраняются канонический ID и исходная ссылка. Grant changed разрешает прямое утверждение; reported с reference-only остаётся непроверенным до явного grant или проверенного пути зависимостей. ID и slug подчиняются одним полномочиям.

### 6.2. ChangeEvent пришёл раньше Service

1. Владелец/source и target namespace известны и разрешены, Service slug отсутствует. Событие/ссылка сохраняются с `resolution_status=pending_resolution`, закреплённым namespace_team_id, first_event_id и сроком ожидания; владелец видит pending в Inbox.
2. Каноническая связь с Service, корреляция и чужая публикация пока не создаются. Поиск идентичности никогда не создаёт ресурс.
3. Создание/изменение каталога ставит индексируемую работу разрешения своей транзакцией; периодический обход готовых pending-ссылок — ограниченный fallback. Полного сканирования истории Change нет.
4. Поиск только по `(namespace_team_id, requested_service_slug)` с текущими интеграцией/source, grants и состоянием ресурсов. Переименование Team безопасно; повторно искать Team по исходному slug запрещено. Сопоставление/evidence, увеличение Change.revision и downstream-задания записываются атомарно.
5. Ротация/отзыв токена сами по себе не останавливают принятое. Нет текущих grants — `denied`, namespace недействителен/удалён — `invalid`, срок истёк — `expired`. Перехода к новой Team/Service со старым slug нет. Доступны диагностика владельцу и аудируемый разрешённый повтор.
6. После позднего сопоставления ограниченный discovery учитывает и подходящие существующие эпизоды. Более старая история за автоматическим горизонтом доступна для ручных связей. До фазы 2 статус корреляции — `not_enabled`, а не бесконечный `queued`.

TTL pending, число попыток и размер batch — параметры конфигурации, документируемые до поставки фазы 1. Явный повтор не меняет присланную ссылку; исправленный Service slug присылается новым событием/ссылкой. Отозванное основание, expiry и dead jobs остаются видимыми в диагностике.

### 6.3. Изменения каталога/grants и историческое evidence

Изменение графа увеличивает ChangeGraphState.revision, изменение полномочий — auth_revision интеграции. Владелец/environment/active/deleted Service участвуют в нужных ревизиях той же транзакцией. Change — восстанавливаемая проекция событий: правка каталога не переписывает принятые события и не переназначает их канонические Service ID. Она инвалидирует соответствующие производные mapping/trust/impact и надёжно запрашивает ограниченный пересчёт.

Сохраняются snapshot пути и ревизия расчёта. Текущий граф может предложить связь со старым событием, но не доказывает существование этой топологии в прошлом; ограничение показывается в evidence. Ручной review сохраняет исходный snapshot даже при исчезновении текущего вычисленного основания. Автоматического переноса на alias или новый Service нет. External_service_ref/Service.uid как входной контракт — отдельная будущая работа.

## 7. Authentication, токены и RBAC

### 7.1. Машинный приём и администрирование

`POST /api/change-events` требует активный привязанный к интеграции `ApiToken` со scope `changes:ingest`, даже при выключенной глобальной обязательности API auth. JWT, персонального токена или wildcard без идентичности ChangeIntegration недостаточно. После аутентификации разрешается owner Team и проверяется принадлежность активного `(owner_team_id, source)` этой интеграции, затем grants. Payload не выбирает другого принципала.

Машинные токены выдаются/ротируются в новом admin-only UI/API Change Integrations с действующим механизмом секретов ApiToken. `Profile → API Tokens` остаётся для персональных токенов чтения/review и не выдаёт идентичность интеграции. Предлагаемые административные маршруты под `/api/admin/change-integrations` управляют sources, grants и токенами, требуют JWT аутентифицированного администратора и аудируют каждую запись. В v1 ни ingest-токен, ни персональный API-токен не администрируют этот namespace.

Scopes: `changes:ingest` для машинного POST; `changes:read` для чтения; `changes:write` для ручного review/связей. Нет неявного `changes:ingest` через `resources:write` или персональный `*`. Токены интеграции принимаются только endpoint приёма. JWT человека использует текущий RBAC; персональный API-токен дополнительно проверяет scopes и существующее ограничение Group. Вложенные read endpoints Service/AlertGroup/Incident требуют одновременно `changes:read` и read scope родительского ресурса; review/запись связи — `changes:write` и write scope целевого ресурса. В `api_token_scopes.py` нужны явные правила method/path, без случайной выдачи целого домена через общий prefix.

### 7.2. Право ссылки и доверие

1. Владение source разрешает только приём операции. Каждый changed Service требует grant `changed`; grant на Team разрешает pending slug, grant на Service — только конкретный существующий Service.
2. Reported affected требует как минимум `reference` для namespace/Service. Это разрешение непроверенного утверждения, а не межкомандной публикации. Доверие даёт grant `reported_affected` либо проверенный серверный путь зависимостей от авторизованного changed Service. Основание и input stamp сохраняются. Потеря пути/grant отменяет вычисленное доверие, не переписывая полученное событие.
3. Разрешённый namespace проверяется до раскрытия существования Service. Внутренний lookup числового ID для определения владельца допустим, но за разрешённым scope существующие, отсутствующие и soft-deleted ID/slug получают одинаковый безопасный отказ. В явно разрешённом namespace неизвестный Team/ID — ошибка валидации, неизвестный Service slug может стать pending. Так ожидание CMDB не превращается в проверку существования чужих ресурсов.
4. Разные формы канонической ссылки объединяются детерминированно: доверие есть, пока хотя бы одна текущая авторизованная ссылка или проверенный путь поддерживает эту роль. Непроверенный дубль не понижает доверенное утверждение, отозванное основание не сохраняет доверие. Исходные ссылки и основания сохраняются все.
5. Grant разрешает утверждение, а не чтение исходного Change или чужого Incident. Права человека проверяются отдельно при запросе, включая счётчики, пагинацию, поиск, Explain и безопасные списки выбора связей.

### 7.3. Безопасная межкомандная проекция и Service Timeline

Читатель owner Team видит поля операции, но детали чужих Service/участков пути всё равно требуют прав на эти ресурсы. Читатель только затронутого Service получает проекцию по белому списку: непрозрачный UUID Change, доступный ему Service, время события, безопасные kind и роль связи. Заголовок константный, например «Связанное изменение»; без присланных title/description, имени source, внешних ID, actor, URL, raw details и закрытых участков пути. Нельзя сначала сериализовать полный объект и затем удалять несколько известных ключей.

Service Timeline следует той же политике. Действующий `serialize_service_event()` возвращает actor, URL и payload без проверки владельца Change. Поэтому новые ServiceEvent изменения содержат **только безопасную проекцию даже у owner Services**; полные данные читаются отдельным авторизованным endpoint Change. Используются постоянный `source=change_intelligence`, безопасные title/summary, пустые actor/URL и payload по белому списку. Добавляются nullable индексируемый `change_event_id` для происхождения и `change_relation_type`; поведение прежних событий других типов не меняется. Одного URL в source_ref или копии raw JSON недостаточно.

До пагинации/подсчёта SQL timeline/related changes проверяет текущий доступ к Service и видимость соответствующей канонической связи/влияния Change. После изменения grants, графа или владельца Service устаревшая производная видимость скрывается до перепроверки; задержавшийся worker не продлевает старую авторизацию. История владельца и evidence ручного review сохраняются без раскрытия через чужую проекцию. При отсутствии доступа к полным данным ручной review использует тот же безопасный evidence; связывание с Incident не выдаёт участникам права владельца Change.

### 7.4. Отзыв и принятая работа

Отзыв/истечение секрета немедленно запрещает новые запросы, включая повторы; ротация не меняет source и владельца события. Уже принятая работа перепроверяет актуальные интеграцию/source/grants, **а не существование прежнего токена**. Отключение интеграции/source или отзыв grant увеличивает auth_revision и блокирует зависимое сопоставление/новую публикацию. Задания и события остаются в аудите; после разрешённого включения явная reconciliation может их продолжить. Старый секрет в заданиях не хранится.

## 8. Lifecycle и события не по порядку

### 8.1. Контракт порядка source

Source явно выбирает один режим; он копируется в новый Change. Изменение настройки source влияет только на будущие Changes. Существующие операции и события не переключают порядок задним числом.

| Режим | Обязательный вход и порядок | Отклонение |
|---|---|---|
| `timestamp` (стандартный для простых отправителей) | `occurred_at` с часовым поясом, нормализованный в UTC; время события, не приёма | Любой `source_sequence` даёт `422` |
| `sequence` | неотрицательный целочисленный `source_sequence` в каждом событии, уникальный внутри Change; пропуски и поздний приход меньших номеров допустимы | Нет/неверный sequence — `422`; другое событие с тем же sequence — `409` |

`occurred_at` обязателен в обоих режимах и задаёт время для корреляции, даже если lifecycle упорядочен sequence. `received_at` — только аудит, никогда tie-breaker. Время без пояса и превышение допустимого ухода часов в будущее (по умолчанию пять минут) отклоняются с `422`; серверное время молча не подставляется. Старые события остаются историей; глубина автоматической исторической корреляции ограничена отдельно (§9). Противоречие sequence и времени диагностируется без выдумывания другого occurred_at.

### 8.2. Детерминированная проекция статуса

Финальные типы: `succeeded`, `failed`, `rolled_back`, `cancelled`. Обрабатывается всё принятое множество, а не порядок доставки. Ключ порядка — sequence в соответствующем режиме или occurred_at в timestamp. Итог задаёт **наибольший ключ финальных событий**; started/updated не отменяют финальный исход.

| Принятые события lifecycle | Итоговый статус |
|---|---|
| Нет started и финальных событий, только updates | `unknown`, без lifecycle conflict |
| Есть started, финальных событий нет | `running` |
| Один исход у событий с наибольшим финальным ключом | Этот исход, независимо от поздней доставки started/updated |
| Разные финальные исходы с одним наибольшим occurred_at без sequence | `unknown`, `lifecycle_conflict=true`; сохраняются все ID конфликтующих событий |
| После конфликта финальное событие с большим ключом | Его исход; текущий конфликт снимается, прежняя диагностика сохраняется |

В timestamp одинаковые финальные исходы с одним временем не конфликтуют. Event ID может упорядочить отображение и метаданные с равным временем, но не выбирает между успехом и ошибкой. Финальный исход с большим ключом заменяет прежний иной исход (включая failed → succeeded и succeeded → rolled_back); история сохраняется. Для нового исполнения всё равно нужен новый change_id, а не started, стирающий прежний итог.

Примеры используют **время события у отправителя**:

| События в любом порядке доставки | Результат |
|---|---|
| failed в 10:05; succeeded в 10:10 | succeeded, даже если failed принят последним |
| succeeded в 10:10; started в 10:00 принят последним | succeeded |
| succeeded и failed ровно в 10:10 | unknown + conflict |
| Этот конфликт; rolled_back в 10:20 | rolled_back |
| sequence 20 failed в 10:10; sequence 21 succeeded в 10:09 | succeeded по sequence; инверсия времени диагностируется, исходные времена сохраняются |

### 8.3. Остальные поля и атомарный приём

`kind` и нормализованный environment (включая исходное отсутствие) не меняются внутри операции (`409`). Title непустой; description/URL можно явно очистить через null. Для изменяемого поля берётся событие с наибольшим ключом, **в котором это поле передано**; при равном времени метаданные выбираются лексикографически по external_event_id. Отсутствие сохраняет прежнее значение; received_at и автоинкремент БД не выбирают победителя. `change.updated` меняет эти поля/ссылки, но не статус lifecycle; произвольного свойства status у него нет. Actor/details принадлежат событию, а не разрушающему объединению несвязанных словарей.

`started_at` — минимальный occurred_at started-событий; без started это NULL. `completed_at` — occurred_at победившего финального события либо NULL при отсутствии итога/конфликте. first/last_occurred_at — min/max всех принятых событий. Отрицательная/противоречивая длительность диагностируется и не отображается как корректная. Для корреляции интервал воздействия начинается с started_at, если он известен, иначе с времени самого раннего финального события; updated-only операции и неразрешённый конфликт итогов не дают автоматических предложений причины. Обновление метаданных не является новым воздействием.

Ссылки на сервисы накапливаются; отсутствующий/пустой список не удаляет прежние связи. Pending/denied не переписывают статус операции. В одной write-транзакции сериализуются source/Change, вставляется неизменяемое событие, обновляются ссылки и детерминированная проекция, увеличивается revision и запрашивается outbox-работа. Ошибка любого шага откатывает всё. Уникальность PostgreSQL защищает конкурентную первую вставку; SQLite резервирует запись до чтения. Повтор после rollback даёт одно событие и одну фактическую генерацию.

## 9. Change Intelligence / Correlation

1. Вход — канонические авторизованные changed Services и доверенные reported affected. Неразрешённые, запрещённые, непроверенные и просроченные утверждения не запускают корреляцию.
2. Обход активных неудалённых `ServiceDependency` идёт обратно (в БД consumer → provider, для влияния provider → consumers), с учётом `enabled`, `correlation_enabled`, типа зависимости, environment и evidence задержки распространения. Ограничиваются глубина (по умолчанию 5), узлы, кандидаты и время; циклы и выбор пути обрабатываются детерминированно. Прямое совпадение и несколько путей не создают дубли связей. Разные известные environment исключают автокандидата; отсутствие environment означает неизвестность, а не совпадение.
3. Сохраняются snapshot пути и полный input stamp. Пересчёт по сегодняшнему графу не объявляет его историческим: показываются время/ревизия вычисления, evidence ручного review хранится отдельно. Ingestion не вызывает записывающие статусы эффекты действующего операционного Service Impact engine.
4. Автоматика использует только известное начало эпизода. Для интервала воздействия операции `[start, end]` подходят эпизоды с началом в `[start, end + W]`, W по умолчанию два часа. start определён в §8.3; end — время победившего финального события или момент расчёта для running. Противоречивый интервал исключается с диагностикой. Running проверяется при новых эпизодах, а не только ChangeEvents; AlertGroup.first_seen_at не подменяет начало повторного эпизода. Ретроспективный discovery завершённых операций/старых начал эпизодов ограничен горизонтом (по умолчанию семь дней); всё ещё running-операция не исключается только из-за давнего начала. Более старая история доступна для ручных связей.
5. Автоматика предлагает только `potential_cause`. Change с началом воздействия после начала эпизода не объявляется его автоматической причиной. **Mitigation в v1 только вручную**: оператор связывает позднее изменение с конкретным эпизодом или напрямую с Incident, в том числе без автоматического кандидата. Ручная связь за автоматическим окном допустима с аудируемым пояснением; вымышленного score для mitigation нет.
6. Score — версионированная детерминированная релевантность, не вероятность. Отбор/равенство кандидатов, веса, неизвестные данные и пределы входят в engine_version и требуют фиксированных примеров до приёмки фазы 2. Порядок SQL/обхода графа не меняет рейтинг. Ручная роль/review не перезаписывается, закрытые участки пути не попадают в Explain.
7. Новые ChangeEvents, создание/закрытие эпизода, сопоставление и изменения каталога/grants ставят durable ограниченную discovery/recompute-работу. Повторы и перезапуски workers не теряют триггер и не дублируют проекции (§4.8).

Из корреляции не следуют автоматические rollback, paging/escalation, создание/смена статуса Incident или технического статуса. Ручной confirmed_cause фиксирует суждение оператора, а не объявляет совпадение времени доказательством причины.

## 10. UI

**Operations → Changes** — самостоятельный Inbox, одна строка на Change.

- Поиск по ID, названию, source, внешнему ID, доступным сервисам и их `service_slug`.
- Фильтры: Team (owner **или** доступная затронутая), Service (ID или slug с Team namespace), `kind`, status, source, environment, даты, корреляция, `unmapped/pending`.
- Одна строка на Change при нескольких затронутых Teams; RBAC-фильтрация и `DISTINCT` выполняются сервером до пагинации и подсчёта.
- Change Details: история с occurred_at и received_at, режим порядка, явный конфликт итогов, **Changed**, **Reported affected**, **Inferred impact**, mapping/expiry/job state и разрешённое evidence. Чужой читатель получает только безопасную проекцию, а не страницу исходных данных владельца.
- Для `pending_resolution` — исходный slug/Team namespace, причина ожидания и момент последней попытки (в доступном владельцу scope); **без** кнопки «создать Service» автоматически.
- AlertGroup Details выбирает текущий или исторический эпизод и показывает только его Related Changes/review. Неизвестные границы и ручная mitigation явные. Incident Details поддерживает context/potential_cause/confirmed_cause/mitigation без обязательной AlertGroup.
- Service Timeline использует ServiceEvent после разрешения ссылки: стабильная дедупликация, индексируемое происхождение, безопасно сохранённая проекция и SQL-видимость §7.3. Полные данные читаются отдельным авторизованным endpoint Change; inferred impact не объявляется прямым изменением.
- Redacted view для чужих Teams: собственный сервис, безопасные тип/время/тип связи, без закрытой топологии, полного payload, actor и URL.

## 11. Технические требования и эксплуатация

- Pydantic v2: строгие альтернативные ID/slug, время с поясом, целочисленный sequence, пределы строк/ссылок/body/details. Размер body ограничивается до разбора; задаются тайм-ауты запросов и rate limits каждой интеграции. Глобального поиска Service slug нет.
- Auth применяется независимо от глобальной настройки обязательности. Source/grants повторно проверяются под блокировкой auth revision транзакции приёма; проверки только до конкурентного отзыва недостаточно.
- Ограничения БД и короткие write-транзакции PostgreSQL/SQLite; явный rollback и ограниченные повторы временных ошибок. Сетевых вызовов/обхода графа под lifecycle/Change locks нет. Порядок блокировок — §4.8, несколько интеграций блокируются по ID.
- Durable worker поставляется в фазе 1 на существующих scheduler и БД; Redis/Celery не обязателен, очереди только в памяти Flask недостаточно. Claim, heartbeat lease, expiry, retry/dead и commit проекции проверяют lease_token/generation. Общий scheduler lock дополнителен и не доказывает исключительное владение после истечения срока.
- Индексы Change(owner_team_id,last_occurred_at), уникальные source/external IDs, ChangeService(service_id,change_id), ChangeServiceReference(resolution_status,namespace_team_id,requested_service_slug), ChangeImpact(service_id,active), correlation(episode_id,review_status), ChangeJob(state,next_attempt_at), происхождение timeline и episode(group,ordinal). До discovery проверяются планы запросов на ограниченном репрезентативном наборе.
- Текущие RBAC/валидность проекции применяются в SQL до счётчиков, поиска и пагинации. Полные owner payload/actor/URL не попадают в межкомандный timeline или клиентский кеш, доступный после смены прав.
- Время отправителя и приёма различаются; UI показывает UTC offsets и явные conflict/unknown-boundary/stale/mapping состояния. Неизвестные длительность/причина не угадываются молча.
- В Prometheus labels нет высококардинальных ID/slug/произвольного source. Измеряются accepted/duplicate/rejected ingestion, pending/denied/expired, возраст очереди, claim/reclaim, отброшенная устаревшая работа, длительность/классы ошибок корреляции и lifecycle conflicts.
- Секреты удаляются до сохранения диагностических данных и логирования; URL-схемы ограничены, контент экранируется. Документируются payload limits, future skew, pending TTL, retry budget, discovery horizon, retention и срок идемпотентных повторов. Ручное/Incident evidence защищено от очистки (§4.9).
- Старые ServiceEvents без достоверного внешнего Change ID сохраняются как есть; Change/эпизоды не синтезируются догадкой. Документируются аддитивная миграция, порядок writer/worker rollout и операционный rollback без удаления evidence.
- UI EN/RU/DE/FR/ES/ZH, OpenAPI, все сценарии §13 и поддерживаемый Python CI. Изменение архитектуры не означает готовность реализации или пройденные выпускные проверки.

## 12. Порядок реализации

Реализация разбита на **10 последовательных этапов**. Каждый этап заканчивается проверяемым набором изменений и своими тестами; следующий начинается после выполнения критериев готовности предыдущего. Хранение этапа 1 реализовано; этапы 2–10 запланированы. Ограничения развёртывания и проверки описаны в [руководстве первого этапа](change-intelligence-stage-1.md). Сценарии §13 распределяются по этапам, а не откладываются целиком на выпуск.

| Контрольная точка | Этапы | Результат |
|---|---|---|
| Фаза 1 — Реестр и надёжная основа | 1–6 | Приём, история, рабочий обработчик pending-ссылок и Changes Inbox в тестовом развёртывании; `correlation_status=not_enabled` |
| Фаза 2 — Объяснимая корреляция | 7–8 | Предложения причин, защищённые ручные решения и API связей с эпизодами/Incident |
| Фаза 3 — UI-интеграции и выпуск | 9–10 | Service Timeline, страницы AlertGroup/Incident и проверенное развёртывание |

Этап разработки не означает отдельный production-релиз. Публичный приём Change Events включается только после проверки на этапе 10 полного пути: приём → авторизация и разрешение Service → worker → корреляция с конкретным эпизодом AlertGroup → отображение связи с учётом прав. Этап 6 — внутренняя контрольная точка, а не самостоятельный выпуск реестра. Этап 1 создаёт схему без записи эпизодов и восстановления прошлых циклов; на этапе 2 все lifecycle writers согласованно переходят к записи эпизодов. Схема, writers, worker и политика чтения развёртываются до включения приёма. Новые API, настройки и UI документируются и локализуются по мере появления; этап 10 проверяет их полноту.

### 12.1. Этап 1 — Модели, ограничения и миграции

- **Работа:** модели Change, ChangeEvent, ChangeServiceReference, ChangeService, ChangeIntegration, ChangeSource, ChangeGrant, ChangeJob, ChangeGraphState и AlertGroupEpisode; поля ApiToken/AlertGroup; уникальность, FK и индексы. Добавить запись запроса задания в транзакции вызывающего кода. Создать только схему и начальную ревизию графа, без реконструкции эпизодов и постановки заданий для старых алертов. Модели корреляции, ручных связей и поля timeline добавляются на этапах 7–9 вместе с их использованием.
- **Тесты:** чистая БД и обновление существующей; повтор миграции; старые алерты/события/токены не меняются, эпизоды/Changes/задания не создаются; ошибка откатывает схему и инициализацию; один открытый эпизод; ограничения уникальности и FK в PostgreSQL/SQLite. Запрос задания откатывается вместе с транзакцией.
- **Готово, когда:** схема создаётся и обновляется без изменения существующих данных и включения записи эпизодов или приёма; определён порядок обновления процессов и восстановления после неудачной миграции.

### 12.2. Этап 2 — Эпизоды во всех путях AlertGroup

- **Работа:** атомарное создание/закрытие эпизода при intake, настоящем reopen, resolve, recovery, callbacks, heartbeat, orchestration, merge и удалении ресурса. При переходе writers инициализировать один текущий эпизод с неизвестным началом для уже активных групп, без восстановления закрытых циклов. В той же транзакции сохранять discovery-задание; обработка появится на этапе 5. Сохранить порядок блокировок Incident → AlertGroup → episode и действующие уведомления.
- **Тесты:** идемпотентная инициализация существующих активных групп без догадок о начале; закрытые группы не получают исторических эпизодов; два reopen; resolve одновременно с reopen; повторный resolve; ошибки записи ребёнка, события и задания. Ack → firing, unshelve и reopen только Incident не создают новый эпизод.
- **Готово, когда:** все записывающие пути соблюдают один контракт, незавершённая транзакция не оставляет частичного эпизода, прежние lifecycle-тесты проходят на обеих БД.

### 12.3. Этап 3 — Интеграции, grants и токены

- **Работа:** административные API/UI интеграций, sources, grants и ротации; машинный ApiToken и явные scopes/разрешённый маршрут; журнал изменений и auth_revision. Реализовать проверку владельца/source и области Service, включая reference-only grants. Персональные токены сохраняют действующее поведение.
- **Тесты:** подмена source/Team; выход за grant; одинаковый безопасный отказ для недоступных ID; запрет чтения и администрирования ingest-токеном; ротация, отзыв и конкурентное изменение прав. Персональный wildcard не заменяет идентичность интеграции.
- **Готово, когда:** администратор может создать интеграцию и заменить секрет, не меняя владельца её событий; изменения прав атомарно обновляют ревизию. Продолжение уже принятой работы проверяется с worker на этапе 5.

### 12.4. Этап 4 — Атомарный приём и проекция Change

- **Работа:** валидация общего payload, resolver ID/slug с закреплённым namespace_team_id, digest и идемпотентность; режимы timestamp/sequence и детерминированная проекция. Event, ссылки, состояние Change, revision и запрос задания записываются одной транзакцией с повторной проверкой прав. Endpoint остаётся выключенным в production до сквозной приёмки этапа 10.
- **Тесты:** перестановки событий, одинаковое время разных итогов и более поздний итог; поздний started; пропуски/дубли sequence; absent/null; ротация и повтор event_id; конкурентные первые запросы; ошибка на каждом шаге записи.
- **Готово, когда:** повтор возвращает `200` без новых эффектов, конфликт — `409`; после rollback повтор сохраняется один раз; порядок доставки не меняет результат принятого множества событий.

### 12.5. Этап 5 — Worker, pending-ссылки и пересчёт

- **Работа:** claim/lease/generation, проверка актуальности входов при записи, retry/backoff, expiry, dead state и аудируемый повтор. Подключить catalog/auth revisions, discovery эпизодов, сохранение прогресса обхода и периодическую сверку pending-ссылок. Выполнять доступные обработчики; до этапа 7 не ставить бесконечно ожидающие задания выключенной корреляции. Зафиксировать TTL, лимиты, сроки повторов и метрики очереди.
- **Тесты:** потеря lease и поздняя запись старого worker; новый триггер во время расчёта; сбой/рестарт между записью результата и подтверждением; поздняя CMDB, переименование Team и повторное использование slug; принятая работа после отзыва токена; отзыв grant во время вычисления; возобновление обхода после сбоя.
- **Готово, когда:** задания переживают рестарт, не теряют новые запросы и не создают дубли; pending разрешается только в исходной Team по текущим правам; ошибки доступны в диагностике.

### 12.6. Этап 6 — Read API и минимальный Changes Inbox

- **Работа:** список, детали, события и сервисы; поиск, фильтры, счётчики и пагинация с SQL RBAC; полная проекция владельца и безопасная проекция для доступного затронутого Service. UI показывает конфликт итогов, mapping, pending/expired/dead и состояние обработки. Документировать общий API и пример отправителя.
- **Тесты:** один Change с несколькими Team не дублируется; владелец, затронутая команда и посторонний видят только разрешённые поля; фильтры/поиск/счётчики не раскрывают скрытые данные; end-to-end приём → pending → создание Service → отображение.
- **Готово, когда:** фаза 1 работает в тестовом развёртывании с worker, пределы конфигурации документированы, корреляция явно `not_enabled`. Production-приём остаётся выключенным до готовности связей с эпизодами и итоговой приёмки.

### 12.7. Этап 7 — Автоматическая корреляция

- **Работа:** миграции ChangeImpact и ChangeAlertGroupCorrelation; ограниченный обратный обход графа и привязка к точному эпизоду. До реализации score зафиксировать версию правил и эталонные примеры ранжирования. Подключить все триггеры пересчёта, включая полный обход допустимой истории при смене общей graph revision; публиковать только при актуальном input_stamp. Автоматика предлагает только potential_cause.
- **Тесты:** прямые/косвенные связи, циклы, ромбы, выключенные рёбра, environment, границы окна, длительный running, неизвестное начало эпизода; Change до/после AlertGroup; смена графа/grant во время расчёта; повторные задания и стабильность рейтинга.
- **Готово, когда:** одинаковые входы дают одинаковый результат и объяснение, устаревший расчёт не публикуется, автоматической mitigation и изменений операционных статусов/уведомлений нет.

### 12.8. Этап 8 — Ручной review и связи Incident

- **Работа:** ручное создание связи с эпизодом, confirm/reject, context/mitigation; row_version, аудит и сохранённое evidence. Добавить ChangeIncidentLink и API add/change/remove/reactivate через транзакции/CAS Incident. Защитить связанные доказательства от retention одновременно с появлением связей. UI действий в Change Details использует разрешённую полную или безопасную проекцию.
- **Тесты:** конкурентные confirm/reject и изменение/удаление связи; отсутствие автоматического предложения; mitigation вне автоматического окна; повторное добавление и реактивация; ошибка записи link/event/audit; пересчёт после ручного решения; новый эпизод; очистка родительских объектов.
- **Готово, когда:** устаревшая запись получает `409`, повтор соблюдает контракт `200/201`, ручное решение и его основания переживают пересчёт/очистку и не переносятся на другой эпизод. Связь не раскрывает закрытые данные Change.

### 12.9. Этап 9 — Service Timeline и страницы AlertGroup/Incident

- **Работа:** поля происхождения ServiceEvent и безопасная сохранённая проекция; идемпотентная публикация timeline с SQL-проверкой видимости. Добавить выбор эпизода и Related Changes в AlertGroup, отображение/действия со связями в Incident. Подключить API предыдущих этапов, не менять статус сервисов и уведомления.
- **Тесты:** повтор и crash/retry публикации не дублируют timeline; один Change через все экраны не раскрывает лишних полей; отзыв доступа, перенос Service, устаревший input_stamp и навигация браузера; прежние ServiceEvents отображаются как раньше.
- **Готово, когда:** owner и затронутая команда получают согласованные представления на всех страницах; приватные title/source/actor/URL/payload не попадают в чужой timeline или кеш.

### 12.10. Этап 10 — Выпускные проверки

- **Работа:** сверить OpenAPI, примеры CI/CD и CMDB, шесть локализаций, настройки/лимиты, метрики, инструкции миграции, запуска worker и отката. Описать порядок включения функций и отключение обработки без удаления истории. Проверить планы основных SQL-запросов и ограниченность обходов на репрезентативных данных.
- **Тесты:** весь набор §13 на PostgreSQL/SQLite, поддерживаемая матрица Python CI, upgrade с существующими данными, повтор/сбой миграции, перезапуск worker, сквозные роли и регрессии AlertGroup/Incident/уведомлений. До включения публичного приёма проверить путь от события до отображения разрешённой связи с эпизодом, включая повторы и оба порядка прихода Change/Alert. Неотработавшие проверки явно отмечаются как блокеры.
- **Готово, когда:** результаты обязательных проверок записаны, блокеров нет, развёртывание и восстановление воспроизводимы. Завершение RFC или одного этапа само по себе не означает готовность всего Change Intelligence к релизу.

## 13. Критерии приёмки и обязательные тесты

Все применимые сценарии записи/конкурентности выполняются на PostgreSQL и SQLite. Гонки используют реальные независимые соединения, barriers/events вместо ожиданий только по времени. Проверяются сохранённые данные, результат, число событий/аудитов и задания, а не один HTTP status.

| Область | Обязательные регрессионные сценарии |
|---|---|
| Идентичность | Только slug и смешанные ID; одинаковые Service slug у разных Teams; конфликт namespace; неизвестный ID против pending slug; разные формы дают одну каноническую связь |
| Закреплённый namespace | Team переименована, старый slug получила другая: pending ищется только в исходном namespace_team_id; удаление/перенос namespace или Service не перепривязывает историю |
| Право ссылки | Неизвестный/существующий/удалённый чужой ID даёт одинаковый отказ без namespace grant; reference-only не публикует непроверенное утверждение; доверие по графу теряется при исчезновении основания |
| Идемпотентность | Тот же event/digest — 200 без роста revision/jobs; другой digest/change_id с тем же event ID — 409; конкурентные первые события дают одну операцию/событие/логическое задание; ротация сохраняет namespace/dedup |
| Порядок | Все перестановки принятых событий дают одинаковые статус и метаданные; occurred_at отправителя важнее received_at; пропуски sequence и поздние меньшие номера допустимы; отсутствующий/смешанный/дублирующий sequence отклоняется по контракту |
| Конфликт итогов | Одинаковое время succeeded/failed в timestamp сохраняет оба и даёт unknown + conflict; одинаковые исходы не конфликтуют; более поздний итог снимает текущий конфликт; поздний started/updated не открывает завершённый Change |
| Проекция полей | Отсутствие/null, offsets/микросекунды времени, порядок метаданных с равным временем, неизменяемые kind/environment, пустые списки сервисов, уход часов в будущее и противоречивая длительность |
| Атомарность приёма | Ошибки после вставки Change, события, объединения ссылок, проекции и outbox: частичных Change/event/job нет; повтор сохраняется один раз |
| Полномочия интеграции | Токен source A не подставляет source B/другого владельца; ingest не читает, не делает review, не управляет токенами и не редактирует Incident; персональный wildcard/JWT не обходит машинную идентичность |
| Отзыв | Принятый pending переживает ротацию/истечение/отзыв токена; новые запросы старым секретом запрещены; отключение integration/source или отзыв grant запрещает mapping/публикацию, в том числе уже считающему worker |
| Переход к эпизодам | Этап 1 сохраняет алерты/события и не создаёт эпизоды/Changes/задания; этап 2 инициализирует по одному текущему эпизоду с неизвестным началом для уже активных групп, без восстановления закрытых циклов; acknowledged → firing не принимается за resolved reopen; старые ServiceEvents не выдумываются как Changes |
| Атомарность эпизода | Два reopen дают один эпизод/ребёнка; ошибка ребёнка/event/job откатывает всё; manual resolve во время незавершённого reopen не закрывает новый эпизод; duplicate resolve закрывает один раз |
| Все lifecycle-пути | Recovery/ручные callbacks, heartbeat, orchestration, merge и удаление ресурса корректно открывают/закрывают эпизоды; ack/unshelve/reopen только Incident не создают эпизод |
| Защита job | Worker A потерял lease, B записал результат, A вернулся: A не публикует/подтверждает и не меняет retry B. Триггер во время вычисления не теряется. Сбой до/после публикации не теряет работу и не дублирует timeline |
| Ревизии входов | Во время вычисления меняются граф/grant/mapping: старый input stamp не публикуется; устаревшая межкомандная видимость скрывается до пагинации/счётчиков; ручной review сохраняется |
| Discovery/expiry | Change до AlertGroup и наоборот; поздняя CMDB; периодический fallback; пределы batch/depth/horizon; обход после смены графа охватывает и несвязанные Changes, переживает сбой batch и перезапускается на новой ревизии; истечение pending/dead job и аудируемый повтор |
| Корреляция | Прямой/зависимый Service, циклы/ромбы/несколько путей, выключенные/удалённые рёбра, correlation_enabled=false, разные/неизвестные environment, длительная running-операция, границы окна и неизвестное начало эпизода |
| Ручной review | Конкурентные confirm/reject дают одну принятую версию и 409 устаревшему; пересчёт сохраняет роль и evidence; новый эпизод не наследует прежнее решение |
| Ручная mitigation | Позднее изменение не получает автоматическую причинную связь, но связывается вручную с более ранним эпизодом/Incident с аудируемым пояснением; без выдуманной вероятности и paging |
| Связи Incident | Incident без AlertGroup; duplicate add/reactivation/remove/смена роли соблюдают 200/201/409; link/event/audit откатываются вместе; статус и уведомления Incident не меняются |
| Redaction | Один Change через inbox/details/search/counts/Explain/timeline/Incident links: затронутая команда не видит закрытые title/source/ID/actor/URL/payload/path; перенос Service, отзыв доступа и навигация браузерного кеша не раскрывают старые полные данные |
| Retention и rollout | Ручное/Incident evidence переживает очистку родителей; записи идемпотентности соблюдают срок повторов; машинная auth не ломает legacy API; upgrade/retry схемы, rollback-процедура и развёртывание worker документированы |

Пределы payload/retention/retry фиксируются в конфигурации и OpenAPI до приёмки фазы 1. Точные примеры score/рейтинга — до приёмки фазы 2. Неизвестные исторические границы и скрытые устаревшие проекции имеют явные состояния UI, а не молча теряются.

## 14. Соответствие IncidentRelay 2.5

Проверено по `release/2.5.0` на 2026-10-28 (`7cf123d` и локальное исправление resolve/reopen). Этап 1 добавляет хранение в рабочем дереве; остальное поведение и маршруты остаются будущей работой. Это не включает Change Intelligence и не объявляет его частью уже выпущенной базы 2.5.

Переиспользуются действующие контракты: глобально уникальный Team.slug; Service(team,slug) и Service.uid; ServiceDependency; ServiceEvent с dedup key; AlertGroupCorrelation для AlertGroup ↔ AlertGroup; отдельные операционные Incident/IncidentAlertGroupLink; ApiToken с хешем; центральные API scopes; scheduler/DB locks. Collaboration Incident в 2.5 имеет собственные состояние/версию и не связывается с техническим ingestion Change.

Необходимые изменения интеграции перечислены явно:

- Добавить сохранение эпизодов во все технические lifecycle-пути. Сейчас `reopen.py` сохраняет исторический AlertGroup.first_seen_at и повторно использует группу с новым ребёнком; постоянный ключ цикла нельзя получить из этого поля. Сохраняются порядок Incident → AlertGroup и no-op для resolved.
- Ручные связи и аудит используют транзакции/CAS Incident, сохраняя независимость lifecycle Incident и AlertGroup.
- Расширить ApiToken/middleware принципалом интеграции, разрешённым маршрутом и явными scopes. Одного ApiToken.team недостаточно для grants нескольких Teams/sources; Profile остаётся управлением персональными токенами.
- Добавить graph/auth revision и discovery hooks в транзакции каталога. Действующие scheduler locks из `db_lock.py` не заменяют fencing отдельного job и проверку публикации.
- Действующий сериализатор ServiceEvent раскрывает actor/URL/payload. Безопасно сохраняемая проекция Change, происхождение и SQL-видимость добавляются до публикации timeline; контракты прочих типов событий сохраняются.
- Обновить retention: прежние каскады AlertGroup/Service не удаляют защищённые новые доказательства. Порядок миграции, rollback и развёртывания не допускает смеси старых lifecycle writers с читателями, полагающимися на эпизоды.

Предлагаемые модули: `app/services/change_intelligence/` (identity, projection, grants, jobs, reconciliation, correlation), `app/modules/db/changes_repo.py`, Change schemas/views/OpenAPI, helpers хранения эпизодов и UI Changes/Admin, а также миграции, переводы и тесты. Это доменные модули существующего приложения; универсальная plugin/event-sourcing платформа не требуется.
