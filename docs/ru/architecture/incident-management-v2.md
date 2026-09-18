# Управление инцидентами v2

**Статус:** Предложено  
**Цель:** Поэтапное внедрение с готовностью к production  
**Проект:** IncidentRelay  
**Предлагаемый путь документа:** `docs/architecture/incident-management-v2.md`

## 1. Назначение

Incident Management v2 отделяет операционный процесс работы с инцидентом от существующего жизненного цикла алертов IncidentRelay.

Цель — сохранить текущие механизмы приёма, группировки, эскалации и уведомления алертов, работу с ответственными, заинтересованными лицами, комментариями, корреляцией и влиянием на сервисы, добавив при этом полноценную запись `Incident` для проблем, требующих согласованного расследования, внешнего тикета, классификации, отчётности и закрытия.

Реализация не должна создавать второй конкурирующий жизненный цикл алерта. `AlertGroup` остаётся техническим агрегатом, а `Incident` становится отдельной операционной сущностью.

## 2. Текущее состояние

IncidentRelay уже предоставляет большую часть технической основы:

- `Alert` хранит нормализованный технический сигнал;
- `AlertGroup` объединяет связанные алерты и сейчас служит основным агрегатом повседневной работы с инцидентами;
- ручные инциденты создаются как `AlertGroup` с одним дочерним `Alert`, созданным вручную;
- несколько групп можно объединить;
- поддерживаются приоритеты инцидентов P1-P5;
- поддерживаются исполнители, ответственные и заинтересованные лица;
- поддерживаются комментарии и события временной шкалы;
- поддерживаются подтверждение, разрешение, эскалация и доставка уведомлений;
- влияние на сервисы и бизнес-сервисы вычисляется по группам алертов;
- для многих действий с инцидентами уже записываются события аудита;
- До 2.3 `/api/incidents` представлял AlertGroup как инциденты; в 2.3 этот контракт заменён first-class Incident, а технические операции перенесены в `/api/alert-groups`.

Не хватает отдельной операционной сущности Incident. Текущий процесс ручного создания инцидента должен сохраниться как ручное создание Alert Group, а ручное создание Incident должно создавать настоящую сущность Incident.

## 3. Архитектурное решение

### 3.1 Сохранить `AlertGroup` как технический агрегат

`AlertGroup` продолжает отвечать за:

- дедупликацию и группировку алертов;
- состояния firing, acknowledged, silenced, maintenance и resolved;
- состояние уведомлений и эскалаций;
- исполнителя и приоритет;
- влияние на сервисы;
- дочерние алерты;
- существующих ответственных, заинтересованных лиц, комментарии и временную шкалу.

Это позволяет избежать рискованной миграции текущего технического жизненного цикла.

### 3.2 Добавить отдельную сущность `Incident`

`Incident` — полноценная операционная запись, которая может существовать без Alert Group или связывать одну либо несколько связанных Alert Group.

Способы создания:

- ручное создание Incident;
- действие оператора **Create Incident** из Alert Group;
- классификация алерта как `Incident`;
- позднее: действие Event Orchestration;
- позднее: автоматизация по длительности, эскалации или корреляции.

Не каждой Alert Group нужен Incident.

### 3.3 Сохранить оба процесса ручного создания

Текущее ручное создание остаётся доступным под правильным названием:

```text
Create Alert Group
  -> AlertGroup
  -> один дочерний Alert, созданный вручную
```

Отдельное действие создаёт Incident:

```text
Create Incident
  -> самостоятельный Incident
  -> необязательно связанные Alert Group
```

Создание Alert Group не должно создавать Incident. Создание Incident не должно создавать скрытую Alert Group или Alert.

### 3.4 Хранить классификацию алерта отдельно

Классификация описывает операционный результат Alert Group и не должна заменять состояние её жизненного цикла.

Примеры:

- Incident;
- False Positive;
- Duplicate;
- Known Issue;
- No Action Required;
- Planned Activity;
- Test Alert;
- Other.

Группа может иметь состояние `resolved` и классификацию `False Positive`. Группа может иметь состояние `firing` и уже быть классифицирована как `Incident`.

### 3.5 Разделить техническое назначение и операционное владение

Назначение в AlertGroup и Incident отвечает на разные вопросы.

```text
AlertGroup.assignee
  Кто сейчас является технической целью уведомлений и эскалации?

Incident.assignee
  Кто сейчас владеет операционным расследованием?
```

Правила:

- после появления полноценных Incident сущность `AlertGroup` остаётся полноценным техническим эпизодом сигнала;
- `AlertGroup.assignee` по-прежнему выбирается и меняется маршрутом, расписанием и эскалацией;
- `Incident.assignee` хранит конкретного пользователя и может быть назначен, переназначен или очищен вручную;
- изменение `Incident.assignee` не должно менять исполнителя связанных AlertGroup, ротацию, состояние уведомлений или ход эскалации;
- изменение технического исполнителя AlertGroup не должно незаметно заменять исполнителя Incident;
- назначение Incident остаётся стабильным при обычной смене дежурства;
- в 2.4 On-call Roles могут определить текущих пользователей и скопировать конкретных пользователей в Incident;
- будущая автоматизация может явно переназначить Incident, но ротация расписания сама по себе не является живой ссылкой на владение Incident.

Это архитектурное решение для предложения #83.

### 3.6 Безопасное повторное использование AlertGroup при flapping

Разрешённый дочерний `Alert` остаётся финальным техническим occurrence и никогда не переводится обратно в `firing`.

При этом разрешённая `AlertGroup` может быть повторно использована, если приходит новый подходящий firing occurrence и Event Orchestration явно разрешает окно повторного открытия.

Правила:

- политикой управляет Event Orchestration через `set_grouping.reopen_window_seconds`;
- отсутствие поля или `0` означает disabled и сохраняет текущее поведение;
- `set_grouping.window_seconds` и `reopen_window_seconds` — разные понятия;
- повторное открытие создаёт новый дочерний Alert occurrence;
- старые resolved Alert остаются resolved и сохраняют свои timestamps;
- после истечения reopen window новый matching firing создаёт новую AlertGroup;
- состояние `closed` не добавляется в технический state machine AlertGroup;
- `closed` остаётся финальным операционным состоянием полноценного Incident;
- отсутствие webhook/update не считается recovery по умолчанию.

Это архитектурное решение для предложения #84 и workstream #85.

### Граница ответственности AlertGroup и Incident

Целевая модель сохраняет обе сущности полноценными:

```text
Alert -> AlertGroup        технический эпизод сигнала
             -> Incident   необязательное операционное расследование
```

`AlertGroup` продолжает отвечать за:

- child Alert occurrence, grouping и deduplication;
- technical lifecycle и source state;
- routing, notification и escalation;
- technical assignee и ручное переназначение AlertGroup;
- technical priority/context, Silence, maintenance и shelving;
- impact, correlation и source context;
- technical timeline;
- **технические комментарии**.

`Incident` отвечает за:

- независимый operational workflow;
- operational assignee и ручное переназначение Incident;
- Incident Commander и responders;
- stakeholders;
- affected-service context;
- **операционные комментарии**;
- root cause и resolution summary;
- external ITSM references;
- postmortem и corrective actions.

```text
AlertGroup.assignee = текущая техническая ответственность / paging target
Incident.assignee   = владелец операционного расследования
```

Оба назначения можно менять вручную, но они независимы. AlertGroup reassignment
не означает ACK и не сбрасывает escalation policy, escalation level, rotation
или next scheduled escalation.

#83 трактуется прежде всего как ручное переназначение текущего
`AlertGroup.assignee`, потому что текущий UI называет AlertGroup инцидентом.
Ручное переназначение first-class Incident остаётся отдельной capability 2.3.

Комментарии:

- AlertGroup comments остаются техническими заметками;
- Incident comments используются для operational collaboration;
- combined Incident activity может показывать комментарии linked AlertGroup с
  явным source/target;
- комментарии не копируются автоматически между объектами.

Responders/stakeholders:

- canonical ownership переходит в Incident;
- legacy AlertGroup records сохраняются во время staged migration;
- окончательное удаление legacy operational storage относится к 2.9;
- technical comments AlertGroup cleanup не удаляет.

## 4. Терминология

```text
Alert
  Один нормализованный технический сигнал, сохранённый IncidentRelay.

Alert Group
  Технический агрегат одного или нескольких Alert. Управляет текущим жизненным
  циклом алерта, уведомлений и эскалаций.

Incident
  Отдельная операционная запись, которая может существовать без Alert Group
  или связывать одну либо несколько связанных Alert Group.

Classification
  Проверенный результат Alert Group. Не зависит от состояния алерта и
  состояния инцидента.
```

## 5. Цели

Поэтапная реализация должна предоставить:

1. Необязательную классификацию групп алертов.
2. Необязательное требование классифицировать группу перед ручным закрытием.
3. Отдельные сущности `AlertGroup` и `Incident`.
4. Ручное создание Alert Group с одним дочерним Alert.
5. Ручное создание самостоятельного Incident и необязательную привязку из Alert Group.
6. Операционное состояние процесса, отдельное от состояния алерта.
7. Связывание относящихся к инциденту групп алертов без обязательного разрушительного объединения.
8. Классификацию дубликата со ссылкой на канонический инцидент.
9. Сводки о первопричине и разрешении.
10. Ссылки на внешние тикеты.
11. Нейтральную к провайдеру платформу интеграции с ITSM.
12. Интеграцию с Event Orchestration.
13. Метрики и отчёты по инцидентам.
14. Полную поддержку аудита, временной шкалы, RBAC, OpenAPI и пользовательской документации.

## 6. Что не входит в первый релиз

Первый релиз не должен включать:

- полную двустороннюю синхронизацию со всеми ITSM-провайдерами;
- создание или группировку инцидентов с помощью машинного обучения;
- автоматический анализ первопричины;
- произвольное владение между группами, относящимися к разным группам безопасности;
- замену логики уведомлений или эскалаций `AlertGroup`;
- автоматическое разрушительное объединение групп алертов;
- обязательную классификацию для каждой команды;
- блокировку автоматического разрешения от источника при отсутствии классификации;
- полноценный редактор разбора инцидента.

## 7. Доменная модель

### 7.1 Классификация группы алертов

Добавьте nullable-поля классификации в `AlertGroup` либо модель проверки с отношением один к одному.

Предлагаемые поля:

```text
classification                 nullable slug
classification_note            nullable text
classified_by_id               nullable user
classified_at                  nullable datetime
classification_incident_id     nullable incident
```

Рекомендуемые встроенные slug:

```text
incident
false_positive
duplicate
known_issue
no_action_required
planned_activity
test_alert
other
```

Правила:

- по умолчанию классификация необязательна;
- изменение классификации создаёт события временной шкалы и аудита;
- `incident` может создать или связать `Incident`;
- `duplicate` должен требовать каноническую Alert Group или Incident;
- автоматическое разрешение источником не должно завершаться ошибкой из-за отсутствия классификации;
- команда может требовать классификацию перед ручным закрытием, но не перед автоматическим разрешением.

### 7.2 Incident

Предлагаемые поля:

```text
id
team_id
service_id                     nullable
workflow_status                declared | investigating | identified |
                               monitoring | resolved | closed | cancelled
title
description                    nullable text
priority                       nullable
assignee_id                    nullable user
summary                        nullable text
root_cause                     nullable text
resolution_summary             nullable text
declared_by_id                 nullable user
declared_at
investigation_started_at       nullable datetime
identified_at                  nullable datetime
monitoring_at                  nullable datetime
resolved_at                    nullable datetime
closed_by_id                   nullable user
closed_at                      nullable datetime
created_at
updated_at
```

Ответственные, заинтересованные лица, комментарии и операционная временная шкала относятся к Incident. Состояние уведомлений и эскалаций остаётся в `AlertGroup`.

Правила:

- Incident может существовать без Alert Group;
- Incident может связывать одну или несколько Alert Group;
- ручное создание Incident создаёт только Incident;
- закрытие Incident не удаляет, не архивирует и не разрешает связанные Alert Group;
- разрешение Alert Group может перевести Incident в состояние `resolved`, но никогда автоматически не переводит его в `closed`;
- повторное открытие связанной группы может вернуть Incident из `resolved` или `monitoring`;
- `closed` — явное операционное действие.

### 7.3 IncidentAlertGroupLink

Если группы должны оставаться независимо отслеживаемыми, используйте отношение вместо разрушительного объединения.

Предлагаемые поля:

```text
id
incident_id
group_id
relation_type                  primary | related | symptom | duplicate
linked_by_id
linked_at
removed_by_id                  nullable
removed_at                     nullable
```

Правила:

- у Incident может не быть связанных Alert Group;
- одна Alert Group не может быть дважды активно связана с одним инцидентом;
- добавление или удаление группы создаёт события временной шкалы и аудита;
- связанные Alert Group сохраняют собственные источник, дедупликацию и временную шкалу;
- существующее ручное объединение остаётся доступным для случаев, когда группы действительно должны стать одним техническим агрегатом.

### 7.4 IncidentExternalReference

Предлагаемые поля:

```text
id
incident_id
provider                       jira_service_management | servicenow | glpi |
                               generic | other
external_id
external_key                   nullable
url
external_status                nullable
source_of_truth                incidentrelay | external | link_only
sync_status                    idle | pending | synced | failed | disabled
last_synced_at                 nullable
last_error                     nullable
metadata_json                  nullable
created_by_id
created_at
updated_at
```

Секреты и конфигурацию провайдера нельзя хранить в этой таблице.

### 7.5 Конфигурация интеграции Incident

Учётные данные провайдера и сопоставление полей должны храниться в конфигурации интеграции, принадлежащей группе.

Предлагаемые возможности:

- тип провайдера;
- базовый URL;
- зашифрованные или защищённые учётные данные;
- идентификатор проекта или очереди;
- сопоставление приоритетов;
- сопоставление состояний;
- сопоставление сервиса и команды;
- режим источника истины;
- секрет входящего webhook;
- разрешённые действия;
- политика повторных попыток.

## 8. Модель жизненного цикла

### 8.1 Жизненный цикл алерта не меняется

```text
firing
acknowledged
silenced
maintenance
resolved
```

Это состояние управляет уведомлениями, эскалацией и техническим влиянием.

### 8.2 Рабочий процесс Incident

```text
declared
  -> investigating
  -> identified
  -> monitoring
  -> resolved
  -> closed
```

Необязательные переходы:

```text
declared -> cancelled
resolved -> investigating     при повторном открытии связанного алерта
closed -> investigating       явное действие повторного открытия
```

### 8.3 Правила синхронизации

Рекомендуемые значения по умолчанию для первой версии:

- создание или связывание Incident не меняет состояние Alert Group;
- ручное создание Alert Group не создаёт Incident;
- ручное создание Incident не создаёт Alert Group;
- подтверждение Alert Group не меняет автоматически состояние Incident;
- когда все активно связанные группы разрешены, Incident может перейти в `resolved`;
- Incident никогда не закрывается автоматически;
- если любая связанная группа снова становится неразрешённой, Incident в состоянии resolved возвращается в `investigating`;
- классификация не меняется при изменении состояния;
- в зависимости от настроек группы закрытие может требовать классификацию.

## 9. Политика классификации

Предлагаемый режим на уровне группы:

```text
off
optional
required_before_manual_close
```

Важные особенности поведения:

- автоматическое разрешение от интеграции принимается всегда;
- если классификация обязательна, автоматически разрешённая группа помечается как требующая проверки;
- вместо сохранения технического алерта в состоянии firing UI показывает очередь проверки;
- при настроенном требовании ручное разрешение или закрытие запрашивает классификацию;
- команды, не использующие классификацию, сохраняют текущий процесс.

Предлагаемые действия классификации:

```text
Incident
  Предложить создать Incident или связать Alert Group с существующим Incident.

Duplicate
  Потребовать выбрать каноническую Alert Group или Incident.

Known Issue
  Разрешить необязательную ссылку на проблему или тикет.

False Positive / Test Alert / Planned Activity / No Action Required
  Сохранить результат без создания инцидента.
```

## 10. Разрешения

Используйте существующую RBAC команд и групп.

### Чтение

Разрешено пользователям, которые могут читать данные основной команды инцидента.

### Классификация и операционные действия

Разрешено следующим ролям:

- глобальный администратор;
- редактор группы команды;
- менеджер команды;
- ответственный команды.

### Настройка классификации и ITSM-интеграций

Разрешено следующим ролям:

- глобальный администратор;
- редактор владеющей группы.

### Связывание между группами

Пользователь должен иметь доступ на чтение к обеим группам и доступ на запись или реагирование в команде инцидента. Межгрупповые связи не должны раскрывать данные недоступной группы.

## 11. Стратегия API

Этот релиз непосредственно меняет семантику API, не вводя промежуточный API.

Текущее поведение Alert Group переносится из `/api/incidents` в `/api/alert-groups`.

```text
GET    /api/alert-groups
POST   /api/alert-groups
GET    /api/alert-groups/{id}
PATCH  /api/alert-groups/{id}
POST   /api/alert-groups/{id}/acknowledge
POST   /api/alert-groups/{id}/resolve
POST   /api/alert-groups/{id}/reopen
POST   /api/alert-groups/{id}/merge
PUT    /api/alert-groups/{id}/classification
DELETE /api/alert-groups/{id}/classification
POST   /api/alert-groups/{id}/create-incident
```

`POST /api/alert-groups` сохраняет текущее поведение ручного создания и в одной транзакции создаёт `AlertGroup` с одним дочерним `Alert`, созданным вручную.

`/api/incidents` становится настоящим API Incident:

```text
GET    /api/incidents
POST   /api/incidents
GET    /api/incidents/{id}
PATCH  /api/incidents/{id}
POST   /api/incidents/{id}/status
POST   /api/incidents/{id}/close
POST   /api/incidents/{id}/reopen
GET    /api/incidents/{id}/alert-groups
POST   /api/incidents/{id}/alert-groups
DELETE /api/incidents/{id}/alert-groups/{group_id}
GET    /api/incidents/{id}/external-references
POST   /api/incidents/{id}/external-references
PATCH  /api/incidents/{id}/external-references/{reference_id}
DELETE /api/incidents/{id}/external-references/{reference_id}
```

`POST /api/incidents` создаёт только Incident и может дополнительно связать существующие Alert Group. Он не должен создавать скрытую Alert Group или Alert.

Это документированное несовместимое изменение API. OpenAPI, вызовы frontend, тесты и документация интеграций должны быть обновлены в том же релизе.

## 12. Архитектура UI

### 12.1 Страница Alerts

Сохраните текущую страницу Alerts для всех групп алертов.

Добавьте:

- действие **Create Alert Group**, создающее AlertGroup и один дочерний Alert вручную;
- значок и фильтр классификации;
- действие **Classify**;
- действие **Create Incident**;
- действие **Link to incident**;
- фильтр групп, требующих проверки;
- ссылку на канонический инцидент для дубликатов.

### 12.2 Страница Incidents

Добавьте отдельную страницу верхнего уровня, а не страницу Administration.

Добавьте отдельное действие **Create Incident**. Оно создаёт только Incident и может дополнительно связать существующие Alert Group.

Фильтры списка:

- состояние рабочего процесса;
- команда и сервис;
- приоритет;
- исполнитель;
- классификация;
- внешний провайдер и состояние;
- период открытия, разрешения или закрытия;
- поиск.

### 12.3 Рабочее пространство Incident

Разделы:

- сводка и текущее состояние;
- связанные Alert Group;
- активные алерты и состояние источников;
- приоритет, исполнитель и сервис;
- ответственные и заинтересованные лица;
- комментарии и временная шкала действий;
- сводка первопричины и разрешения;
- внешние тикеты;
- runbook'и, дашборды и ссылки сервиса;
- влияние и зависимости;
- метаданные аудита.

## 13. Интеграция с Event Orchestration

Добавляйте действия только после стабилизации ручных процессов.

Предлагаемые действия:

```text
create_alert_group
declare_incident
set_alert_classification
attach_to_open_incident
create_incident_draft
set_incident_priority
```

Предлагаемые триггеры:

- серьёзность или приоритет;
- сервис или маршрут;
- метки и источник;
- отсутствие похожего открытого инцидента;
- порог длительности алерта;
- достижение шага эскалации;
- уверенность корреляции.

Триггеры длительности и эскалации требуют асинхронных хуков и не должны реализовываться исключительно как правила времени приёма.

## 14. Архитектура интеграции с ITSM

Используйте нейтральный к провайдеру интерфейс сервиса и модель outbox с повторными попытками.

Предлагаемый интерфейс провайдера:

```text
create_external_incident()
update_external_incident()
add_external_comment()
resolve_external_incident()
fetch_external_incident()
handle_inbound_webhook()
validate_configuration()
```

Первая поставка должна поддерживать внешние ссылки только для привязки (**link-only**). После этого первым активным провайдером может стать Jira Service Management.

Рекомендуемый порядок внедрения:

1. Сохранять внешний ID и URL вручную.
2. Создавать тикет JSM из IncidentRelay.
3. Передавать выбранные обновления из IncidentRelay.
4. Получать обновления webhook от JSM.
5. Добавить настраиваемый источник истины и обработку конфликтов.

## 15. Отчётность

Начальные метрики:

- созданные Incidents;
- вручную созданные Alert Group;
- вручную созданные Incidents;
- доля преобразований Alert Group в Incident;
- инциденты по сервисам, командам и приоритетам;
- распределение классификаций;
- доля ложных срабатываний;
- доля дубликатов;
- время до подтверждения;
- время до объявления;
- время до начала расследования;
- время до разрешения;
- время до закрытия;
- количество повторных открытий;
- количество связанных групп алертов;
- инциденты с внешними тикетами;
- ошибки внешней синхронизации.

Не перегружайте термин MTTR разными значениями. В отчётах должны быть явно указаны измеряемые временные метки.

## 16. Аудит и временная шкала

Предлагаемые имена событий:

```text
alert_classification_set
alert_classification_changed
alert_classification_cleared
incident_declared
incident_status_changed
incident_closed
incident_reopened
incident_group_linked
incident_group_unlinked
incident_external_reference_added
incident_external_reference_updated
incident_external_reference_removed
incident_external_sync_failed
incident_root_cause_updated
incident_resolution_updated
```

Каждое изменение должно записывать одновременно:

- видимое пользователю событие временной шкалы, если это полезно для операционной работы;
- запись `AuditLog` в области группы и команды с отредактированными данными.

## 17. Миграция и совместимость

Рекомендуемая стратегия миграции:

- добавить nullable-поля классификации;
- добавить новые таблицы Incident и отношения Incident-to-AlertGroup;
- не переименовывать и не перестраивать `AlertGroup`;
- сохранить каждую существующую Alert Group и дочерний Alert;
- перенести текущее поведение API Alert Group в `/api/alert-groups`;
- в том же релизе заменить `/api/incidents` настоящим API Incident;
- переименовать текущее действие ручного создания инцидента в **Create Alert Group**, не меняя его поведение;
- сохранить записи, созданные прежним ручным действием, как ручные Alert Group с дочерними Alert;
- действие **Create Incident** должно создавать только Incident;
- не создавать Incidents задним числом для каждой исторической Alert Group;
- создавать или связывать исторические Incidents только по явному правилу миграции или действию администратора;
- обновить OpenAPI, вызовы frontend, тесты и документацию в составе несовместимого релиза;
- использовать feature flags только для автоматической синхронизации, а не для сохранения конфликтующей семантики API.

## 18. Версионированный план поставки

### IncidentRelay 2.3: Incident Core и ownership

- first-class `Incident` и `IncidentAlertGroupLink`;
- manual Incident, Create Incident from AlertGroup, basic link/unlink;
- independent Incident lifecycle, team/service/priority;
- manual Incident assign/reassign/unassign и **Assign to me**;
- manual AlertGroup assign/reassign и **Assign to me** для #83;
- AlertGroup reassignment не делает ACK и не сбрасывает escalation state;
- breaking `/api/alert-groups` vs `/api/incidents` split;
- отдельные Alerts/Incidents UI и минимальный Incident workspace;
- technical comments AlertGroup сохраняются;
- RBAC, audit, timeline, migrations, concurrency, OpenAPI и docs.

### IncidentRelay 2.4: Lifecycle resilience и flapping

- #84/#85 Event Orchestration `set_grouping.reopen_window_seconds`;
- disabled by default;
- reopen создаёт новый child Alert, старые resolved child Alert остаются terminal;
- concurrency для resolve/reopen и duplicate delivery;
- linked resolved/monitoring Incident может вернуться в `investigating`;
- recovery notification hysteresis / delayed resolved notification;
- отмена pending recovery notification при быстром reopen;
- Explain, audit, timeline и UI context.

### IncidentRelay 2.5: Incident collaboration

- Incident Commander и responders;
- Incident stakeholders и snapshot service-default stakeholders;
- operational comments Incident и richer activity;
- root cause и resolution summary;
- affected services и runbook/dashboard/dependency/impact context;
- technical comments AlertGroup остаются отдельным target;
- combined Incident activity может показывать comments linked AlertGroup с
  явным source attribution;
- staged migration legacy AlertGroup responder/stakeholder data при наличии
  однозначного Incident mapping;
- Incident не создаётся задним числом только ради migration collaboration data.

### IncidentRelay 2.6: Classification, relations и merge/split

- AlertGroup classification и review policy;
- review-required queue;
- duplicate canonical AlertGroup/Incident targets;
- relation types `primary`, `related`, `symptom`, `duplicate`;
- Incident merge/split;
- technical AlertGroup merge/link reconciliation;
- RBAC, audit, history и concurrency.

### IncidentRelay 2.7: On-call Roles и Incident automation

- #59 On-call Roles и concurrent role-aware coverage;
- role-aware suggestions assignee/commander/responders;
- concrete users вместо live schedule ownership links;
- #51 Event Orchestration Incident actions;
- draft-and-confirm, similar-open-Incident checks, idempotency;
- async duration/escalation hooks;
- optional stale-signal policy, disabled by default;
- inactivity сама по себе не означает recovery.

### IncidentRelay 2.8: ITSM и Jira

- #52 `IncidentExternalReference` и provider-neutral ITSM;
- manual external references, protected connector config;
- outbox, retries, idempotency, dead-letter;
- #53 Jira/JSM create/update;
- authenticated inbound events, source-of-truth/conflict handling;
- sync-loop prevention, secret redaction, SSRF/private-network controls.

### IncidentRelay 2.9: Analytics, Postmortems и final cleanup

- #54 analytics Incident/AlertGroup с точными lifecycle definitions;
- отдельные Incident reopen и AlertGroup reopen/flapping metrics;
- classification, alert-quality и external-ticket metrics;
- #60 configurable Postmortems / Incident Reviews;
- corrective actions с owner/due date и export/reporting;
- final Incident v2 cleanup;
- deprecated AlertGroup responder/stakeholder write flows удаляются только после
  reconciliation;
- technical comments AlertGroup и operational comments Incident сохраняются;
- удаляются legacy Incident-as-AlertGroup terminology/helpers/adapters;
- obsolete compatibility DB structures удаляются только explicit idempotent
  migrations с reconciliation и rollback boundary;
- historical Incident не создаются только ради cleanup.

### Cross-release hardening rule

Каждый релиз включает RBAC, audit, timeline, migrations, concurrency, OpenAPI,
localization, tests и docs для собственного scope.

## 19. Release gate IncidentRelay 2.3

Incident Core готов к 2.3, когда:

- границы Alert, AlertGroup и Incident явны и протестированы;
- AlertGroup остаётся полноценным technical signal episode;
- `/api/alert-groups` представляет AlertGroup, `/api/incidents` — только
  first-class Incident;
- manual AlertGroup атомарно создаёт group и один child Alert;
- manual Incident создаёт только Incident;
- Incident может иметь ноль или несколько linked AlertGroup;
- linked AlertGroup сохраняют собственный technical lifecycle;
- authorized operator может вручную reassign AlertGroup assignee;
- AlertGroup reassignment не делает ACK и не сбрасывает escalation state;
- authorized operator может assign/reassign/unassign Incident ownership;
- AlertGroup и Incident assignments независимы;
- technical comments AlertGroup остаются поддерживаемыми;
- минимальный Incident UI, RBAC, audit, migration, concurrency и OpenAPI
  production-ready;
- flapping/reopen behavior 2.4 не блокирует 2.3.

Collaboration, classification, role-aware scheduling, automation, ITSM,
analytics, postmortems и cleanup более поздних релизов не блокируют 2.3.

## 20. Критерии успеха

Архитектура успешна, если:

- существующая техническая обработка Alert Group остаётся стабильной;
- операторы могут отличить техническую Alert Group от операционного Incident;
- ручное создание Alert Group создаёт AlertGroup и один дочерний Alert;
- ручное создание Incident создаёт только Incident;
- Alert Group могут существовать без Incidents;
- Incidents могут существовать без Alert Group;
- классификация предоставляет надёжные данные о качестве алертов;
- один Incident может связывать одну или несколько независимых Alert Group;
- связанные алерты можно подключать, не разрушая их исходный жизненный цикл;
- внешнюю систему тикетов можно добавить без полей конкретного провайдера в основной модели;
- текущий жизненный цикл уведомлений и эскалаций остаётся стабильным;
- весь доступ контролируется существующей RBAC групп и команд.

### Примечание по реализации 2.3: хранение Incident и конкурентные изменения

В Incident Core 2.3 используется отдельная first-class запись `Incident` и
исторические записи `IncidentAlertGroupLink`. Операционные изменения защищены
optimistic concurrency через `Incident.row_version`: клиент передаёт прочитанную
версию, а устаревшая запись отклоняется вместо тихого перезаписывания более
нового состояния Incident.

Переходы workflow проверяются централизованно. Изменение `Incident.assignee`
меняет только операционного владельца Incident и не ACK-ает связанный AlertGroup,
не меняет его rotation, escalation state или технического assignee. В 2.3
базовые связи имеют типы `primary` и `related`. Unlink не удаляет историю:
заполняется `removed_at`, а повторный link создаёт новую аудируемую запись.

Каждая core-операция пишет `IncidentEvent` для операционной timeline и запись
`AuditLog`. Технические комментарии и timeline AlertGroup остаются отдельными и
не изменяются.
