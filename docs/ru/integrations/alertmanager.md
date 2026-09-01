---
title: Интеграция с Alertmanager
description: Настройка маршрута для Prometheus Alertmanager и обработка payload.
---

# Интеграция с Alertmanager

Alertmanager — это входящий источник алертов.

Эндпоинт:

```text
POST /api/integrations/alertmanager
```

Аутентификация использует токен приёма маршрута:

```text
Authorization: Bearer ROUTE_TOKEN
```

## Настройка маршрута

Создайте маршрут с:

```text
Source: alertmanager
```

Привяжите хотя бы один канал уведомлений и скопируйте токен приёма маршрута в конфигурацию вебхука Alertmanager.


## Пример конфигурации Alertmanager

Минимальный receiver в `alertmanager.yml` может отправлять в IncidentRelay как firing, так и resolved уведомления:

```yaml
route:
  receiver: incidentrelay
  group_by:
    - alertname
    - cluster
    - service
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

receivers:
  - name: incidentrelay
    webhook_configs:
      - url: https://incidentrelay.example.com/api/integrations/alertmanager
        send_resolved: true
        http_config:
          authorization:
            type: Bearer
            credentials_file: /etc/alertmanager/secrets/incidentrelay-route-token
```

Файл credentials должен содержать только токен маршрута IncidentRelay, без префикса `Bearer `. Хранить токен в подключаемом secret-файле предпочтительнее, чем коммитить его в `alertmanager.yml`.

Для небольшой тестовой инсталляции токен можно указать непосредственно в конфигурации:

```yaml
receivers:
  - name: incidentrelay
    webhook_configs:
      - url: https://incidentrelay.example.com/api/integrations/alertmanager
        send_resolved: true
        http_config:
          authorization:
            type: Bearer
            credentials: ROUTE_TOKEN
```

`send_resolved: true` важен: без resolved-уведомлений IncidentRelay не сможет автоматически закрывать соответствующий алерт после восстановления в Alertmanager.

Если в IncidentRelay должна уходить только часть дерева маршрутизации Alertmanager, направьте в receiver только нужную ветку вместо использования его как receiver по умолчанию:

```yaml
route:
  receiver: default-receiver
  routes:
    - receiver: incidentrelay
      matchers:
        - team="infra"
        - environment="production"
```

После изменения конфигурации проверьте её перед reload Alertmanager:

```bash
amtool check-config /etc/alertmanager/alertmanager.yml
```

## Назначение сервиса

После того как маршрут сопоставит входящий алерт, IncidentRelay может привязать алерт к сервису.

Есть два способа:

1. Выбрать сервис по умолчанию на маршруте.
2. Настроить правила сопоставления сервисов.

Используйте сервис по умолчанию, когда все алерты через маршрут относятся к одной системе. Используйте правила сопоставления сервисов, когда один маршрут получает алерты для нескольких систем.

Пример правила сопоставления сервиса для RabbitMQ:

```json
{
  "labels": {
    "job": "RabbitMQ",
    "rabbitmq": {
      "op": "regex",
      "value": "^rabbitmq-cloud$"
    }
  }
}
```

Это может привязать совпадающие алерты к сервису `RabbitMQ Cloud`.

## Пример payload

```json
{
  "status": "firing",
  "externalURL": "https://alertmanager.example.com",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "RabbitMQClusterPartition",
        "severity": "critical",
        "instance": "rabbit-1",
        "team": "infra",
        "job": "RabbitMQ",
        "rabbitmq": "rabbitmq-cloud"
      },
      "annotations": {
        "summary": "RabbitMQ cluster partition detected",
        "description": "Erlang distribution link is not healthy",
        "event_link": "https://grafana.example.com/d/rabbitmq/rabbitmq?viewPanel=12",
        "runbook_url": "https://wiki.example.com/runbooks/rabbitmq-cluster-partition"
      },
      "generatorURL": "https://prometheus.example.com/graph?g0.expr=erlang_vm_dist_node_state",
      "fingerprint": "rabbitmq-cloud-partition-rabbit-1"
    }
  ]
}
```

`generatorURL` — это стандартная для Alertmanager ссылка на источник, ведущая к выражению, которое сгенерировало алерт. IncidentRelay использует её как `event_link`, если более конкретная ссылка не указана в аннотациях.

IncidentRelay также поддерживает следующие псевдонимы аннотаций для ссылки на исходное событие:

```text
event_link
event_url
alert_url
source_url
dashboard_url
panel_url
runbook_url
```

Первое непустое значение сохраняется в `labels.event_link` и предоставляется как `alert.event_link` в ответе API алертов.

## Совместимость с Grafana Alerting

Вебхуки алертов, управляемых Grafana, могут включать такие поля, как `dashboardURL`, `panelURL` и `silenceURL`.

`dashboardURL` и `panelURL` можно использовать как ссылки на исходное событие. `silenceURL` не используется как `event_link`, потому что она указывает на действие заглушки (silence), а не на исходное событие или дашборд. При наличии она должна сохраняться отдельно как `labels.silence_url`.

## Нормализованные поля

| Поле IncidentRelay | Источник |
|---|---|
| `source` | `alertmanager` |
| `team_slug` | `labels.team`, `labels.oncall_team` или верхнеуровневое `team` |
| `external_id` | `fingerprint` или `labels.alertname` |
| `title` | `annotations.summary`, затем `labels.alertname` |
| `message` | `annotations.description` или `annotations.message` |
| `severity` | `labels.severity` |
| `labels` | метки элемента алерта плюс вспомогательные метки, такие как `event_link`, `generator_url` и `alertmanager_url` |
| `event_link` | `annotations.event_link`, `annotations.event_url`, `annotations.alert_url`, `annotations.source_url`, `annotations.dashboard_url`, `annotations.panel_url`, `annotations.runbook_url`, `generatorURL`, `dashboardURL` или `panelURL` |
| `status` | статус элемента или верхнеуровневый статус, по умолчанию `firing` |

## События разрешения

Используйте тот же fingerprint и данные группировки для событий разрешения (resolved).

Это позволяет IncidentRelay обновлять существующий алерт вместо создания нового.
