---
title: Systemd Installation
description: Quick start installation with systemd services
---

# Systemd Installation

This guide describes a classic Linux installation with systemd.

It starts two services:

```text
incidentrelay.service        # HTTP API, UI, webhooks
incidentrelay-scheduler.service  # reminders, escalations, periodic jobs
```

The scheduler must run as a separate service. Do not start it inside every web worker.

## Recommended paths

```text
/var/www/incidentrelay                     # application directory
/var/www/incidentrelay/venv                # Python virtual environment
/etc/incidentrelay/incidentrelay.conf      # configuration file
/var/lib/incidentrelay                     # SQLite database or runtime state
/var/log/incidentrelay                     # logs
/usr/local/lib/incidentrelay/voice_providers # custom voice providers
```

IncidentRelay reads the configuration path from:

```text
INCIDENTRELAY_CONFIG_FILE
```

The old `ONCALL_CONFIG_FILE` variable should not be used.

## 1. Install system packages

Debian / Ubuntu example:

```bash
sudo apt-get update
sudo apt-get install -y \
  git \
  python3 \
  python3-venv \
  python3-pip \
  build-essential \
  curl
```

If you use PostgreSQL, also install PostgreSQL build/runtime dependencies:

```bash
sudo apt-get install -y libpq-dev
```

## 2. Clone IncidentRelay

```bash
sudo mkdir -p /var/www
sudo git clone https://github.com/roxy-wi/IncidentRelay.git /var/www/incidentrelay
cd /var/www/incidentrelay
```

## 3. Create a virtual environment

```bash
sudo python3 -m venv /var/www/incidentrelay/venv
sudo /var/www/incidentrelay/venv/bin/pip install --upgrade pip
sudo /var/www/incidentrelay/venv/bin/pip install -r /var/www/incidentrelay/requirements.txt
sudo /var/www/incidentrelay/venv/bin/pip install gunicorn
```

For PostgreSQL installations:

```bash
sudo /var/www/incidentrelay/venv/bin/pip install psycopg2-binary
```

## 4. Create directories

```bash
sudo mkdir -p /etc/incidentrelay
sudo mkdir -p /var/lib/incidentrelay
sudo mkdir -p /var/log/incidentrelay
sudo mkdir -p /usr/local/lib/incidentrelay/voice_providers
```

Set ownership:

```bash
sudo chown -R www-data:www-data /var/www/incidentrelay
sudo chown -R www-data:www-data /var/lib/incidentrelay
sudo chown -R www-data:www-data /var/log/incidentrelay
```

Custom voice provider files are executable Python code. Keep this directory writable only by administrators:

```bash
sudo chown root:root /usr/local/lib/incidentrelay/voice_providers
sudo chmod 755 /usr/local/lib/incidentrelay/voice_providers
```

## 5. Create config

Create:

```text
/etc/incidentrelay/incidentrelay.conf
```

SQLite example:

```ini
[main]
log_level = INFO
log_file = /var/log/incidentrelay/incidentrelay.log

[server]
host = 0.0.0.0
port = 8080
public_base_url = http://localhost:8080

[database]
type = sqlite
path = /var/lib/incidentrelay/incidentrelay.db

[sqlite]
wal = true
busy_timeout = 5000

[voice]
provider = stub
providers_dir = /usr/local/lib/incidentrelay/voice_providers
callback_secret =
```

For production behind Nginx or HAProxy, set `public_base_url` to the real external URL:

```ini
[server]
public_base_url = https://incidentrelay.example.com
```

`public_base_url` is used for generated links and callback URLs.

## 6. Install systemd services

Copy service files:

```bash
sudo cp /var/www/incidentrelay/systemd/incidentrelay.service /etc/systemd/system/
sudo cp /var/www/incidentrelay/systemd/incidentrelay-scheduler.service /etc/systemd/system/
```

Reload systemd:

```bash
sudo systemctl daemon-reload
```

## 7. Run migrations

```bash
cd /var/www/incidentrelay
sudo -u www-data \
  INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf \
  /var/www/incidentrelay/venv/bin/python app/migrate.py migrate
```

## 8. Create the first admin user

```bash
cd /var/www/incidentrelay
sudo -u www-data \
  INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf \
  /var/www/incidentrelay/venv/bin/python manage.py create-admin \
    --username admin \
    --password 'change-me-123' \
    --email admin@example.com
```

## 9. Start services

```bash
sudo systemctl enable incidentrelay
sudo systemctl enable incidentrelay-scheduler

sudo systemctl start incidentrelay
sudo systemctl start incidentrelay-scheduler
```

Check status:

```bash
sudo systemctl status incidentrelay
sudo systemctl status incidentrelay-scheduler
```

Open:

```text
http://SERVER_IP:8080/login
```

## 10. Logs

Web logs:

```bash
journalctl -u incidentrelay -f
```

Scheduler logs:

```bash
journalctl -u incidentrelay-scheduler -f
```

Application log file:

```bash
tail -f /var/log/incidentrelay/incidentrelay.log
```

## Systemd service files

### Web service

```ini
[Unit]
Description=IncidentRelay Web service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple

User=www-data
Group=www-data

WorkingDirectory=/var/www/incidentrelay

Environment=INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
Environment=INCIDENTRELAY_SERVICE=web
Environment=PYTHONUNBUFFERED=1

ExecStart=/var/www/incidentrelay/venv/bin/gunicorn \
  --bind 0.0.0.0:8080 \
  --workers 1 \
  --threads 4 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile - \
  "app:create_app()"

Restart=always
RestartSec=5

KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

### Scheduler service

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

## Important scheduler note

The web process must not start the scheduler automatically.

Correct model:

```text
web service:
  create_app()
  no scheduler autostart

scheduler service:
  create_app()
  start_scheduler()
```

If scheduler startup currently happens inside `create_app()`, guard it:

```python
import os

if os.getenv("INCIDENTRELAY_SERVICE") == "scheduler":
    start_scheduler()
```

If `app.scheduler_worker` starts the scheduler explicitly, it is usually better to remove automatic scheduler startup from `create_app()` completely.

## Production with reverse proxy

For production, it is usually better to bind Gunicorn to localhost and expose IncidentRelay through Nginx or HAProxy with HTTPS.

Change web service `ExecStart`:

```ini
ExecStart=/var/www/incidentrelay/venv/bin/gunicorn \
  --bind 127.0.0.1:8080 \
  --workers 1 \
  --threads 4 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile - \
  "app:create_app()"
```

Then set:

```ini
[server]
public_base_url = https://incidentrelay.example.com
```

## PostgreSQL variant

For larger installations, use PostgreSQL.

Example config section:

```ini
[database]
type = postgresql
host = 127.0.0.1
port = 5432
name = incidentrelay
user = incidentrelay
password = change-me
```

For PostgreSQL, increase web workers if needed:

```ini
ExecStart=/var/www/incidentrelay/venv/bin/gunicorn \
  --bind 127.0.0.1:8080 \
  --workers 4 \
  --threads 4 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile - \
  "app:create_app()"
```

For SQLite, keep `--workers 1`.

## Update IncidentRelay

```bash
cd /var/www/incidentrelay
sudo systemctl stop incidentrelay-scheduler
sudo systemctl stop incidentrelay

sudo git pull
sudo /var/www/incidentrelay/venv/bin/pip install -r requirements.txt

sudo -u www-data \
  INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf \
  /var/www/incidentrelay/venv/bin/python app/migrate.py migrate

sudo systemctl start incidentrelay
sudo systemctl start incidentrelay-scheduler
```

## Troubleshooting

### Config file not found

Check:

```bash
systemctl show incidentrelay --property=Environment
systemctl show incidentrelay-scheduler --property=Environment
```

Check file exists:

```bash
ls -l /etc/incidentrelay/incidentrelay.conf
```

### Permission denied for SQLite database

Check permissions:

```bash
sudo -u www-data test -w /var/lib/incidentrelay
sudo -u www-data test -r /etc/incidentrelay/incidentrelay.conf
```

### Reminders are duplicated

Check that the scheduler is not running inside web workers and that only one scheduler service is active:

```bash
systemctl status incidentrelay-scheduler
ps aux | grep scheduler
```

### Service does not start after code update

Check logs:

```bash
journalctl -u incidentrelay -n 100 --no-pager
journalctl -u incidentrelay-scheduler -n 100 --no-pager
```
