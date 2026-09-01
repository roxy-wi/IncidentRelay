# Nagios Core / Nagios XI

IncidentRelay принимает уведомления о хостах и сервисах из Nagios Core и Nagios XI через:

```text
POST /api/integrations/nagios
```

Создайте Route с источником **Nagios** и используйте его intake token как `Authorization: Bearer`.

## Жизненный цикл

| Уведомление Nagios | IncidentRelay |
|---|---|
| `PROBLEM` | firing alert |
| `RECOVERY` или состояние `OK` / `UP` | resolved alert |
| `ACKNOWLEDGEMENT` | ACK соответствующей группы IncidentRelay |
| flapping / downtime / custom | принимаются и игнорируются |

Для host alert ключ дедупликации строится по хосту, для service alert — по хосту и описанию сервиса. Поэтому recovery обновляет исходный alert, а не создаёт новый.

## Рекомендуемый sender

В репозитории есть `examples/nagios/incidentrelay_notify.py`. Скрипт использует только стандартную библиотеку Python и безопасно кодирует значения Nagios macros в JSON, включая кавычки и многострочный plugin output.

```bash
install -m 0755 examples/nagios/incidentrelay_notify.py \
  /usr/local/nagios/libexec/incidentrelay_notify.py
```

URL и intake token удобно хранить в `resource.cfg` в свободных `$USERn$` macros:

```text
$USER10$=https://incidentrelay.example.com/api/integrations/nagios
$USER11$=YOUR_ROUTE_INTAKE_TOKEN
```

### Notification command

Nagios экспортирует большинство стандартных macros для notification scripts как переменные окружения `NAGIOS_*`. Встроенный sender читает их напрямую, поэтому plugin output не подставляется в shell command line. `$USERn$` используются только для контролируемых значений URL/token.

```text
define command {
    command_name notify-by-incidentrelay
    command_line /usr/bin/python3 /usr/local/nagios/libexec/incidentrelay_notify.py --url '$USER10$' --token '$USER11$'
}
```

Используйте `notify-by-incidentrelay` одновременно как host и service notification command для нужных contacts/contact groups. В Nagios XI ту же команду можно создать через **Core Config Manager → Commands**.

Рекомендуем также оставить включённой очистку Nagios macros через `illegal_macro_output_chars`.

## Пример JSON

```bash
curl -X POST 'https://incidentrelay.example.com/api/integrations/nagios' \
  -H 'Authorization: Bearer ROUTE_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "notification_type": "PROBLEM",
    "host_name": "db01",
    "host_address": "10.10.20.15",
    "service_description": "Disk Usage",
    "service_state": "CRITICAL",
    "service_output": "/var заполнен на 96%"
  }'
```

Normalizer добавляет matcher-friendly labels: `nagios_host`, `nagios_service`, `nagios_state`, `nagios_notification_type`, `nagios_object_type`.
