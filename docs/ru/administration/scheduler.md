---
title: Планировщик
description: Запуск планировщика напоминаний и эскалаций IncidentRelay отдельно от веб-процесса
---

# Планировщик

IncidentRelay использует задачи планировщика для напоминаний, эскалаций и периодической логики обслуживания.

Планировщик должен работать как отдельный процесс и не должен запускаться внутри каждого веб-воркера.

## Зачем отдельный процесс планировщика?

Не запускайте задачи планировщика внутри нескольких воркеров Gunicorn.

Плохая модель:

```text
gunicorn -w 4
├── worker 1 -> scheduler
├── worker 2 -> scheduler
├── worker 3 -> scheduler
└── worker 4 -> scheduler
```

Это может дублировать напоминания и эскалации.

Рекомендуемая модель:

```text
incidentrelay             # HTTP API, UI, incoming webhooks
incidentrelay-scheduler   # one scheduler process
```

## Интервал планировщика и интервал напоминаний

Существует два разных интервала:

| Настройка | Значение |
|---|---|
| Интервал пробуждения планировщика | Как часто планировщик проверяет наличие работы |
| Интервал напоминаний ротации | Как часто конкретный алерт должен получать уведомления-напоминания |

Правила интервала напоминаний ротации:

```text
0       disables reminders for that rotation
>= 60   sends reminders at that interval in seconds
1..59   invalid
```

Не используйте глобальный резервный интервал времени выполнения для reminder-after, когда ротации требуют явного интервала напоминаний.


## Retention данных

IncidentRelay 2.1 запускает один периодический retention job для истории alerts, Explain Trace и Event Orchestration. Периодичность настраивается в отдельной секции:

```ini
[retention]
alert_days = 30
cleanup_interval_seconds = 86400
batch_size = 500
```

`explain_trace_days` и `orchestration_execution_days` наследуют `alert_days`, если не заданы явно. Job использует тот же distributed database lock, что и остальные scheduler jobs. Подробнее: [Политика хранения данных](data-retention.md).

## Переменные окружения

Процесс планировщика должен использовать:

```text
INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
INCIDENTRELAY_SERVICE=scheduler
PYTHONUNBUFFERED=1
```

Веб-процесс должен использовать:

```text
INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
INCIDENTRELAY_SERVICE=web
PYTHONUNBUFFERED=1
```

## Автономный воркер планировщика

Точка входа:

```text
python -m app.scheduler_worker
```

## Сервис systemd

Пакеты RPM должны устанавливать этот сервис автоматически. Для ручных установок создайте:

```text
/etc/systemd/system/incidentrelay-scheduler.service
```

Пример с virtualenv:

```ini
[Unit]
Description=IncidentRelay Scheduler service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/var/www/incidentrelay
Environment=INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
Environment=INCIDENTRELAY_SERVICE=scheduler
Environment=PYTHONUNBUFFERED=1
ExecStart=/var/www/incidentrelay/venv/bin/python -m app.scheduler_worker
Restart=always
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

Применить изменения:

```bash
sudo systemctl daemon-reload
sudo systemctl enable incidentrelay-scheduler
sudo systemctl restart incidentrelay-scheduler
sudo systemctl status incidentrelay-scheduler
```

Логи:

```bash
journalctl -u incidentrelay-scheduler -f
```

## Устранение неполадок

### Напоминания дублируются

Проверьте, что запущен только один процесс планировщика:

```bash
systemctl status incidentrelay-scheduler
ps aux | grep scheduler
```

Также проверьте, что запуск планировщика не срабатывает автоматически внутри каждого веб-воркера.

### Напоминания продолжают приходить после установки интервала в 0

Проверьте:

1. Алерт использует ожидаемую ротацию.
2. У ротации `reminder_interval_seconds = 0`.
3. Сервис планировщика был перезапущен после изменений кода/конфигурации.
4. Код времени выполнения не откатывается к глобальному значению reminder-after, когда интервал ротации равен `0`.

### Планировщик не может прочитать конфигурацию

Проверьте:

```bash
systemctl show incidentrelay-scheduler --property=Environment
sudo -u www-data test -r /etc/incidentrelay/incidentrelay.conf
```

Для установок RPM используйте пользователя `incidentrelay` вместо `www-data`, если это пользователь сервиса из пакета.

### База данных SQLite заблокирована

SQLite подходит для небольших установок, но у неё есть блокировка на одного писателя. Рекомендуемая конфигурация SQLite:

```ini
[sqlite]
wal = true
busy_timeout = 5000
```

Для большего объёма алертов или нескольких веб-воркеров используйте PostgreSQL.
