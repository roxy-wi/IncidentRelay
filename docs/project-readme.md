---
title: IncidentRelay Project README
description: Repository overview, workflow, installation and API summary.
---

# IncidentRelay

IncidentRelay is a self-hosted on-call scheduling, alert routing and notification service.

It provides:

- groups and RBAC;
- teams and rotations;
- service directory with affected systems, links, runbooks, dependencies and impact analytics;
- route-based alert intake tokens;
- Alertmanager, Zabbix and generic webhook intake;
- Mattermost, Telegram, email, webhook-based and voice call notification channels;
- ACK and Resolve workflows;
- reminders and escalation;
- silences and rotation overrides;
- calendar view;
- personal API tokens;
- Swagger/OpenAPI documentation.

## Core workflow

```text
Monitoring system -> Route -> Service -> Team -> Rotation -> Notification channels -> ACK / Resolve
```

Routes decide how alerts enter IncidentRelay. Services describe what logical system is affected.

Service and team display order:

```text
name -> slug -> "-"
```

## Installation

Choose one method:

| Method | Documentation |
|---|---|
| Docker Compose | [Docker Installation](getting-started/docker.md) |
| RPM package | [RPM Installation](getting-started/rpm-installation.md) |
| Manual systemd | [Manual systemd Installation](getting-started/systemd.md) |

## Runtime services

IncidentRelay should run as separate services:

```text
incidentrelay           # web API, UI, incoming webhooks
incidentrelay-scheduler # reminders, escalations, periodic jobs
```

Telegram worker is optional and only needed when Telegram polling/actions are used.

## Configuration

IncidentRelay reads config path from:

```text
INCIDENTRELAY_CONFIG_FILE
```

Example:

```bash
export INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
```

Do not use the old `ONCALL_CONFIG_FILE` name.

## Database migrations

```bash
python manage.py migrate
```

## Create first admin

```bash
python manage.py create-admin   --username admin   --password 'change-me-123'   --email admin@example.com
```

## First setup flow

```text
1. Create a group
2. Create users
3. Add users to the group
4. Create a team
5. Add users to the team
6. Create a rotation
7. Add rotation members
8. Create a service
9. Add service links and runbooks
10. Create notification channels
11. Create a route and select default service
12. Copy the route intake token
13. Configure Alertmanager, Zabbix, or webhook sender
14. Send a test alert
15. Acknowledge or resolve the alert
```

## Services

A service describes the affected system, for example:

```text
RabbitMQ Cloud
Billing API
PostgreSQL Prod
Frontend Web
```

A service can have:

- dashboard, logs, traces, repository and documentation links;
- generic runbooks;
- alert-specific runbooks selected by matchers;
- dependencies;
- analytics and impact status.

Runbook matcher behavior:

```text
empty matchers -> generic runbook for all alerts of the service
matchers set   -> runbook only for matching alerts
```

## Email notifications

Email channel does not store recipients or SMTP transport settings.

- SMTP is configured globally in the config file.
- Emails are sent to the assigned user's profile email address.
- Email channel can optionally override the HTML template.

## Reminder intervals

Reminder interval is configured on rotations:

```text
0 disables reminders
>= 60 enables reminders
1..59 invalid
```

## API

Swagger UI:

```text
/docs
```

OpenAPI JSON:

```text
/api/openapi.json
```

Service API endpoints are available under:

```text
/api/services
```

## Documentation

| Topic | Link |
|---|---|
| First login | [getting-started/first-login.md](getting-started/first-login.md) |
| Services | [concepts/services.md](concepts/services.md) |
| Alerts | [usage/alerts.md](usage/alerts.md) |
| Route intake tokens | [concepts/route-intake-tokens.md](concepts/route-intake-tokens.md) |
| API | [api/index.md](api/index.md) |
| Troubleshooting | [administration/troubleshooting.md](administration/troubleshooting.md) |

## License

MIT
