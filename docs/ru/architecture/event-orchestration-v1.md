# Event Orchestration v1

**Статус:** предложено  
**Цель:** первый релиз, готовый к промышленной эксплуатации  
**Проект:** IncidentRelay  
**Путь документа:** `docs/architecture/event-orchestration-v1.md`

## 1. Назначение

Event Orchestration v1 вводит единый версионируемый движок правил, который обрабатывает нормализованные события до их попадания в существующий жизненный цикл алертов IncidentRelay.

Цель — объединить маршрутизацию, мутацию событий, выбор сервиса, выбор приоритета, решения об эскалации, решения об уведомлениях, группировку, подавление, отложенную активацию и безопасную автоматизацию в один объяснимый конвейер выполнения.

Это не минимальный proof of concept. Первая версия должна быть достаточно безопасной для промышленного использования и структурированной так, чтобы функции AIOps с сохранением состояния можно было добавить позже без замены базовой модели.

## 2. Текущая проблема

В IncidentRelay уже есть множество строительных блоков оркестрации:

- нормализаторы интеграций;
- матчеры маршрутов;
- правила сопоставления сервисов;
- пресеты матчеров;
- политики приоритетов;
- политики уведомлений;
- политики эскалации;
- заглушки (silences);
- окна обслуживания;
- настраиваемая группировка и дедупликация;
- корреляция зависимостей;
- трассировки объяснений (Explain traces).

Эти механизмы настраиваются по отдельности и выполняются в основном в фиксированном порядке. Сейчас пользователь не может описать один целостный поток принятия решений, например:

> Если событие пришло из production, извлечь имя сервиса, направить его во владеющую команду, повысить серьёзность, выбрать критическую политику эскалации, сгруппировать по сервису и окружению, приостановить временные сбои на две минуты и запустить диагностический вебхук.

Event Orchestration v1 предоставляет этот единый поток.

## 3. Цели

Первый промышленный релиз должен обеспечивать:

1. Глобальную оркестрацию и оркестрацию в области сервиса.
2. Неизменяемые опубликованные версии и редактируемые черновики.
3. Вложенные деревья условий с семантикой AND, OR и NOT.
4. Упорядоченные правила с явным управлением потоком.
5. Извлечение переменных и безопасные шаблоны.
6. Мутацию событий.
7. Динамический выбор группы, команды, маршрута, сервиса, политики и приоритета.
8. Группировку и дедупликацию на основе правил.
9. Различающиеся исходы `continue`, `stop`, `suppress`, `drop` и `pause`.
10. Настоящую отложенную активацию для приостановленных событий.
11. Безопасные асинхронные действия-вебхуки.
12. Симуляцию, повтор (replay), теневой режим (shadow mode) и подробные трассировки выполнения.
13. Визуальный конструктор правил.
14. Совместимость с существующим жизненным циклом IncidentRelay и устаревшими (legacy) политиками.
15. Публичный API и документацию OpenAPI.

## 4. То, что не входит в v1

Следующее намеренно отложено:

- кеш-переменные, разделяемые между независимыми событиями;
- условия по частоте (rate), периодичности, числу уникальных значений (distinct-count), последовательности и отсутствию (absence);
- произвольная рекомбинация графа;
- группировка на основе машинного обучения;
- выполнение произвольного Python, shell, SSH или контейнеров;
- нативные действия AWX, Rundeck, Kubernetes Job или Terraform;
- двунаправленные рабочие процессы Jira или ServiceNow;
- автоматическое преобразование каждого продвинутого правила оркестрации PagerDuty;
- долговременное хранение отброшенных сырых полезных нагрузок (payloads);
- замена нормализаторов, специфичных для интеграций.

Эти функции могут быть введены после того, как модель оркестрации без состояния станет стабильной.

## 5. Архитектура обработки

Целевой конвейер обработки:

```text
Incoming payload
    ↓
Integration authentication
    ↓
Integration normalizer
    ↓
Global Orchestration
    ├── mutate normalized event
    ├── extract variables
    ├── choose group/team/route/service
    ├── set grouping and policies
    └── continue/suppress/drop/pause
    ↓
Service Orchestration
    ├── mutate event
    ├── set priority/severity
    ├── select escalation/notification policy
    ├── enqueue webhook actions
    └── continue/suppress/drop/pause
    ↓
Existing IncidentRelay lifecycle
    ↓
Alerts, incidents, escalation, notifications, correlation and impact
```

Движок оркестрации не должен заменять существующий жизненный цикл алертов. Он выдаёт финальное решение и мутированное нормализованное событие, которые потребляются существующим жизненным циклом.

## 6. Контекст выполнения

Движок работает с контекстом в стиле неизменяемости. Каждое действие возвращает обновлённый контекст, а не мутирует несвязанное глобальное состояние.

Предлагаемая модель результата:

```python
OrchestrationResult(
    normalized_event={},
    variables={},
    provenance={},
    group_id=None,
    team_id=None,
    route_id=None,
    service_id=None,
    priority_id=None,
    escalation_policy_id=None,
    notification_policy_id=None,
    group_by=None,
    dedup_key=None,
    disposition="continue",
    pause_seconds=None,
    suppress_reason=None,
    drop_reason=None,
    action_requests=[],
    trace=[],
)
```

Разрешённые исходы (dispositions):

```text
continue
stop
suppress
drop
pause
```

`stop` останавливает дальнейшую оценку оркестрации, но всё же отправляет текущий результат в обычный жизненный цикл.

## 7. Модель предметной области

### 7.1 EventOrchestration

```text
id
group_id
name
description
scope                  global | service
service_id             nullable for global scope
enabled
mode                   active | shadow | disabled
active_version_id
created_by
created_at
updated_at
deleted_at
```

Правила:

- глобальная оркестрация принадлежит одной группе IncidentRelay;
- сервисная оркестрация привязана к одному сервису;
- одновременно активна только одна опубликованная версия;
- теневой режим оценивает правила, но не применяет результат.

### 7.2 EventOrchestrationVersion

```text
id
orchestration_id
version_number
status                 draft | published | archived
definition_hash
comment
created_by
published_by
created_at
published_at
```

Правила:

- опубликованные версии неизменяемы;
- редактирование активной оркестрации создаёт или обновляет черновик;
- публикация атомарно заменяет активную версию;
- откат (rollback) переопубликовывает предыдущую версию как новую версию либо атомарно восстанавливает её в соответствии с решением по реализации;
- каждое выполнение сохраняет точный ID версии.

### 7.3 EventOrchestrationRule

Может использоваться нормализованное реляционное представление, но полная версия также должна экспортироваться в одно детерминированное JSON-определение.

Предлагаемые поля:

```text
id
version_id
parent_rule_id
position
name
description
enabled
condition_tree_json
actions_json
processing_mode
created_at
updated_at
```

Режимы обработки:

```text
continue
stop
evaluate_children
children_then_continue
```

### 7.4 OrchestrationIntakeToken

```text
id
orchestration_id
name
token_hash
enabled
last_used_at
created_by
created_at
revoked_at
```

Глобальные токены приёма не привязаны к одному существующему маршруту. Они авторизуют глобальную оркестрацию, которая затем выбирает целевой маршрут/команду/сервис.

### 7.5 PendingOrchestratedEvent

Используется настоящей семантикой паузы:

```text
id
group_id
orchestration_id
orchestration_version_id
route_id
service_id
dedup_key
normalized_event_json
context_json
activation_at
status                 pending | activated | resolved | cancelled | failed
created_at
updated_at
resolved_at
activated_at
```

### 7.6 OrchestrationExecution

```text
id
group_id
orchestration_id
version_id
source
integration_name
event_fingerprint
disposition
matched_rule_count
duration_ms
trace_json
alert_id
alert_group_id
created_at
expires_at
```

Трассировки отброшенных событий должны иметь настраиваемый короткий срок хранения и должны редактировать (скрывать) секреты.

### 7.7 OrchestrationWebhookAction

```text
id
group_id
name
description
url
method
headers_encrypted
body_template
timeout_seconds
retry_count
private_network_policy
enabled
created_by
created_at
updated_at
```

### 7.8 AutomationExecution

```text
id
action_id
orchestration_execution_id
alert_group_id
rule_id
status                 pending | running | succeeded | failed | cancelled
attempts
request_metadata_json
response_status
response_excerpt_safe
error_safe
created_at
started_at
finished_at
```

## 8. Язык условий

Условия должны поддерживать вложенные деревья.

Пример:

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
          "field": "severity",
          "operator": "in",
          "value": ["critical", "high"]
        },
        {
          "field": "labels.customer_tier",
          "operator": "equals",
          "value": "enterprise"
        }
      ]
    }
  ]
}
```

Обязательные логические узлы:

```text
all
any
none
```

Обязательные операторы:

```text
equals
not_equals
contains
not_contains
starts_with
ends_with
regex
not_regex
in
not_in
exists
not_exists
greater_than
less_than
greater_or_equal
less_or_equal
is_true
is_false
```

Поддерживаемые источники данных:

```text
event.*
labels.*
raw.*
variables.*
route.*
service.*
team.*
integration.*
time.*
result.*
```

Оценщик (evaluator) должен:

- иметь детерминированное приведение типов;
- никогда не выполнять произвольный код;
- ограничивать сложность регулярных выражений и размер входных данных;
- возвращать структурированные причины как для совпадений, так и для несовпадений;
- записывать результаты условий в трассировку Explain;
- по возможности проверять ссылки на поля до публикации.

## 9. Извлечение переменных

Обязательные действия извлечения:

```text
extract_regex
copy_field
json_path
split
set_variable
lowercase
uppercase
trim
```

Пример:

```json
{
  "type": "extract_regex",
  "source": "event.title",
  "pattern": "^\\[(?<environment>[^]]+)\\]\\[(?<service>[^]]+)\\]"
}
```

Результат:

```json
{
  "variables": {
    "environment": "prod",
    "service": "payments"
  }
}
```

Сбои извлечения должны поддерживать настраиваемое поведение:

```text
continue
stop_rule
stop_orchestration
```

## 10. Язык шаблонов

Шаблоны должны использовать ограниченный интерполятор, а не неограниченное вычисление Jinja или Python.

Примеры:

```text
{{ event.title }}
{{ labels.environment }}
{{ variables.service }}
{{ service.name }}
```

Обязательные фильтры:

```text
lower
upper
trim
default
replace
truncate
```

Шаблоны могут использоваться для:

- заголовка;
- сообщения;
- ключа дедупликации (dedup key);
- ключа группировки (group key);
- меток (labels);
- значений переменных;
- поиска сервиса;
- поиска маршрута;
- заголовков вебхука;
- тела вебхука;
- ссылок события.

Реализация должна применять ограничения на длину вывода и скрывать секреты в трассировках.

## 11. Действия

Действия реализуются через реестр (registry), так что каждое действие имеет изолированную логику валидации и выполнения.

```python
ACTION_HANDLERS = {
    "set_title": handle_set_title,
    "set_severity": handle_set_severity,
    "set_service": handle_set_service,
    "suppress": handle_suppress,
}
```

### 11.1 Мутация события

```text
set_title
set_message
set_status
set_severity
set_dedup_key
set_group_key
add_label
remove_label
rename_label
copy_field
add_event_link
```

### 11.2 Маршрутизация и владение

```text
set_group
set_team
set_route
set_service
```

Межгрупповая маршрутизация должна быть явно запрещена, если только будущая модель разрешений её не поддержит.

### 11.3 Политики

```text
set_priority
set_escalation_policy
set_notification_policy
```

Выбранные сущности должны принадлежать результирующему контексту группы/команды/сервиса.

### 11.4 Группировка и корреляция

```text
set_group_by
disable_grouping
set_correlation_window
```

Финальное решение о дедупликации/группировке применяется до того, как существующий репозиторий алертов сгруппирует событие.

### 11.5 Исход (disposition)

```text
continue
stop
suppress
drop
pause
```

### 11.6 Действия с контекстом

```text
extract_regex
set_variable
copy_to_variable
attach_runbook
add_stakeholder
```

### 11.7 Автоматизация

```text
enqueue_webhook
```

Выполнение вебхука должно быть асинхронным и не должно задерживать приём (ingestion).

## 12. Семантика suppress, drop и pause

### 12.1 Suppress

Suppress означает:

- алерт и группа алертов могут быть созданы;
- эскалация не запускается;
- уведомления не отправляются;
- причина и исходное правило сохраняются;
- аналитика может подсчитывать подавленные алерты;
- алерт остаётся доступным для расследования.

Это отличается от заглушки (silence), потому что является прямым результатом содержимого события, а не отдельно запланированного объекта подавления.

### 12.2 Drop

Drop означает:

- ни алерт, ни инцидент не создаются;
- эскалация или уведомление не запускаются;
- сохраняется отредактированное (с сокрытием) выполнение оркестрации на короткий срок хранения;
- счётчики отброшенных событий доступны;
- сырая полезная нагрузка не хранится бессрочно.

Меры предосторожности:

- публикация правила drop типа «catch-all» требует явного подтверждения;
- валидация предупреждает, когда большой процент повторно проигранных событий был бы отброшен;
- перед активацией рекомендуется теневой режим;
- для создания или публикации действий drop требуется разрешение RBAC.

### 12.3 Pause

Pause должен реализовывать отложенную активацию, а не просто отложенные уведомления.

Поведение:

```text
trigger
  → pending event created
  → activation scheduled

resolve before activation
  → pending event resolved
  → no alert group
  → no notifications

activation time reached
  → pending event enters existing alert lifecycle
```

Поведение при повторном срабатывании:

- обновить сохранённое нормализованное событие;
- сохранить исходное или пересчитать время активации в соответствии с явным правилом;
- добавить информацию в трассировку.

Требуемое поведение воркера:

- безопасно захватывать ожидающие строки (pending rows);
- быть идемпотентным;
- переносить перезапуски воркера;
- избегать двойной активации;
- предоставлять неуспешные активации для повтора.

## 13. Глобальный приём

Новый эндпоинт:

```text
POST /api/integrations/orchestration
```

Аутентификация:

```http
Authorization: Bearer GLOBAL_ORCHESTRATION_TOKEN
```

Эндпоинт должен:

1. аутентифицировать токен оркестрации;
2. принимать документированный обобщённый конверт события (event envelope);
3. опционально выбирать нормализатор;
4. выполнять глобальную оркестрацию;
5. выполнять выбранную сервисную оркестрацию;
6. передавать финальный результат в существующий жизненный цикл;
7. возвращать ID трассировки.

Если маршрут/сервис не выбран:

```text
catch-all route
unrouted event
explicit drop
```

должно быть настраиваемым.

Будущая страница UI должна показывать нераспределённые события (Unrouted Events) с возможностью повтора.

## 14. Действия-вебхуки и безопасность

Действия-вебхуки — единственный исполняемый тип автоматизации в v1.

Требуемые меры защиты:

- HTTPS по умолчанию;
- проверка сертификата TLS;
- таймаут;
- лимит повторов;
- лимит размера ответа;
- лимит редиректов;
- защита от DNS rebinding;
- блокировка loopback и link-local адресов;
- настраиваемый allowlist приватной сети;
- зашифрованные заголовки и секретные значения;
- сокрытие (redaction) в логах и трассировках;
- ключ идемпотентности;
- аудит выполнения;
- проверки разрешений;
- лимиты параллелизма и частоты в пределах группы.

Действия должны ставиться в очередь после того, как решение оркестрации сохранено.

## 15. Жизненный цикл версий

Требуемый рабочий процесс:

```text
Published version
    ↓ clone/edit
Draft
    ↓ validate
Simulate / Replay / Shadow
    ↓ publish
New published version
```

Операции:

- создать черновик;
- дублировать правило;
- проверить черновик;
- сравнить черновик с активной версией;
- симулировать полезную нагрузку;
- проиграть сохранённые события;
- опубликовать;
- откатить (rollback);
- заархивировать версию;
- экспортировать/импортировать определение.

Публикация должна быть атомарной.

Валидация должна обнаруживать:

- некорректные деревья условий;
- неподдерживаемые операторы;
- некорректные шаблоны;
- отсутствующие ссылочные сервисы или политики;
- межгрупповые ссылки;
- недостижимые правила, где это обнаруживается;
- небезопасный drop типа «catch-all»;
- некорректные длительности паузы;
- некорректные действия-вебхуки;
- циклическую или чрезмерную вложенность;
- дублирующиеся позиции правил.

## 16. Теневой режим

Теневой режим оценивает оркестрацию на реальных событиях, но не применяет результат.

Трассировка должна показывать:

```text
Current behavior
Draft/shadow behavior
Field-by-field difference
Routing difference
Disposition difference
```

Теневой режим должен собирать:

- количество совпадений;
- изменения маршрутизации;
- изменения серьёзности;
- потенциальные отбрасывания (drops);
- потенциальные подавления (suppressions);
- потенциальные паузы;
- ошибки выполнения.

В теневом режиме действия-вебхуки не выполняются.

## 17. Симулятор и повтор

Требуемые режимы симулятора:

```text
Paste payload
Use stored alert event
Replay one execution
Replay a selected event set
Compare active versus draft
```

Вывод симулятора:

- выбранный нормализатор;
- начальное нормализованное событие;
- каждое оценённое правило;
- результаты условий;
- извлечённые переменные;
- мутации полей;
- решения по маршрутизации и политикам;
- финальный исход;
- ошибки валидации;
- различие между активной версией и черновиком (active/draft diff).

Повтор не должен изменять промышленное состояние, если только не введён явный будущий режим применения.

## 18. Интеграция с Explain

Существующая трассировка Explain должна получить раздел Orchestration.

Каждая трассировка правила должна содержать:

```text
rule ID and name
matched/not matched
condition results
actions attempted
before/after field values
variables created
processing mode
duration
error-safe message
```

Финальная трассировка должна содержать:

```text
orchestration ID
version ID
initial context
final context
selected entities
disposition
pause/suppress/drop reason
queued action IDs
total duration
```

## 19. Режимы совместимости

IncidentRelay должен поддерживать:

```text
legacy
hybrid
orchestration
```

### Legacy

Текущие маршруты, правила сервисов и политики ведут себя в точности как раньше.

### Hybrid

Оркестрация выполняется первой. Существующие политики заполняют только значения, не заданные явно оркестрацией.

Пример:

```text
priority set by orchestration
→ Priority Policy does not override it

notification policy not set by orchestration
→ current Notification Policy evaluation continues
```

### Orchestration

Решения по маршрутизации и политикам в основном контролируются оркестрацией. Существующие компоненты жизненного цикла по-прежнему выполняют сохранение алертов, эскалацию, доставку уведомлений, корреляцию и оценку влияния.

Каждое финальное поле должно опционально хранить происхождение (provenance):

```json
{
  "priority": {
    "value": "P1",
    "source": "orchestration",
    "rule_id": 25
  }
}
```

## 20. Поверхность API

Реализованные эндпоинты control plane:

```text
GET    /api/event-orchestrations
POST   /api/event-orchestrations
GET    /api/event-orchestrations/catalog
GET    /api/event-orchestrations/{orchestration_id}
PATCH  /api/event-orchestrations/{orchestration_id}
DELETE /api/event-orchestrations/{orchestration_id}

POST   /api/event-orchestrations/{orchestration_id}/draft
PUT    /api/event-orchestrations/{orchestration_id}/draft
POST   /api/event-orchestrations/{orchestration_id}/validate
POST   /api/event-orchestrations/{orchestration_id}/publish
POST   /api/event-orchestrations/{orchestration_id}/rollback
PATCH  /api/event-orchestrations/{orchestration_id}/runtime
POST   /api/event-orchestrations/{orchestration_id}/simulate
POST   /api/event-orchestrations/{orchestration_id}/replay

GET    /api/event-orchestrations/{orchestration_id}/versions
GET    /api/event-orchestrations/{orchestration_id}/versions/{version_id}
GET    /api/event-orchestrations/{orchestration_id}/executions
GET    /api/event-orchestrations/{orchestration_id}/shadow-metrics

GET    /api/orchestration-webhook-actions
POST   /api/orchestration-webhook-actions
PATCH  /api/orchestration-webhook-actions/{action_id}
DELETE /api/orchestration-webhook-actions/{action_id}
GET    /api/orchestration-webhook-actions/{action_id}/executions
```

Сгенерированный документ OpenAPI включает рекурсивные схемы деревьев условий,
перечисление безопасных встроенных действий, метаданные авторов черновиков и
версий, а также доступные только для записи секретные заголовки webhook.
Отдельное руководство по публичному API находится в
[`docs/api/event-orchestration.md`](../api/event-orchestration.md).

## 21. UI

Пункт навигации:

```text
Event Orchestration
```

Предлагаемые разделы:

```text
Overview
Rules
Simulator
Versions
Executions
Webhook Actions
Settings
```

Конструктор правил:

```text
WHEN
  [labels.environment] [equals] [production]
  AND
  [severity] [in] [critical, high]

THEN
  [Set service] [Payments]
  [Set priority] [P1]
  [Set severity] [critical]

AFTER
  [Continue processing]
```

Требуемый UX:

- упорядоченные правила;
- переупорядочивание перетаскиванием (drag-and-drop);
- вложенные группы условий;
- автодополнение полей;
- по возможности автодополнение меток;
- селекторы сущностей;
- встроенная (inline) валидация;
- дублирование правила;
- включение/отключение правила;
- тестирование одного правила;
- просмотр JSON-определения;
- различие между активной версией и черновиком (active/draft diff);
- диалог публикации;
- предупреждения для действий drop и pause;
- просмотрщик трассировки выполнения.

## 22. RBAC

Предлагаемые разрешения:

```text
orchestration.view
orchestration.create
orchestration.edit
orchestration.publish
orchestration.delete
orchestration.simulate
orchestration.replay
orchestration.manage_tokens
orchestration.manage_actions
orchestration.view_executions
```

Публикация, действия drop, управление токенами и управление секретами вебхуков требуют повышенных разрешений.

## 23. Наблюдаемость

Требуемые метрики:

```text
orchestration_events_total
orchestration_rule_evaluations_total
orchestration_rule_matches_total
orchestration_duration_seconds
orchestration_errors_total
orchestration_dropped_events_total
orchestration_suppressed_events_total
orchestration_paused_events_total
orchestration_pending_events
orchestration_webhook_executions_total
orchestration_webhook_duration_seconds
```

Требуемые логи:

- публикация;
- откат;
- сбой выполнения;
- сбой активации ожидающего события;
- сбой выполнения вебхука;
- создание/отзыв токена;
- предупреждение валидации о небезопасном правиле.

Логи никогда не должны содержать токены приёма или незамаскированные секретные заголовки.

## 24. Лимиты

Первый релиз должен применять настраиваемые лимиты:

```text
maximum rules per version
maximum nesting depth
maximum actions per rule
maximum template output length
maximum regex length
maximum payload size
maximum pause duration
maximum webhook response size
maximum replay event count
trace retention
dropped-event trace retention
```

Лимиты защищают задержку (latency), хранилище и безопасность оператора.

## 25. Ожидания по производительности

Начальные целевые показатели:

- оценка оркестрации должна добавлять небольшие однозначные значения миллисекунд для обычных наборов правил;
- ни один сетевой вызов не должен выполняться синхронно во время приёма;
- опубликованные определения должны кешироваться;
- инвалидация кеша происходит после публикации или отката;
- оценка правил должна быть детерминированной;
- хранение трассировок выполнения должно быть настраиваемым или выборочным (sampled) для успешных высоконагруженных событий;
- сбой теневой оценки не должен приводить к сбою промышленного приёма.

Нагрузочные тесты должны включать:

- много простых правил;
- глубоко вложенные условия;
- большие наборы меток;
- условия с регулярными выражениями;
- параллельный глобальный приём;
- массовую активацию ожидающих событий;
- всплески очереди действий-вебхуков.

## 26. Миграция и выкат

Рекомендуемый выкат:

1. Добавить модели и API за feature-флагом.
2. Реализовать оценщик и симулятор без применения в промышленной среде.
3. Добавить теневой режим.
4. Протестировать на скопированных промышленных событиях.
5. Добавить гибридный режим.
6. Включить для выбранных групп.
7. Добавить глобальный приём.
8. Добавить действия pause и вебхуки после того, как базовая оценка станет стабильной.
9. Сохранять доступность режима legacy в течение всего выката v1.

Ни один существующий маршрут или политика не должны автоматически преобразовываться при первой миграции.

Более поздний помощник миграции может создавать черновики определений оркестрации из простых существующих правил маршрута/сервиса/приоритета.

## 27. Совместимость с миграцией из PagerDuty

Модель должна делать возможным последующее преобразование из PagerDuty.

Ожидаемые точные или почти точные сопоставления:

```text
PagerDuty service routing
→ global routing rules

PagerDuty severity and priority actions
→ event mutation and set_priority

PagerDuty escalation policy override
→ set_escalation_policy

PagerDuty dedup key action
→ set_dedup_key

PagerDuty suppress
→ suppress

PagerDuty pause
→ pause

PagerDuty webhook action
→ orchestration webhook action
```

Изначально не поддерживаемые конструкции PagerDuty следует импортировать только в аналитический отчёт:

- кеш-переменные;
- пороги частоты;
- последовательности событий;
- произвольные рекомбинирующие графы;
- нативные Automation Actions;
- вебхуки с секретами без явного одобрения.

## 28. Рабочие потоки поставки

### Workstream 1 — Модель данных и API версий

- миграции;
- репозитории;
- схемы;
- CRUD;
- draft/publish/rollback;
- RBAC;
- детерминированные экспорты.

### Workstream 2 — Оценщик условий

- вложенные условия;
- операторы;
- резолвер полей;
- валидация;
- структурированные причины совпадений;
- модульные (unit) и property-тесты.

### Workstream 3 — Движок действий

- реестр;
- мутация событий;
- маршрутизация;
- политики;
- группировка;
- извлечение переменных;
- шаблоны;
- происхождение (provenance).

### Workstream 4 — Интеграция во время выполнения

- глобальная и сервисная оркестрация;
- режимы legacy/hybrid/orchestration;
- передача в жизненный цикл (lifecycle handoff);
- кеш опубликованных определений;
- сохранение выполнений.

### Workstream 5 — Suppress, drop и pause

- семантика исходов;
- модель ожидающего события;
- воркер активации;
- разрешение до активации (resolve-before-activation);
- метрики и хранение трассировок.

### Workstream 6 — Действия-вебхуки

- зашифрованная конфигурация;
- воркер очереди;
- защита от SSRF;
- повторы и лимиты;
- UI аудита.

### Workstream 7 — Симулятор, повтор и теневой режим

- API симуляции;
- повтор сохранённых событий;
- сравнение активной версии и черновика;
- теневые метрики;
- интеграция с Explain.

### Workstream 8 — UI

- список оркестраций;
- конструктор правил;
- редактор дерева условий;
- редактор действий;
- симулятор;
- версии и diff;
- выполнения;
- действия-вебхуки.

### Workstream 9 — Документация и качество

- OpenAPI;
- пользовательская документация;
- архитектурная документация;
- примеры;
- нагрузочные тесты;
- тесты безопасности;
- процедуры обновления и отката.

## 29. Критерии приёмки

Event Orchestration v1 считается завершённым, когда:

1. Администратор группы может создать глобальную или сервисную оркестрацию.
2. Правила поддерживают вложенные условия AND/OR/NOT.
3. Правила могут извлекать переменные и использовать безопасные шаблоны.
4. Правила могут мутировать поля событий и метки.
5. Правила могут выбирать маршрут, сервис, команду, приоритет, политику эскалации и политику уведомлений.
6. Правила могут изменять группировку и дедупликацию.
7. Continue, stop, suppress, drop и pause имеют документированное и протестированное поведение.
8. Разрешение до активации паузы (resolve-before-pause-activation) не создаёт группу алертов и не отправляет уведомлений.
9. Действия-вебхуки выполняются асинхронно с защитой от SSRF и аудитом.
10. Черновики можно проверять, симулировать, публиковать и откатывать.
11. Опубликованные версии неизменяемы.
12. Теневой режим сообщает о различиях, не изменяя промышленное поведение.
13. Существующие события можно безопасно проигрывать на черновике.
14. Каждое промышленное решение видно в трассировке Explain.
15. Поддерживаются режимы legacy, hybrid и orchestration.
16. Существующие установки остаются в режиме legacy после обновления.
17. Документация OpenAPI и пользовательская документация полны.
18. Модульные, интеграционные тесты, тесты безопасности и нагрузочные тесты проходят.
19. Ключи каталога совпадают для каждого поддерживаемого языка UI.
20. Ни один секрет не раскрывается в логах, трассировках, ответах API или экспортированных определениях.

## 30. Отложенные последующие шаги

После стабилизации v1 оценить:

- кеш-переменные с TTL;
- условия по количеству/частоте/длительности событий;
- условия по уникальным хостам (distinct-host) и последовательностям;
- рекомбинирующие графы;
- нативные Automation Actions;
- шаги ручного одобрения;
- более богатый импорт оркестрации PagerDuty;
- аналитику оркестрации и рекомендации по оптимизации.
