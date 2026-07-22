# SLI / SLO сервиса

SLI/SLO в IncidentRelay добавляет целевые показатели надёжности на уровне сервиса, используя данные, которыми IncidentRelay уже владеет: группы алертов, метки времени подтверждения и разрешения, статус сервиса, окна обслуживания и метаданные каталога сервисов.

Функция намеренно называется **SLI / SLO** в UI и API.

- **SLI** — Service Level Indicator (индикатор уровня сервиса). Определяет, что измеряется для сервиса.
- **SLO** — Service Level Objective (цель уровня сервиса). Определяет целевое значение для SLI.
- **Измерение SLO** — последний результат расчёта для SLO за его настроенное окно.

Пример:

```text
SLI: Critical alert acknowledgement latency
SLO: 95% of critical alert groups must be acknowledged within 15 minutes over 30 days
```

## Где создавать SLI и SLO

SLI и SLO настраиваются в модальном окне сведений о сервисе.

Откройте:

```text
Services → service row → Details
```

или щёлкните по имени сервиса в таблице Services, если UI открывает модальное окно сведений по имени.

Внутри модального окна сведений о сервисе используйте раздел:

```text
SLI / SLO
```

Типичный порядок действий:

1. Откройте модальное окно сведений о сервисе.
2. Прокрутите до **SLI / SLO**.
3. Нажмите **Add SLI**.
4. Выберите тип SLI, источник и фильтры.
5. Сохраните SLI.
6. Нажмите **Add SLO**.
7. Выберите созданный выше SLI.
8. Настройте целевое значение и окно оценки.
9. Сохраните SLO.

SLI необходимо создать первым. SLO всегда привязан ровно к одному SLI.

## Где просматривать SLI и SLO

SLI/SLO виден в трёх местах.

### 1. Сведения о сервисе

Откройте:

```text
Services → service row → Details → SLI / SLO
```

Это представление показывает SLI/SLO для одного сервиса:

```text
SLI name
SLO name
current value
target
status
window
error budget, when applicable
```

Используйте это представление при исследовании одного сервиса.

### 2. Аналитика сервисов

Откройте:

```text
Services → Analytics → SLI / SLO health
```

Это представление показывает агрегированное состояние SLO по сервисам в текущей области группы/команды:

```text
Total SLOs
Met
At risk
Breached
No data
Services with SLOs
```

Оно также включает таблицу с последними измерениями SLO:

```text
Service | SLI | SLO | Current | Target | Status | Window | Budget
```

Используйте это представление, чтобы быстро находить сервисы с нарушенными или находящимися под риском SLO.

### 3. Хронология сервиса

Откройте:

```text
Services → service row → Details → Timeline
```

Действия создания, обновления и удаления SLI/SLO записываются в хронологию сервиса через адаптер событий каталога сервисов.

Типы событий хронологии:

```text
service_sli.created
service_sli.updated
service_sli.deleted
service_slo.created
service_slo.updated
service_slo.deleted
```

Категория:

```text
sli_slo
```

## Поддерживаемые типы SLI

### `alert_ack_latency`

Измеряет, насколько быстро подтверждаются группы алертов.

Исходные данные:

```text
AlertGroup.first_seen_at
AlertGroup.acknowledged_at
```

Хорошее событие:

```text
acknowledged_at - first_seen_at <= SLO threshold
```

Типичный SLO:

```text
95% of critical alert groups must be acknowledged within 15 minutes over 30 days.
```

Рекомендуемые поля SLO:

```json
{
  "target_percent_basis_points": 9500,
  "threshold_seconds": 900,
  "window_days": 30,
  "include_open_alerts": true,
  "enabled": true
}
```

### `alert_resolve_latency`

Измеряет, насколько быстро разрешаются группы алертов.

Исходные данные:

```text
AlertGroup.first_seen_at
AlertGroup.resolved_at
```

Хорошее событие:

```text
resolved_at - first_seen_at <= SLO threshold
```

Типичный SLO:

```text
90% of critical alert groups must be resolved within 4 hours over 30 days.
```

Рекомендуемые поля SLO:

```json
{
  "target_percent_basis_points": 9000,
  "threshold_seconds": 14400,
  "window_days": 30,
  "include_open_alerts": true,
  "enabled": true
}
```

### `incident_availability`

Оценивает доступность по интервалам влияющих алертов.

Исходные данные:

```text
AlertGroup.first_seen_at
AlertGroup.resolved_at
```

Если включён `include_open_alerts`, открытые группы алертов завершаются в момент расчёта. Перекрывающиеся интервалы объединяются перед расчётом простоя, поэтому одновременные инциденты не учитывают простой дважды.

Этот SLI намеренно называется **доступностью на основе инцидентов**. Это не доступность синтетического мониторинга и не доступность Prometheus. Он отвечает на вопрос:

```text
How much of the window did this service have active impact incidents?
```

Типичный SLO:

```text
99.9% incident-based availability over 30 days, excluding maintenance windows.
```

Рекомендуемые поля SLO:

```json
{
  "target_percent_basis_points": 9990,
  "window_days": 30,
  "exclude_maintenance": true,
  "include_open_alerts": true,
  "enabled": true
}
```

### `incident_count`

Подсчитывает совпадающие группы алертов в скользящем окне.

Типичный SLO:

```text
No more than 3 P1/P2 impact incidents over 30 days.
```

Рекомендуемые поля SLO:

```json
{
  "threshold_count": 3,
  "window_days": 30,
  "include_open_alerts": true,
  "enabled": true
}
```

## Поля SLI

SLI определяет, что измерять.

Общие поля:

| Поле | Значение |
| --- | --- |
| `slug` | Стабильный идентификатор внутри сервиса. |
| `name` | Понятное человеку имя SLI. |
| `description` | Необязательное пояснение. |
| `sli_type` | Что измеряет IncidentRelay. |
| `source` | Откуда поступают данные измерений. |
| `severity` | Необязательный фильтр серьёзности для SLI-типов реагирования, например `critical`. |
| `priority` | Необязательный фильтр по одному приоритету, например `p1`. Для SLI-типов влияния предпочтительнее `configuration.priority_scope`. |
| `configuration.priority_scope` | Список приоритетов, используемый доступностью на основе инцидентов и подсчётом инцидентов, например `["p1", "p2"]`. По умолчанию P1/P2 для SLI-типов влияния. |
| `enabled` | Включает или отключает этот SLI. |

Поддерживаемые значения `sli_type`:

```text
alert_ack_latency
alert_resolve_latency
incident_availability
incident_count
```

Поддерживаемый встроенный источник:

```text
incidentrelay_alert_groups
```

Будущие источники можно добавить позже, например Prometheus, blackbox-проверки, логи или внешние API метрик.

### Область приоритетов для SLI-типов влияния

`incident_availability` и `incident_count` — это SLI-типы, ориентированные на влияние. По умолчанию они используют приоритет группы алертов, а не серьёзность алерта:

```json
{
  "configuration": {
    "priority_scope": ["p1", "p2"]
  }
}
```

Это означает, что предупреждающий алерт P1/P2 может считаться влиянием, тогда как критический алерт P3 не считается простоем для доступности на основе инцидентов. Серьёзность остаётся полезной для SLI-типов реагирования, таких как задержка подтверждения и разрешения.

## Поля SLO

SLO определяет целевое значение для SLI.

Общие поля:

| Поле | Значение |
| --- | --- |
| `sli_id` | SLI, которому принадлежит этот SLO. |
| `name` | Понятное человеку имя SLO. |
| `description` | Необязательное пояснение. |
| `target_percent_basis_points` | Целевой процент, хранимый в базисных пунктах. Используется SLO задержки и доступности. |
| `threshold_seconds` | Порог времени в секундах. Используется SLO задержки подтверждения и разрешения. |
| `threshold_count` | Максимально допустимое количество инцидентов. Используется SLO подсчёта инцидентов. |
| `window_days` | Скользящее окно оценки. |
| `exclude_maintenance` | Исключает окна обслуживания из учёта простоя доступности инцидентов. |
| `include_open_alerts` | Включает открытые группы алертов в расчёты. |
| `enabled` | Включает или отключает этот SLO. |

Внутреннее значение `comparison` выводится бэкендом из типа SLI. Пользователям не нужно выбирать его в UI.

Правила сравнения, выводимые бэкендом:

```text
alert_ack_latency        → percent_good_gte
alert_resolve_latency    → percent_good_gte
incident_availability    → percent_good_gte
incident_count           → value_lte
```

## Процентные значения и базисные пункты

Целевые проценты хранятся в базисных пунктах, чтобы избежать дрейфа чисел с плавающей точкой.

```text
95%    = 9500
99%    = 9900
99.9%  = 9990
99.99% = 9999
```

Ответ API может также включать понятные человеку процентные значения, такие как:

```text
target_percent
value_percent
```

## Статусы SLO

### `met`

Текущее значение удовлетворяет целевому, и нет отложенных событий в окне, которые всё ещё могли бы его нарушить.

### `at_risk`

Текущее измеренное значение удовлетворяет целевому, но внутри настроенного порога всё ещё существуют отложенные события.

Пример:

```text
An alert was created 5 minutes ago.
The ACK threshold is 15 minutes.
The alert is not acknowledged yet.
The SLO is still technically within target, but it can breach soon.
```

### `breached`

Текущее значение не удовлетворяет целевому.

### `no_data`

В окне нет совпадающих событий или SLO невозможно оценить.

## Бюджет ошибок

Для `incident_availability` IncidentRelay рассчитывает поля бюджета ошибок.

```text
budget_seconds = window_seconds * (100% - target%)
budget_consumed_seconds = downtime_seconds
budget_remaining_seconds = budget_seconds - budget_consumed_seconds
```

Пример для 30-дневной цели 99.9%:

```text
Window: 30 days = 2,592,000 seconds
Allowed downtime: 0.1% = 2,592 seconds = 43.2 minutes
```

Если простой превышает бюджет, статус SLO становится `breached`.

## Окна обслуживания

Когда включён `exclude_maintenance`, `incident_availability` вычитает окна обслуживания из учёта простоя. Это предотвращает потребление бюджета ошибок плановым обслуживанием.

SLO задержки и подсчёта инцидентов в настоящее время используют группы алертов, соответствующие фильтру их SLI. Они не исключают обслуживание из знаменателя.

## Примеры UI

### Пример 1: задержка ACK для критических алертов

Создайте SLI:

```text
Name: Critical alert acknowledgement latency
SLI type: Alert acknowledgement latency
Source: IncidentRelay alert groups
Severity: critical
Enabled: yes
```

Создайте SLO:

```text
SLI: Critical alert acknowledgement latency
Name: 95% critical alerts acknowledged within 15 minutes
Target: 95%
Threshold: 15 minutes
Window: 30 days
Include open alerts: yes
Enabled: yes
```

### Пример 2: доступность на основе инцидентов

Создайте SLI:

```text
Name: P1/P2 incident availability
SLI type: Incident-based availability
Source: IncidentRelay alert groups
Priority scope: P1, P2
Enabled: yes
```

Создайте SLO:

```text
SLI: P1/P2 incident availability
Name: 99.9% P1/P2 incident-based availability over 30 days
Target: 99.9%
Window: 30 days
Exclude maintenance: yes
Include open alerts: yes
Enabled: yes
```

### Пример 3: максимальное число критических инцидентов

Создайте SLI:

```text
Name: Critical incident count
SLI type: Impact incident count
Source: IncidentRelay alert groups
Severity: critical
Enabled: yes
```

Создайте SLO:

```text
SLI: Critical incident count
Name: No more than 3 critical incidents over 30 days
Max incidents: 3
Window: 30 days
Include open alerts: yes
Enabled: yes
```

## Обзор API

### SLI

```text
GET    /api/services/<service_id>/slis
POST   /api/services/<service_id>/slis
PUT    /api/services/slis/<sli_id>
DELETE /api/services/slis/<sli_id>
```

### SLO

```text
GET    /api/services/<service_id>/slos
POST   /api/services/<service_id>/slos
PUT    /api/services/slos/<slo_id>
DELETE /api/services/slos/<slo_id>
```

### Агрегатные эндпоинты

```text
GET /api/services/sli-slo
GET /api/services/sli-slo/analytics
```

`/api/services/sli-slo/analytics` обеспечивает работу:

```text
Services → Analytics → SLI / SLO health
```

## Пример API: создание SLI и SLO задержки ACK

Создайте SLI:

```http
POST /api/services/42/slis
Content-Type: application/json
```

```json
{
  "slug": "critical-ack-latency",
  "name": "Critical alert acknowledgement latency",
  "description": "How quickly critical alert groups are acknowledged.",
  "sli_type": "alert_ack_latency",
  "source": "incidentrelay_alert_groups",
  "severity": "critical",
  "enabled": true
}
```

Создайте SLO:

```http
POST /api/services/42/slos
Content-Type: application/json
```

```json
{
  "sli_id": 10,
  "name": "95% critical alerts acknowledged within 15 minutes",
  "description": "Critical alerts should be acknowledged quickly by the on-call team.",
  "target_percent_basis_points": 9500,
  "threshold_seconds": 900,
  "window_days": 30,
  "include_open_alerts": true,
  "enabled": true
}
```

Ответ на создание SLO включает первую оценку. Последующие вызовы списка, сведений и аналитики обновляют оценку.

## Пример API: создание SLO доступности инцидентов

Создайте SLI:

```json
{
  "slug": "critical-incident-availability",
  "name": "Critical incident availability",
  "sli_type": "incident_availability",
  "source": "incidentrelay_alert_groups",
  "severity": "critical",
  "enabled": true
}
```

Создайте SLO:

```json
{
  "sli_id": 11,
  "name": "99.9% incident-based availability over 30 days",
  "target_percent_basis_points": 9990,
  "window_days": 30,
  "exclude_maintenance": true,
  "include_open_alerts": true,
  "enabled": true
}
```

## Пример API: создание SLO подсчёта инцидентов

Создайте SLI:

```json
{
  "slug": "critical-incident-count",
  "name": "Critical incident count",
  "sli_type": "incident_count",
  "source": "incidentrelay_alert_groups",
  "severity": "critical",
  "enabled": true
}
```

Создайте SLO:

```json
{
  "sli_id": 12,
  "name": "No more than 3 critical incidents over 30 days",
  "threshold_count": 3,
  "window_days": 30,
  "include_open_alerts": true,
  "enabled": true
}
```

## Payload сведений о сервисе

`GET /api/services/<service_id>/details` включает блок SLI/SLO для модального окна сведений о сервисе.

Ожидаемое поле верхнего уровня:

```json
{
  "sli_slo": {
    "slis": [],
    "slos": [],
    "measurements": [],
    "summary": {
      "total": 0,
      "met": 0,
      "at_risk": 0,
      "breached": 0,
      "no_data": 0
    }
  }
}
```

## Payload аналитики

`GET /api/services/sli-slo/analytics` возвращает последние измерения SLO для текущей читаемой области сервисов.

Пример структуры:

```json
{
  "summary": {
    "total": 4,
    "met": 2,
    "at_risk": 1,
    "breached": 1,
    "no_data": 0,
    "services": 3
  },
  "items": [
    {
      "service_id": 42,
      "service_name": "Payments API",
      "sli_id": 10,
      "sli_name": "Critical alert acknowledgement latency",
      "sli_type": "alert_ack_latency",
      "slo_id": 20,
      "slo_name": "95% critical alerts acknowledged within 15 minutes",
      "window_days": 30,
      "target_percent": 95.0,
      "value_percent": 97.2,
      "status": "met",
      "good_count": 35,
      "bad_count": 1,
      "pending_count": 0,
      "total_count": 36,
      "measured_at": "2026-06-28T18:00:00Z"
    }
  ]
}
```

## События хронологии

Действия создания, обновления и удаления SLI/SLO публикуют события хронологии сервиса через адаптер событий каталога сервисов.

События:

```text
service_sli.created
service_sli.updated
service_sli.deleted
service_slo.created
service_slo.updated
service_slo.deleted
```

Категория:

```text
sli_slo
```

Эти события видны здесь:

```text
Services → service row → Details → Timeline
```

## Текущие ограничения

IncidentRelay в настоящее время поддерживает встроенные SLI на основе групп алертов и учёта инцидентов/статусов. Он пока не рассчитывает следующие внешние SLI:

```text
Prometheus latency
request success rate
error rate
synthetic availability
real user monitoring availability
tracing-based SLIs
```

Их можно добавить позже как новые источники SLI и ветви оценщика без изменения базовой модели API SLI/SLO.
