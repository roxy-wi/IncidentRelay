---
title: Интеграция с LibreNMS
description: Приём алертов LibreNMS через API Transport и их нормализация в инциденты IncidentRelay.
---

# Интеграция с LibreNMS

IncidentRelay может получать алерты LibreNMS через LibreNMS **API Transport** и нормализовать их в обычные инциденты IncidentRelay.

LibreNMS API Transport должен отправлять JSON payload на:

```http
POST /api/integrations/librenms
```

Токен приёма маршрута должен принадлежать маршруту IncidentRelay с:

```text
source = librenms
```

## Поведение

IncidentRelay нормализует каждый payload транспорта LibreNMS в одно событие алерта:

| Поле LibreNMS | Поле IncidentRelay |
|---|---|
| `uid`, `alert_uid`, `id`, `alert_id` | `external_id` |
| `fingerprint` | явный `dedup_key` |
| `title`, `subject`, `rule`, `name` | заголовок алерта |
| `message`, `msg`, `description`, `alert_notes` | сообщение алерта |
| `state`, `status` | статус алерта |
| `severity` | severity алерта |
| `hostname`, `display`, `sysName` | метка `hostname` |
| `device_id` | метка `device_id` |
| `team` | переопределение slug команды IncidentRelay |
| `event_link`, `event_url`, `alert_url`, `source_url`, `device_url` | внешняя ссылка на алерт |
| `librenms_url` + `hostname` или `device_id` | сгенерированная ссылка на устройство LibreNMS |

## Сопоставление статусов

IncidentRelay трактует следующие состояния/статусы LibreNMS как разрешённые:

```text
0, ok, clear, cleared, recover, recovery, recovered, resolve, resolved, closed
```

Любое другое состояние/статус трактуется как firing.

Примеры:

| Состояние LibreNMS | Статус IncidentRelay |
|---|---|
| `1` | `firing` |
| `2` | `firing` |
| `alert` | `firing` |
| `0` | `resolved` |
| `ok` | `resolved` |
| `recovered` | `resolved` |

## Сопоставление severity

| Severity LibreNMS | Severity IncidentRelay |
|---|---|
| `critical`, `crit`, `error`, `err`, `high` | `critical` |
| `warning`, `warn`, `medium` | `warning` |
| `info`, `informational`, `notice`, `low`, `ok`, `clear`, `normal` | `info` |
| неизвестное непустое значение | исходное значение |
| пустое значение | `info` |

## Дедупликация

IncidentRelay использует первое доступное значение из этого списка как `external_id`:

```text
uid, alert_uid, id, alert_id
```

Если предоставлен `fingerprint`, он используется как явный ключ дедупликации.

Если явного fingerprint нет, IncidentRelay строит стабильный ключ дедупликации из:

```text
source=librenms
external_id
hostname
rule/name
device_id
```

Для надёжной корреляции firing/recovery настройте LibreNMS отправлять одинаковый `uid` или `id` для событий алерта и восстановления.

## Создание маршрута IncidentRelay

Создайте или обновите маршрут алертов с источником `librenms`.

Пример свойств маршрута:

```json
{
  "name": "LibreNMS",
  "source": "librenms",
  "team_id": 1,
  "matchers": {},
  "group_by": ["hostname", "rule"],
  "enabled": true
}
```

Скопируйте токен приёма маршрута. Он будет использоваться в заголовке `Authorization` LibreNMS API Transport.

## Настройка LibreNMS API Transport

В LibreNMS создайте Alert Transport с типом **API**.

Рекомендуемые настройки:

| Настройка | Значение |
|---|---|
| API Method | `POST` |
| API URL | `https://incidentrelay.example.com/api/integrations/librenms` |
| API Headers | `Authorization=Bearer INCIDENTRELAY_ROUTE_TOKEN` |
| API Headers | `Content-Type=application/json` |
| API Body | JSON-тело из примера ниже |

## Рекомендуемое API Body

Используйте JSON-тело вроде этого в конфигурации LibreNMS API Transport:

```json
{
  "id": "{{ $id }}",
  "uid": "{{ $uid }}",
  "state": "{{ $state }}",
  "severity": "{{ $severity }}",
  "title": "{{ $title }}",
  "message": "{{ $msg }}",
  "hostname": "{{ $hostname }}",
  "display": "{{ $display }}",
  "sysName": "{{ $sysName }}",
  "device_id": "{{ $device_id }}",
  "ip": "{{ $ip }}",
  "os": "{{ $os }}",
  "type": "{{ $type }}",
  "hardware": "{{ $hardware }}",
  "version": "{{ $version }}",
  "location": "{{ $location }}",
  "rule": "{{ $name }}",
  "timestamp": "{{ $timestamp }}",
  "team": "sre",
  "librenms_url": "https://librenms.example.com"
}
```

`team` необязательно. Используйте его только когда хотите, чтобы payload переопределял маршрутизацию на конкретный slug команды IncidentRelay.

`librenms_url` необязательно. Когда оно задано, IncidentRelay может сгенерировать ссылку на устройство LibreNMS из `librenms_url` и `hostname` или `device_id`.

## Пользовательские метки

Вы можете прикрепить дополнительные метки с помощью объекта `labels`:

```json
{
  "uid": "{{ $uid }}",
  "state": "{{ $state }}",
  "severity": "{{ $severity }}",
  "title": "{{ $title }}",
  "message": "{{ $msg }}",
  "hostname": "{{ $hostname }}",
  "labels": {
    "environment": "prod",
    "service": "network",
    "source_system": "librenms"
  }
}
```

IncidentRelay копирует `labels` в нормализованные метки алерта, а также добавляет нормализованные метки LibreNMS, такие как:

```text
hostname
device_id
ip
os
type
hardware
version
location
rule
librenms_id
librenms_uid
librenms_state
librenms_timestamp
librenms_severity
event_link
```

## Пример payload firing

```json
{
  "id": "12345",
  "uid": "lnms-alert-12345",
  "state": "1",
  "severity": "critical",
  "title": "Device down",
  "message": "Device router1 is unreachable",
  "hostname": "router1",
  "device_id": "77",
  "ip": "10.0.0.1",
  "rule": "Device down",
  "timestamp": "2026-06-17 10:00:00",
  "team": "sre",
  "librenms_url": "https://librenms.example.com"
}
```

Нормализованный результат:

```json
{
  "source": "librenms",
  "team_slug": "sre",
  "external_id": "lnms-alert-12345",
  "title": "Device down",
  "message": "Device router1 is unreachable",
  "severity": "critical",
  "status": "firing",
  "labels": {
    "hostname": "router1",
    "device_id": "77",
    "ip": "10.0.0.1",
    "rule": "Device down",
    "event_link": "https://librenms.example.com/device/device=router1/"
  }
}
```

## Пример payload восстановления

Отправьте тот же `uid` или `id`, но установите `state` в значение восстановления:

```json
{
  "id": "12345",
  "uid": "lnms-alert-12345",
  "state": "0",
  "severity": "ok",
  "title": "Device down",
  "message": "Device router1 recovered",
  "hostname": "router1",
  "device_id": "77",
  "rule": "Device down"
}
```

Нормализованный статус:

```json
{
  "status": "resolved"
}
```

## Тест с curl

```bash
curl -X POST "https://incidentrelay.example.com/api/integrations/librenms" \
  -H "Authorization: Bearer INCIDENTRELAY_ROUTE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "12345",
    "uid": "lnms-alert-12345",
    "state": "1",
    "severity": "critical",
    "title": "Device down",
    "message": "Device router1 is unreachable",
    "hostname": "router1",
    "device_id": "77",
    "rule": "Device down",
    "team": "sre",
    "librenms_url": "https://librenms.example.com"
  }'
```

Ожидаемый ответ имеет ту же форму, что и у других входящих интеграций алертов IncidentRelay: запрос должен быть принят и направлен через совпадающий маршрут `librenms`.

## Устранение неполадок

### 401 unauthorized

Проверьте, что заголовок `Authorization` содержит токен приёма маршрута:

```text
Authorization=Bearer INCIDENTRELAY_ROUTE_TOKEN
```

Также проверьте, что токен принадлежит маршруту с:

```text
source = librenms
```

### 400 validation_error

Payload должен содержать хотя бы одно значимое поле идентификации или содержимого, например:

```text
id, uid, alert_id, title, name, rule, message, msg, description, hostname, display, sysName, fingerprint or labels
```

### Восстановление создаёт новый инцидент вместо разрешения старого

Убедитесь, что payload firing и recovery используют одну и ту же стабильную идентичность:

```text
uid or id
```

Не включайте изменяющиеся значения, такие как timestamp, в `fingerprint`.

### Ссылка на событие отсутствует

Отправьте одно из этих полей:

```text
event_link, event_url, alert_url, source_url, device_url
```

Или отправьте `librenms_url` вместе с `hostname` или `device_id`, чтобы IncidentRelay мог сгенерировать ссылку на устройство.
