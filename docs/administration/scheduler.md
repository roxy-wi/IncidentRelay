---
title: Scheduler
description: Run IncidentRelay reminder and escalation scheduler separately from the web process
---

# Scheduler

IncidentRelay uses scheduler jobs for reminders, escalations and periodic maintenance logic.

The scheduler must run as a separate process and must not be started inside every web worker.

## Why separate scheduler process?

Do not run scheduler jobs inside multiple Gunicorn workers.

Bad model:

```text
gunicorn -w 4
├── worker 1 -> scheduler
├── worker 2 -> scheduler
├── worker 3 -> scheduler
└── worker 4 -> scheduler
```

This may duplicate reminders and escalations.

Recommended model:

```text
incidentrelay             # HTTP API, UI, incoming webhooks
incidentrelay-scheduler   # one scheduler process
```

## Scheduler interval and reminder interval

There are two different intervals:

| Setting | Meaning |
|---|---|
| Scheduler wake-up interval | How often the scheduler checks for work |
| Rotation reminder interval | How often a specific alert should receive reminder notifications |

Rotation reminder interval rules:

```text
0       disables reminders for that rotation
>= 60   sends reminders at that interval in seconds
1..59   invalid
```

Do not use a global runtime fallback for reminder-after when rotations require an explicit reminder interval.


## Data retention job

IncidentRelay 2.1 runs one periodic retention job for alert history, Explain Trace, and Event Orchestration retention. Configure its cadence in the dedicated section:

```ini
[retention]
alert_days = 30
cleanup_interval_seconds = 86400
batch_size = 500
```

`explain_trace_days` and `orchestration_execution_days` inherit `alert_days` when omitted. The job uses the same distributed database-lock mechanism as other scheduler maintenance jobs. See [Data Retention](data-retention.md).

## Environment variables

The scheduler process should use:

```text
INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
INCIDENTRELAY_SERVICE=scheduler
PYTHONUNBUFFERED=1
```

The web process should use:

```text
INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
INCIDENTRELAY_SERVICE=web
PYTHONUNBUFFERED=1
```

## Standalone scheduler worker

Entrypoint:

```text
python -m app.scheduler_worker
```

## systemd service

RPM packages should install this service automatically. For manual installations, create:

```text
/etc/systemd/system/incidentrelay-scheduler.service
```

Example with virtualenv:

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

Apply changes:

```bash
sudo systemctl daemon-reload
sudo systemctl enable incidentrelay-scheduler
sudo systemctl restart incidentrelay-scheduler
sudo systemctl status incidentrelay-scheduler
```

Logs:

```bash
journalctl -u incidentrelay-scheduler -f
```

## Troubleshooting

### Reminders are duplicated

Check that only one scheduler process is running:

```bash
systemctl status incidentrelay-scheduler
ps aux | grep scheduler
```

Also check that scheduler startup is not triggered automatically inside every web worker.

### Reminders keep arriving after setting interval to 0

Check:

1. The alert uses the expected rotation.
2. The rotation has `reminder_interval_seconds = 0`.
3. The scheduler service was restarted after code/config changes.
4. Runtime code does not fall back to a global reminder-after value when the rotation interval is `0`.

### Scheduler cannot read config

Check:

```bash
systemctl show incidentrelay-scheduler --property=Environment
sudo -u www-data test -r /etc/incidentrelay/incidentrelay.conf
```

For RPM installations, use the `incidentrelay` user instead of `www-data` if that is the packaged service user.

### SQLite database is locked

SQLite is suitable for small installations, but it has one writer lock. Recommended SQLite config:

```ini
[sqlite]
wal = true
busy_timeout = 5000
```

For higher alert volume or multiple web workers, use PostgreSQL.
