---
title: Azure Monitor
description: Отправка уведомлений Azure Monitor Common Alert Schema в IncidentRelay через Webhook в Action Group.
---

# Интеграция Azure Monitor

IncidentRelay принимает уведомления **Azure Monitor Common Alert Schema** через отдельный входящий маршрут.

Endpoint:

```text
POST /api/integrations/azure-monitor
```

Поддерживается только Common Alert Schema. Legacy-схемы Azure Monitor намеренно отклоняются, чтобы lifecycle, severity и routing оставались однозначными.

## Создание маршрута IncidentRelay

Создайте маршрут:

```text
Source: Azure Monitor
```

Группировка по умолчанию:

```json
["azure_alert_id"]
```

Сохраните маршрут и сразу скопируйте сгенерированный webhook URI. В URI встроены HTTP Basic credentials:

```text
https://incidentrelay:<ROUTE_TOKEN>@incidentrelay.example.com/api/integrations/azure-monitor
```

IncidentRelay использует фиксированный username `incidentrelay`, а intake token маршрута — как пароль Basic auth. Для Logic Apps, curl и других клиентов, умеющих задавать custom headers, тот же token можно передавать как `Authorization: Bearer`.

## Настройка Azure Monitor Action Group

В Azure Monitor создайте или отредактируйте **Action Group** и добавьте действие **Webhook**.

Укажите webhook URI, который показал IncidentRelay, и включите **Common Alert Schema** для этого действия.

Не выбирайте **Secure webhook** для этой схемы: Secure webhook использует Microsoft Entra ID, а эта интеграция аутентифицирует обычный Webhook через HTTP Basic credentials в URI.

Common Alert Schema включается отдельно на уровне каждого action.

## Lifecycle

IncidentRelay преобразует `data.essentials.monitorCondition` так:

| Azure Monitor | IncidentRelay |
|---|---|
| `Fired` | `firing` |
| `Resolved` | `resolved` |

Основной deduplication key — `alertId`. Благодаря этому `Resolved` обновляет уже существующий алерт IncidentRelay.

Если `alertId` отсутствует, используются `originAlertId`, а затем стабильный вычисляемый ключ.

## Severity

| Azure Monitor | IncidentRelay |
|---|---|
| `Sev0` | `critical` |
| `Sev1` | `high` |
| `Sev2` | `medium` |
| `Sev3` | `warning` |
| `Sev4` | `info` |

## Labels и routing

IncidentRelay добавляет метаданные Azure в labels:

```text
azure_alert_id
azure_alert_rule
azure_alert_rule_id
azure_origin_alert_id
azure_monitor_condition
azure_severity
azure_signal_type
azure_monitoring_service
azure_target_resource_id
azure_configuration_item
azure_resource_group
azure_resource_type
azure_subscription_id
event_link
```

Значения из `data.customProperties` также становятся matcher-friendly labels. Рекомендуется передавать там routing metadata, например:

```json
{
  "team": "sre",
  "service": "checkout",
  "environment": "production"
}
```

Custom property `team` или `oncall_team` может участвовать в стандартном выборе команды.

## Тестовый запрос

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/azure-monitor' \
  -H 'Content-Type: application/json' \
  -u 'incidentrelay:ROUTE_TOKEN' \
  -d '{
    "schemaId": "azureMonitorCommonAlertSchema",
    "data": {
      "essentials": {
        "alertId": "/subscriptions/example/providers/Microsoft.AlertsManagement/alerts/example-1",
        "alertRule": "Checkout API latency",
        "severity": "Sev1",
        "signalType": "Metric",
        "monitorCondition": "Fired",
        "monitoringService": "Platform",
        "configurationItems": ["checkout-api"],
        "description": "p95 latency exceeded 2 seconds"
      },
      "customProperties": {
        "team": "sre",
        "service": "checkout",
        "environment": "production"
      }
    }
  }'
```

Для проверки закрытия отправьте тот же `alertId` с:

```json
"monitorCondition": "Resolved"
```

## Диагностика

- `401 Route intake token is required`: проверьте URI в Action Group и username `incidentrelay`.
- `400 Route source must be azure_monitor`: credential относится к маршруту другого source.
- `400 Azure Monitor Common Alert Schema is required`: включите Common Alert Schema у Webhook action.
- `Fired` и `Resolved` создают разные алерты: проверьте, что Azure передаёт одинаковый `alertId`.
- Не работает route/service matching: проверьте `customProperties` и нормализованные labels в деталях алерта.

Документация Microsoft: [Azure Monitor Common Alert Schema](https://learn.microsoft.com/ru-ru/azure/azure-monitor/alerts/alerts-common-schema) и [Action Groups](https://learn.microsoft.com/ru-ru/azure/azure-monitor/alerts/action-groups).
