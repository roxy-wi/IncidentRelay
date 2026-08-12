---
title: Services API
description: Инвентарь сервисов, правила сопоставления, ссылки, runbook'и, влияние и эндпоинты аналитики.
---

# Services API

Эндпоинты управления сервисами доступны по пути:

```text
/api/services
```

Они охватывают:

- сервисы;
- правила сопоставления сервисов;
- ссылки сервисов;
- runbook'и сервисов;
- зависимости сервисов;
- аналитику сервисов;
- влияние сервисов.

Сервисы описывают логическую затронутую систему.

Маршруты отвечают на вопрос, как алерт попал в IncidentRelay, а сервисы отвечают на вопрос, какая система неисправна.

## Общие эндпоинты сервисов

```text
GET /api/services
POST /api/services
GET /api/services/{service_id}
PUT /api/services/{service_id}
DELETE /api/services/{service_id}
```

## Правила сопоставления сервисов

```text
GET /api/services/match-rules
GET /api/services/{service_id}/match-rules
POST /api/services/{service_id}/match-rules
PUT /api/services/match-rules/{rule_id}
DELETE /api/services/match-rules/{rule_id}
```

## Ссылки и runbook'и сервисов

    GET /api/services/links
    GET /api/services/{service_id}/links
    POST /api/services/{service_id}/links
    GET /api/services/runbooks
    GET /api/services/{service_id}/runbooks
    POST /api/services/{service_id}/runbooks

## Зависимости сервисов

    GET /api/services/dependencies
    GET /api/services/{service_id}/dependencies
    POST /api/services/{service_id}/dependencies
    PUT /api/services/dependencies/{dependency_id}
    DELETE /api/services/dependencies/{dependency_id}

Полезная нагрузка зависимости:

    {
      "depends_on_service_id": 2,
      "dependency_type": "hard",
      "criticality": "required",
      "correlation_enabled": true,
      "propagation_delay_seconds": 300,
      "description": "Primary PostgreSQL dependency",
      "enabled": true
    }

Поля:

Имя Тип По умолчанию Описание
`depends_on_service_id` integer required Идентификатор вышестоящего сервиса.
`dependency_type` string `hard` Одно из `hard`, `soft`, `external`, `informational`.
`criticality` string `important` Одно из `required`, `important`, `optional`.
`correlation_enabled` boolean `true` Может ли эта зависимость использоваться для корреляции алертов с учётом зависимостей.
`propagation_delay_seconds` integer `300` Максимальная ожидаемая задержка между связанными группами алертов.
`description` string или null `null` Необязательная человекочитаемая заметка о зависимости.
`enabled` boolean `true` Активна ли зависимость.

`propagation_delay_seconds` ограничивается валидацией API. Используйте короткие окна для синхронных зависимостей и более длинные окна только для отложенного пакетного или основанного на очередях распространения.

## Аналитика и влияние

```text
GET /api/services/analytics
GET /api/services/impact
```

Порядок отображения имён сервисов и команд у потребителей API и в UI:

```text
name -> slug -> "-"
```

## Service impact v2

```text
GET /api/services/impact
GET /api/services/{service_id}/impact
```

Возвращает текущее вычисленное влияние сервиса.

Влияние — это расчёт на определённый момент времени. Оно отвечает на вопросы:

- что затронуто прямо сейчас;
- почему это затронуто;
- какой сервис является первопричиной;
- как распространилось влияние по зависимостям;
- какие нижестоящие сервисы могут быть затронуты этим сервисом.

Параметры запроса:

| Имя | Тип | По умолчанию | Описание |
| --- | --- | --- | --- |
| `team_id` | integer | `null` | Ограничить влияние одной командой. |
| `service_id` | integer | `null` | Вернуть влияние для одного сервиса, при этом всё равно вычисляя читаемый граф зависимостей. |
| `include_disabled` | boolean | `false` | Включить отключённые сервисы. |
| `include_operational` | boolean | `true` | Включить работоспособные сервисы. |
| `include_explanation` | boolean | `true` | Включить человекочитаемое объяснение. |
| `include_root_causes` | boolean | `true` | Включить сервисы-первопричины. |
| `include_blast_radius` | boolean | `true` | Включить нижестоящий радиус поражения. |
| `include_paths` | boolean | `true` | Включить пути зависимостей. |
| `max_depth` | integer | `5` | Глубина обхода зависимостей, ограничивается валидацией. |
| `limit` | integer | `100` | Максимальное количество возвращаемых элементов. |
| `sort` | string | `effective_status` | Одно из `service`, `status`, `effective_status`, `blast_radius`, `criticality`, `tier`. |
| `order` | string | `desc` | `asc` или `desc`. |

Ответ:

```json
{
  "version": 2,
  "items": [
    {
      "service_id": 42,
      "service_slug": "billing-api",
      "service_name": "Billing API",
      "team_id": 7,
      "team_slug": "payments",
      "team_name": "Payments",
      "own_status": "operational",
      "alert_impact_status": "operational",
      "dependency_impact_status": "major_outage",
      "effective_status": "major_outage",
      "primary_reason": "upstream_dependency",
      "open_alert_groups": 0,
      "critical_open_alert_groups": 0,
      "upstream_issues_count": 1,
      "root_causes": [
        {
          "service_id": 10,
          "service_slug": "postgresql-prod",
          "service_name": "PostgreSQL Prod",
          "reason": "alert_group",
          "status": "operational",
          "effective_status": "major_outage",
          "severity": "critical",
          "open_alert_groups": 1,
          "critical_open_alert_groups": 1,
          "path": []
        }
      ],
      "explanation": {
        "primary_reason": "upstream_dependency",
        "primary_source_service_id": 10,
        "primary_source_service_slug": "postgresql-prod",
        "primary_source_service_name": "PostgreSQL Prod",
        "title": "Billing API is impacted by PostgreSQL Prod",
        "message": "The effective status is major_outage because an upstream dependency is unhealthy.",
        "rules": [],
        "paths": []
      },
      "blast_radius": {
        "direct_downstream": 2,
        "transitive_downstream": 5,
        "critical_downstream": 3,
        "tier_1_downstream": 2,
        "affected_downstream": 5,
        "paths": [],
        "cycle_detected": false,
        "depth_limited": false
      },
      "cycle_detected": false,
      "depth_limited": false
    }
  ],
  "summary": {
    "total": 1,
    "affected": 1,
    "critical": 1,
    "by_effective_status": {
      "major_outage": 1
    },
    "cycle_detected": 0,
    "depth_limited": 0
  },
  "filters": {
    "team_id": null,
    "service_id": null,
    "include_disabled": false,
    "include_operational": true,
    "max_depth": 5,
    "limit": 100,
    "sort": "effective_status",
    "order": "desc"
  }
}
```

Важные замечания:

- Impact v2 основан на `AlertGroup`, а не на сырых событиях `Alert`.
- `service_id` фильтрует только возвращаемые элементы. Граф зависимостей по-прежнему вычисляется с использованием читаемых сервисов в области видимости.
- `root_causes` объясняет, где началось влияние.
- `explanation.paths` объясняет, как распространялось влияние.
- `blast_radius` объясняет, какие нижестоящие сервисы могут быть затронуты.

## Service analytics v2

```text
GET /api/services/analytics
```

Возвращает историческую аналитику сервисов за выбранное временное окно.

Аналитика отвечает на вопросы:

- сколько сгруппированных алертов произошло за период;
- сколько сырых алертов было получено;
- какие сервисы «шумные»;
- текущее влияние для каждого сервиса;
- счётчики подавления при обслуживании;
- метрики времени реакции, когда доступны поля с временными метками.

Параметры запроса:

| Имя | Тип | По умолчанию | Описание |
| --- | --- | --- | --- |
| `team_id` | integer | `null` | Ограничить аналитику одной командой. |
| `service_id` | integer | `null` | Вернуть аналитику для одного сервиса, при этом всё равно вычисляя влияние с использованием читаемого графа зависимостей. |
| `days` | integer | `30` | Окно аналитики, `1..365`. |
| `include_disabled` | boolean | `false` | Включить отключённые сервисы. |
| `include_operational` | boolean | `true` | Включить работоспособные сервисы. |
| `include_series` | boolean | `true` | Включить дневные временные ряды. |
| `include_noise` | boolean | `true` | Включить метрики сырых алертов/шума. |
| `include_response` | boolean | `true` | Включить поля MTTA/MTTR, когда доступны. |
| `include_maintenance` | boolean | `true` | Включить счётчики подавления при обслуживании. |
| `include_impact` | boolean | `true` | Включить текущий виджет Impact v2 для каждого сервиса. |
| `limit` | integer | `100` | Максимальное количество возвращаемых элементов. |
| `sort` | string | `open_alert_groups` | Одно из `service`, `open_alert_groups`, `critical_open_alert_groups`, `raw_alerts`, `dedup_ratio`, `mtta`, `mttr`, `blast_radius`. |
| `order` | string | `desc` | `asc` или `desc`. |

Ответ:

```json
{
  "version": 2,
  "window": {
    "days": 30,
    "since": "2026-05-09T00:00:00Z",
    "until": "2026-06-08T00:00:00Z"
  },
  "items": [
    {
      "service_id": 42,
      "service_slug": "billing-api",
      "service_name": "Billing API",
      "team_id": 7,
      "team_slug": "payments",
      "team_name": "Payments",
      "service_status": "operational",
      "service_criticality": "critical",
      "service_environment": "production",
      "service_tier": "tier_1",
      "enabled": true,
      "alert_groups": {
        "total": 12,
        "open": 3,
        "firing": 2,
        "acknowledged": 1,
        "resolved": 8,
        "silenced": 1,
        "critical_open": 1,
        "by_status": {},
        "by_severity": {},
        "first_seen_at": "2026-05-12T10:00:00Z",
        "last_seen_at": "2026-06-08T08:00:00Z"
      },
      "noise": {
        "raw_alerts": 240,
        "alert_groups": 12,
        "dedup_ratio": 20.0,
        "top_alertnames": [
          {
            "alertname": "BillingApiDown",
            "count": 120
          }
        ]
      },
      "response": {
        "acknowledged_groups": 4,
        "resolved_groups": 8,
        "mtta_seconds_avg": null,
        "mtta_seconds_p50": null,
        "mtta_seconds_p95": null,
        "mttr_seconds_avg": null,
        "mttr_seconds_p50": null,
        "mttr_seconds_p95": null
      },
      "maintenance": {
        "windows": 2,
        "suppressed_alert_groups": 5
      },
      "impact": {
        "effective_status": "major_outage",
        "primary_reason": "upstream_dependency",
        "upstream_issues_count": 1,
        "root_causes": 1,
        "blast_radius": {
          "direct_downstream": 2,
          "transitive_downstream": 5,
          "critical_downstream": 3,
          "tier_1_downstream": 2
        }
      },
      "last_alert_at": "2026-06-08T08:00:00Z"
    }
  ],
  "summary": {
    "services": 1,
    "affected_services": 1,
    "open_alert_groups": 3,
    "critical_open_alert_groups": 1,
    "raw_alerts": 240,
    "by_effective_status": {
      "major_outage": 1
    },
    "top_noisy_services": []
  },
  "series": {
    "alert_groups_by_day": [],
    "raw_alerts_by_day": [],
    "impact_by_day": []
  },
  "filters": {
    "team_id": null,
    "service_id": null,
    "days": 30,
    "include_disabled": false,
    "include_operational": true,
    "include_series": true,
    "include_noise": true,
    "include_response": true,
    "include_maintenance": true,
    "include_impact": true,
    "limit": 100,
    "sort": "open_alert_groups",
    "order": "desc"
  }
}
```

Важные замечания:

- Analytics v2 основана на периоде.
- `AlertGroup` используется для сгруппированной операционной аналитики.
- сырой `Alert` используется для шума и объёма сырых алертов.
- Влияние внутри аналитики — это текущий виджет Impact v2, а не историческое влияние.
- `series.impact_by_day` зарезервировано для будущей истории снимков влияния.
