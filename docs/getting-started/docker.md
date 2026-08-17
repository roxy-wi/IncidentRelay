---
title: Docker Installation
description: Run IncidentRelay with Docker Compose
---

# Docker Installation

Docker Compose is the fastest way to run IncidentRelay for testing, demos and simple self-hosted deployments.

The default Compose setup starts:

```text
incidentrelay             # HTTP API, UI, incoming webhooks
incidentrelay-scheduler   # reminders, escalations, periodic jobs
```

PostgreSQL is optional. SQLite is suitable for small installations and quick starts.

## Default architecture

```text
Docker Compose
├── incidentrelay
│   └── Gunicorn + Flask application
├── incidentrelay-scheduler
│   └── standalone scheduler worker
└── incidentrelay-data
    └── SQLite database volume
```

Default SQLite path inside the container:

```text
/var/lib/incidentrelay/incidentrelay.db
```

Default config path inside the container:

```text
/etc/incidentrelay/incidentrelay.conf
```

The config file is selected by:

```text
INCIDENTRELAY_CONFIG_FILE
```

## Quick start with SQLite

```bash
docker compose up -d --build
```

Open the UI:

```text
http://SERVER_IP:8080/login
```

Show logs:

```bash
docker compose logs -f incidentrelay
docker compose logs -f incidentrelay-scheduler
```

## Run migrations

If migrations are not run automatically by your container entrypoint, run:

```bash
docker compose exec incidentrelay python manage.py migrate
```

## Create the first admin user

```bash
docker compose exec incidentrelay \
  python manage.py create-admin \
    --username admin \
    --password 'change-me-123' \
    --email admin@example.com
```

Change the password and email before production use.

## Default SQLite config

File:

```text
docker/incidentrelay.docker.conf
```

Example:

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

## PostgreSQL variant

Use PostgreSQL for:

- larger teams;
- higher alert volume;
- multiple web workers;
- longer-term production installations.

Start with PostgreSQL if the repository provides a PostgreSQL Compose override:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.postgres.yml \
  up -d
```

PostgreSQL config example:

```ini
[database]
type = postgresql
host = postgres
port = 5432
name = incidentrelay
user = incidentrelay
password = incidentrelay-change-me
```

## External access

With this mapping:

```yaml
ports:
  - "8080:8080"
```

IncidentRelay is available on:

```text
http://SERVER_IP:8080
```

if the firewall allows port `8080`.

For production, it is better to expose IncidentRelay through Nginx or HAProxy with HTTPS:

```text
Internet -> Nginx/HAProxy :443 -> IncidentRelay :8080
```

Set the public URL correctly:

```ini
[server]
public_base_url = https://incidentrelay.example.com
```

`public_base_url` is used for generated links and callbacks.

## Custom voice providers

Custom voice providers can be mounted into:

```text
/usr/local/lib/incidentrelay/voice_providers
```

Example Compose mount:

```yaml
volumes:
  - ./custom_voice_providers:/usr/local/lib/incidentrelay/voice_providers:ro
```

After changing provider files, restart the containers:

```bash
docker compose restart incidentrelay incidentrelay-scheduler
```
