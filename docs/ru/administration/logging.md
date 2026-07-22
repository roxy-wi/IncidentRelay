---
title: Журналирование
description: Расположение журналов IncidentRelay, поля и заметки по устранению неполадок.
---

# Журналирование

IncidentRelay пишет структурированные логи в стиле JSON для приёма алертов, уведомлений, активности планировщика и ошибок.

## Где искать

Установки systemd:

```bash
journalctl -u incidentrelay -f
journalctl -u incidentrelay-scheduler -f
```

Установки RPM используют те же имена сервисов:

```bash
journalctl -u incidentrelay -f
journalctl -u incidentrelay-scheduler -f
journalctl -u incidentrelay-telegram-worker -f
```

Установки Docker:

```bash
docker compose logs -f incidentrelay
docker compose logs -f incidentrelay-scheduler
```

Если настроено журналирование в файл:

```bash
tail -f /var/log/incidentrelay/incidentrelay.log
```

## Полезные поля

Общие поля:

```text
timestamp
level
logger
message
module
function
line
```

Поля алертов и уведомлений:

```text
alert_id
team
route_id
routing_error
channel_id
channel_name
channel_type
event_type
provider
error
```

## Логи уведомлений

`notification sent` означает, что IncidentRelay передал сообщение нижестоящему провайдеру или SMTP-релею без исключения. Это не гарантирует итоговую доставку.

Если пользователь не получил сообщение, проверьте также логи нижестоящего сервиса.
