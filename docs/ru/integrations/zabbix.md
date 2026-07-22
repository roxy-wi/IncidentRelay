---
title: Интеграция с Zabbix
description: Настройка маршрута для входящих алертов Zabbix и формат payload.
---

# Интеграция с Zabbix

Zabbix — это входящий источник алертов.

Эндпоинт:

```text
POST /api/integrations/zabbix
```

Аутентификация использует токен приёма маршрута:

```text
Authorization: Bearer ROUTE_TOKEN
```

## Настройка маршрута

Создайте маршрут с:

```text
Source: zabbix
```

Привяжите хотя бы один канал уведомлений и скопируйте токен приёма маршрута в настройку типа медиа Zabbix или конфигурацию вебхука.

## Назначение сервиса

После того как маршрут сопоставит входящий алерт, IncidentRelay может привязать алерт к сервису.

Есть два способа:

1. Выбрать сервис по умолчанию на маршруте.
2. Настроить правила сопоставления сервисов.

Используйте сервис по умолчанию, когда все алерты через маршрут относятся к одной системе. Используйте правила сопоставления сервисов, когда один маршрут получает алерты для нескольких систем.

Пример правила сопоставления сервиса:

```json
{
  "labels": {
    "service": "cpu",
    "environment": {
      "op": "regex",
      "value": "^(prod|production)$"
    }
  }
}
```

## Пример payload

```json
{
  "status": "firing",
  "event_id": "123456",
  "trigger_id": "98765",
  "event_name": "High CPU load on host1",
  "host": "host1",
  "event_severity": "High",
  "event_status": "PROBLEM",
  "opdata": "CPU load is above 90%",
  "event_tag": "team: infra, service: cpu",
  "tags": [
    {
      "tag": "team",
      "value": "infra"
    },
    {
      "tag": "service",
      "value": "cpu"
    }
  ],
  "event_link": "https://zabbix.example.com/tr_events.php?triggerid=98765&eventid=123456",
  "team": "infra",
  "labels": {
    "host": "host1",
    "service": "cpu",
    "environment": "prod"
  }
}
```

Параметры типа медиа Zabbix могут использовать макросы:

```json
{
  "event_id": "{EVENT.ID}",
  "trigger_id": "{TRIGGER.ID}",
  "event_name": "{EVENT.NAME}",
  "host": "{HOST.NAME}",
  "event_severity": "{EVENT.SEVERITY}",
  "event_status": "{EVENT.STATUS}",
  "opdata": "{EVENT.OPDATA}",
  "event_tag": "{EVENT.TAGS}",
  "tags": "{EVENT.TAGSJSON}",
  "event_link": "{$ZABBIX.URL}/tr_events.php?triggerid={TRIGGER.ID}&eventid={EVENT.ID}",
  "team": "{EVENT.TAGS.oncall_team}"
}
```

`event_link` сохраняется в `labels.event_link` и также предоставляется как `alert.event_link` в ответе API алертов. Оно используется модальным окном деталей алерта для открытия исходного события Zabbix.

`event_tag` сохраняется в `labels.event_tag`. Когда оно содержит теговые данные вроде `team: infra, service: cpu`, IncidentRelay также извлекает отдельные метки, такие как `team` и `service`.

## Обязательное содержимое payload

Payload Zabbix должен содержать достаточно данных для идентификации и описания алерта.

Пустые JSON-объекты должны отклоняться при валидации.

Полезные поля:

```text
event_id
trigger_id
event_name
trigger_name
problem_name
title
subject
message
opdata
event_tag
tags
event_link
fingerprint
```

## Нормализованные поля

| Поле IncidentRelay | Источник |
|---|---|
| `source` | `zabbix` |
| `team_slug` | `team`, `labels.team`, `labels.oncall_team` или разобранные теги Zabbix |
| `external_id` | `event_id`, `eventid`, `trigger_id` или `triggerid` |
| `title` | `title`, `subject`, `event_name`, `problem_name`, `trigger_name`, `labels.alertname`, затем заголовок по умолчанию |
| `message` | `message`, `description` или `opdata` |
| `severity` | нормализовано из `severity`, `event_severity`, `trigger_severity` или `labels.severity` |
| `labels` | `labels`, разобранные `tags`, разобранный `event_tag`, плюс вспомогательные метки, такие как `host`, `event_name`, `trigger_name`, `zabbix_severity` и `event_link` |
| `event_link` | `event_link`, `event_url`, `problem_url`, `trigger_url`, `labels.event_link` или собранная из `zabbix_url` и `event_id` |
| `status` | `status` или `event_status`, по умолчанию `firing` |

Значения severity Zabbix нормализуются для маршрутизации и фильтрации в IncidentRelay:

| Severity Zabbix | Severity IncidentRelay |
|---|---|
| `Disaster` | `critical` |
| `High` | `critical` |
| `Average` | `warning` |
| `Warning` | `warning` |
| `Information` | `info` |
| `Not classified` | `info` |

Исходное значение severity Zabbix сохраняется в `labels.zabbix_severity`.
