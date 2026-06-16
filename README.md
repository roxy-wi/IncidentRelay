![IncidentRelay](app/static/images/incidentrelay-logo.svg)

# IncidentRelay

**Self-hosted on-call scheduling, alert routing, alert delivery, reminders, and escalations for teams that want control over their incident workflow.**

IncidentRelay helps SRE, DevOps, platform, infrastructure, and operations teams route alerts to the right people through the right channels without depending on a hosted incident-management platform.

It provides the core building blocks of an on-call system:

- access groups and RBAC-style group roles;
- teams and on-call rotations;
- alert intake routes with per-route tokens;
- Alertmanager, Zabbix, Sentry, and generic webhook integrations;
- Mattermost, Slack, Telegram, Discord, Microsoft Teams, email, webhook, and voice-call notifications;
- profile-level browser/PWA push notifications;
- profile notification rules for browser push, email, and voice-call follow-up;
- acknowledge and resolve workflows;
- reminders and escalation to the next on-call user;
- rotation overrides;
- alert silences;
- maintenance windows for planned work and alert behavior control;
- calendar view for on-call schedules;
- personal API tokens;
- Swagger/OpenAPI documentation.

IncidentRelay is designed for **self-hosted environments** where teams need predictable behavior, clear ownership, easy integrations, and full control over alert routing.

![Alerts](screenshots/alerts.png)

---

## Why IncidentRelay?

Many teams need on-call routing, but do not always need a large SaaS incident platform.

IncidentRelay focuses on the practical workflow:

```text
Monitoring system -> Route -> Team -> Rotation -> Notification channels -> ACK / Resolve
```

A route owns its own intake token, so external systems send alerts to an exact alert path:

```text
ROUTE_INTAKE_TOKEN -> Route -> Team -> Rotation -> Channels
```

Channels only describe where notifications are delivered. Routes decide which team receives the alert and which channels are used.

Profile browser push and profile notification rules are separate from route channels. They target the assigned user's own browser devices and contact methods.

This keeps alert delivery easier to reason about, easier to audit, and safer for self-hosted deployments.

---

![Callendar](screenshots/callendar.png)

## Highlights

### Self-hosted by design

Run IncidentRelay in your own environment, with your own database, your own network rules, and your own operational policies.

### Route-based alert intake

Alert intake tokens belong to routes, not channels. This makes it clear which incoming integration is allowed to submit alerts to which team and rotation.

### Multi-team and multi-group support

Use groups as access boundaries. Teams, rotations, routes, channels, alerts, and silences are scoped through groups and memberships.

### Escalation and reminders

Unacknowledged alerts can trigger repeated reminders and then escalate to the next on-call user according to the team configuration.

### Mattermost with real actions

Mattermost Bot API mode supports interactive `Acknowledge` and `Resolve` buttons, message updates, and severity-based attachment colors.

### Telegram actions and worker

Telegram notifications can include action buttons and alert links. Telegram callback/polling processing is handled by the optional `incidentrelay-telegram-worker` service.

### Pluggable voice calls

IncidentRelay can be extended with custom voice providers for self-hosted installations. Providers can implement text-to-speech calls, call status callbacks, DTMF button callbacks, ACK / Resolve actions from phone keypad, and optional call status polling.

### Browser/PWA push and profile rules

Users can enable browser push from their profile and receive alert notifications on active browser or installed PWA devices. Browser push can include `Acknowledge` and `Resolve` actions.

Profile notification rules let users define follow-up delivery through browser push, email, or voice call without turning browser push into a route channel.

### API-first

IncidentRelay includes Swagger/OpenAPI documentation and personal API tokens with scopes for alerts, resources, and profile access.

---

![Routes](screenshots/routes.png)

## Supported integrations

### Incoming alert sources

| Source          | Endpoint                                   |
|-----------------|--------------------------------------------|
| Alertmanager    | `POST /api/integrations/alertmanager`      |
| Zabbix          | `POST /api/integrations/zabbix`            |
| Sentry          | `POST /api/integrations/sentry/<route_id>` |
| Generic webhook | `POST /api/integrations/webhook`           |

### Notification channels

| Channel | Notes |
|---|---|
| Mattermost | Incoming webhook mode or Bot API mode with buttons and updates |
| Slack | Webhook notifications |
| Telegram | Bot notifications and optional action buttons |
| Discord | Webhook notifications |
| Microsoft Teams | Webhook notifications |
| Email | Email recipients |
| Webhook | Generic outbound webhook |
| Voice call | Pluggable provider API for self-hosted voice integrations |

Browser/PWA push is profile-level, not a notification channel. Users enable it in Profile, and IncidentRelay sends push notifications to the assigned user's active browser/PWA devices.

---

## Installation

Choose the installation method that matches your environment.

### Docker Compose

Recommended for quick start, testing, and simple self-hosted deployments.

```bash
docker compose up -d --build
```

With PostgreSQL:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.postgres.yml \
  up -d
```

Read more: [Docker installation](docs/getting-started/docker.md)

### Kubernetes (Helm)

A Helm chart lives in [`helm/incidentrelay`](helm/incidentrelay). It deploys the web UI plus the scheduler and Telegram workers, renders the application config from values into a Secret, and wires up the `/healthz` and `/readyz` probes.

> **Note:** no public image is published yet — the default `image.repository` (`roxywi/incidentrelay`) does not exist on Docker Hub, so an out-of-the-box install ends in `ImagePullBackOff`. Build the image yourself, push it to your registry and set `image.repository` / `image.tag`.

```bash
helm install incidentrelay ./helm/incidentrelay \
  --set image.repository=registry.example.com/incidentrelay \
  --set image.tag=1.0.15-beta \
  --set config.main.secret_key="$(openssl rand -hex 32)"
```

The default values use SQLite on a shared PersistentVolumeClaim. This is strictly a single-node setup: SQLite over network-backed `ReadWriteMany` storage (NFS and friends) is a known way to corrupt the database. Database migrations run on web pod start, so keep `web.replicaCount` at `1` (or disable `web.runMigrations` and migrate out of band). For anything multi-node or multi-replica, point `config.database` at PostgreSQL:

```bash
helm install incidentrelay ./helm/incidentrelay \
  --set config.main.secret_key="$(openssl rand -hex 32)" \
  --set config.database.type=postgresql \
  --set config.database.host=postgres.example.svc \
  --set config.database.port=5432 \
  --set config.database.name=incidentrelay \
  --set config.database.user=incidentrelay \
  --set config.database.password=change-me \
  --set persistence.enabled=false
```

All settings from `incidentrelay.conf` are available under `config.*` in [values.yaml](helm/incidentrelay/values.yaml); you can also bring a pre-rendered config via `existingConfigSecret`.

### RedHat-like distributions from RPM repository

Recommended for RHEL, Rocky Linux, AlmaLinux, and CentOS Stream.

```bash
sudo dnf install -y curl
sudo curl -fsSL \
  https://repo.incidentrelay.io/incidentrelay.repo \
  -o /etc/yum.repos.d/incidentrelay.repo
sudo dnf makecache
sudo dnf install -y incidentrelay
```

For older yum-based systems:

```bash
sudo yum install -y curl
sudo curl -fsSL \
  https://repo.incidentrelay.io/incidentrelay.repo \
  -o /etc/yum.repos.d/incidentrelay.repo
sudo yum makecache
sudo yum install -y incidentrelay
```

Read more: [RedHat RPM installation](docs/getting-started/rpm-installation.md)

### Manual systemd installation

Recommended when you want to run IncidentRelay directly from source code or manage the Python environment manually.

Read more: [Systemd installation](docs/getting-started/systemd.md)

---

## Runtime layout

Common paths used by the RPM and systemd installation:

```text
/var/www/incidentrelay                  # application code
/var/www/incidentrelay/venv             # Python environment or venv-compatible wrapper
/etc/incidentrelay/incidentrelay.conf   # main configuration file
/var/lib/incidentrelay                  # runtime data
/var/log/incidentrelay                  # logs
/usr/local/lib/incidentrelay/voice_providers  # custom voice providers
```

Systemd services:

```text
incidentrelay.service               # HTTP API, UI, webhooks
incidentrelay-scheduler.service         # reminders, escalations, periodic jobs
incidentrelay-telegram-worker.service   # optional Telegram callbacks/polling
```

System user:

```text
incidentrelay
```

---

## Configuration

IncidentRelay reads the configuration file path from:

```text
INCIDENTRELAY_CONFIG_FILE
```

Example:

```bash
export INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
```

For production, set the public URL used for generated links and callback URLs:

```ini
[server]
public_base_url = https://incidentrelay.example.com
```

SQLite is suitable for small single-node installations:

```ini
[database]
type = sqlite
path = /var/lib/incidentrelay/incidentrelay.db
```

PostgreSQL is recommended for larger or long-running production installations:

```ini
[database]
type = postgresql
host = 127.0.0.1
port = 5432
name = incidentrelay
user = incidentrelay
password = change-me
```

Read more: [Configuration](docs/getting-started/configuration.md)

---

## First setup

After installation, initialize the database and create the first administrator.

### Run database migrations

For RPM/systemd installations:

```bash
sudo -u incidentrelay \
  INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf \
  /var/www/incidentrelay/venv/bin/python \
  /var/www/incidentrelay/manage.py migrate
```

For Docker installations:

```bash
docker compose exec incidentrelay \
  python manage.py migrate
```

### Create the first admin user

For RPM/systemd installations:

```bash
sudo -u incidentrelay \
  INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf \
  /var/www/incidentrelay/venv/bin/python \
  /var/www/incidentrelay/manage.py create-admin \
  --username admin \
  --password 'change-me-123' \
  --email admin@example.com
```

For Docker installations:

```bash
docker compose exec incidentrelay \
  python manage.py create-admin \
  --username admin \
  --password 'change-me-123' \
  --email admin@example.com
```

Change the password and email before using these commands in production.

---

## Basic UI setup flow

After the first login:

```text
1. Create a group
2. Create users
3. Add users to the group
4. Create a team
5. Add users to the team
6. Create a rotation
7. Add rotation members
8. Create notification channels
9. Create a route
10. Copy the route intake token
11. Configure browser push VAPID keys if browser/PWA notifications are required
12. Ask users to enable browser push or profile notification rules if required
13. Configure Alertmanager, Zabbix, or webhook sender
14. Send a test alert
15. Acknowledge or resolve the alert
```

Detailed guide: [First login and initial setup](docs/getting-started/first-login.md)

---

## Example Alertmanager request

```bash
curl -X POST http://127.0.0.1:8080/api/integrations/alertmanager \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ALERTMANAGER_ROUTE_TOKEN' \
  -d '{
    "status": "firing",
    "alerts": [
      {
        "status": "firing",
        "labels": {
          "alertname": "DiskFull",
          "severity": "critical",
          "team": "infra",
          "instance": "host1"
        },
        "annotations": {
          "summary": "Disk is full",
          "description": "/var is 95% full"
        },
        "fingerprint": "disk-full-host1-var"
      }
    ]
  }'
```

More examples:

- [Alertmanager integration](docs/integrations/alertmanager.md)
- [Zabbix integration](docs/integrations/zabbix.md)
- [Generic webhook integration](docs/integrations/generic-webhook.md)

---

## Mattermost buttons and message updates

Mattermost has two modes.

**Incoming webhook mode** sends plain messages only.

**Bot API mode** is recommended when you want:

- `Acknowledge` button;
- `Resolve` button;
- message updates after ACK / Resolve;
- severity-based colors.

More details: [Mattermost integration](docs/integrations/mattermost.md)

---

## Custom voice providers

IncidentRelay supports custom voice providers for self-hosted installations.

A provider is a Python module that can be placed into:

```text
/usr/local/lib/incidentrelay/voice_providers
```

Custom providers can implement:

- text-to-speech call creation;
- provider call ID tracking;
- call status callbacks;
- DTMF button callbacks;
- ACK / Resolve actions from phone keypad;
- optional call status polling.

Start here:

- [Custom Voice Providers](docs/voice-providers/index.md)
- [Provider API](docs/voice-providers/provider-api.md)
- [Configuration](docs/voice-providers/configuration.md)
- [Callbacks and DTMF](docs/voice-providers/callbacks.md)
- [Security](docs/voice-providers/security.md)
- [Troubleshooting](docs/voice-providers/troubleshooting.md)
- [Example providers](docs/examples/voice_providers/)

---

## API documentation

Swagger UI is available at:

```text
/docs
```

OpenAPI JSON is available at:

```text
/api/openapi.json
```

---

## Documentation

| Topic | Link |
|---|---|
| Getting started | [docs/getting-started/](docs/getting-started/index.md) |
| Docker installation | [docs/getting-started/docker.md](docs/getting-started/docker.md) |
| RedHat RPM installation | [docs/getting-started/rpm-installation.md](docs/getting-started/rpm-installation.md) |
| Systemd installation | [docs/getting-started/systemd.md](docs/getting-started/systemd.md) |
| Configuration | [docs/getting-started/configuration.md](docs/getting-started/configuration.md) |
| First login | [docs/getting-started/first-login.md](docs/getting-started/first-login.md) |
| Groups and RBAC | [docs/concepts/groups-and-rbac.md](docs/concepts/groups-and-rbac.md) |
| Teams, rotations, routes | [docs/concepts/teams-rotations-routes.md](docs/concepts/teams-rotations-routes.md) |
| Route intake tokens | [docs/concepts/route-intake-tokens.md](docs/concepts/route-intake-tokens.md) |
| Maintenance Windows | [docs/concepts/maintenance-windows.md](docs/concepts/maintenance-windows.md) |
| Services | [docs/concepts/services.md](docs/concepts/services.md) |
| Channels | [docs/concepts/channels.md](docs/concepts/channels.md) |
| Alertmanager | [docs/integrations/alertmanager.md](docs/integrations/alertmanager.md) |
| Zabbix | [docs/integrations/zabbix.md](docs/integrations/zabbix.md) |
| Generic webhook | [docs/integrations/generic-webhook.md](docs/integrations/generic-webhook.md) |
| Mattermost | [docs/integrations/mattermost.md](docs/integrations/mattermost.md) |
| Alerts | [docs/usage/alerts.md](docs/usage/alerts.md) |
| Browser push | [docs/usage/browser-push.md](docs/usage/browser-push.md) |
| Calendar | [docs/usage/calendar.md](docs/usage/calendar.md) |
| Silences | [docs/usage/silences.md](docs/usage/silences.md) |
| Rotation overrides | [docs/usage/rotation-overrides.md](docs/usage/rotation-overrides.md) |
| Profile and API tokens | [docs/usage/profile-and-tokens.md](docs/usage/profile-and-tokens.md) |
| Logging | [docs/administration/logging.md](docs/administration/logging.md) |
| Troubleshooting | [docs/administration/troubleshooting.md](docs/administration/troubleshooting.md) |
| Demo data | [docs/administration/demo-data.md](docs/administration/demo-data.md) |
| Schema check | [docs/administration/schema-check.md](docs/administration/schema-check.md) |
| Custom voice providers | [docs/voice-providers/index.md](docs/voice-providers/index.md) |

---

## Demo data

Create demo data:

```bash
python manage.py demo-data
```

The command creates demo groups, users, teams, rotations, channels, routes, and route intake tokens.

Static demo-data check:

```bash
python app/check_demo_data.py
```

More details: [Demo data](docs/administration/demo-data.md)

---

## Schema check

After running migrations, verify that all Peewee model tables and columns exist in the configured database:

```bash
python app/check_schema.py
```

Expected output:

```text
Schema check OK: all model tables and columns exist.
```

More details: [Schema check](docs/administration/schema-check.md)

---

## Troubleshooting

If an alert is not visible or not delivered:

```text
1. Check that the correct route intake token was used.
2. Check that the endpoint matches the route source.
3. Check that route matchers match alert labels.
4. Check that the group is active.
5. Check that the team is active.
6. Check that the UI active group is correct.
7. Select "All my groups" and reload the Alerts page.
8. Check routing_error in the integration response.
9. Check JSON logs by error_id if the server returned one.
```

More details: [Troubleshooting](docs/administration/troubleshooting.md)

---

## License

See [LICENSE](LICENSE).
