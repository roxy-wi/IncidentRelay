# IncidentRelay

IncidentRelay is an on-call incident routing and escalation service designed to help teams deliver alerts to the right people at the right time.

It provides team schedules, routing rules, notification channels, acknowledgements, resolve workflows, and escalation logic for incident management platforms, monitoring systems, and internal SRE tools.

## Key Features

- On-call schedules for teams and users
- Alert routing based on teams, routes, and channels
- Acknowledge and resolve workflows
- Escalation support
- Calendar view for team schedules
- Notification delivery through multiple channels
- API-first design for integrations with monitoring systems

It supports:

- access groups;
- on-call teams;
- on-call rotations;
- team and group membership management;
- Alertmanager, Zabbix, and generic webhook intake;
- Mattermost, Slack, Telegram, Discord, Teams, email, and webhook notifications;
- Acknowledge and Resolve actions;
- repeated reminders for unacknowledged alerts;
- escalation to the next on-call user;
- on-call calendar view;
- JWT authentication;
- RBAC-style group roles;
- personal API tokens;
- Swagger/OpenAPI documentation.

## 1. Install

Unpack the archive:

```bash
git clone https://github.com/roxy-wi/incedentrelay.git
```

Create a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## 2. Configure

The sample configuration file is here:

```text
etc/incedentrelay/incedentrelay.conf
```

For local development you can use it directly:

```bash
export ONCALL_CONFIG_FILE=$PWD/etc/incedentrelay/incedentrelay.conf
```

For a server installation, copy it to `/etc`:

```bash
sudo mkdir -p /etc/incedentrelay
sudo cp etc/incedentrelay/incedentrelay.conf /etc/incedentrelay/incedentrelay.conf
sudo editor /etc/incedentrelay/incedentrelay.conf
```

If `ONCALL_CONFIG_FILE` is not set, the service reads:

```text
/etc/incedentrelay/incedentrelay.conf
```

### Minimal SQLite configuration

```ini
[main]
secret_key = change-me
timezone = UTC
public_base_url = http://127.0.0.1:8080

[database]
type = sqlite
name = incedentrelay.db

[auth]
api_auth_required = true
rbac_enforced = true
jwt_secret = change-me-too
jwt_expire_minutes = 1440
jwt_cookie_name = incedentrelay_jwt
jwt_cookie_secure = false

[alerts]
reminder_after_seconds = 300
reminder_interval_seconds = 60
alert_group_window_seconds = 3600

[scheduler]
lock_ttl_seconds = 120

[logging]
log_file = ./logs/incedentrelay.log
log_level = INFO
json = true

[mattermost]
action_secret = change-me
```

## 3. `public_base_url` vs Mattermost URL

These are different settings.

`public_base_url` is the public URL of the IncidentRelay itself.

Example:

```ini
[main]
public_base_url = https://incedentrelay.example.com
```

Mattermost uses this URL when a user clicks buttons such as `Acknowledge` or `Resolve`. The button callback URL is built like this:

```text
https://incedentrelay.example.com/api/integrations/mattermost/actions
```

The Mattermost URL in a Mattermost channel is the URL of the Mattermost server API.

Example:

```text
https://mattermost.example.com
```

IncidentRelay uses it to send and update Mattermost posts through the Bot API.

In short:

```text
public_base_url        = where Mattermost calls On-call back
Mattermost URL         = where On-call sends messages to Mattermost
```

For Mattermost buttons to work, `public_base_url` must be reachable from the Mattermost server.

## 4. Initialize the database

Run migrations:

```bash
python app/migrate.py migrate
```

Show migration status:

```bash
python app/migrate.py list
```

## 5. Create the first administrator

```bash
python manage.py create-admin \
  --username admin \
  --password 'change-me-123' \
  --email admin@example.com
```

The administrator is needed for the first login and initial setup.

## 6. Start the service

For local development:

```bash
python run.py
```

Open:

```text
http://127.0.0.1:8080/login
```

For production web serving:

```bash
gunicorn -w 4 -b 0.0.0.0:8080 'app:create_app()'
```

Run the scheduler separately if you have a dedicated scheduler entrypoint:

```bash
python scheduler.py
```

For local testing, `python run.py` is enough.

## 7. First login

Open:

```text
/login
```

Log in with the admin user created earlier.

## 8. Main concepts

### Group

A group is an access boundary.

All teams belong to a group. Users only see resources from groups they belong to.

A user can belong to multiple groups.

### Group role

A user can have one of these roles inside a group:

```text
read_only
rw
```

`read_only` can view resources and alerts.

`rw` can create, edit, acknowledge, and resolve resources in that group.

Admin users can see and manage everything.

### Team

A team is an on-call team inside a group.

Example:

```text
Group: Production
Team: Infrastructure
Team slug: infra
```

The team slug is commonly used in Alertmanager labels:

```yaml
team: infra
```

### Rotation

A rotation defines who is on call and when the duty changes.

A rotation has:

- team;
- members;
- member order;
- handoff time;
- rotation type;
- reminder interval.

### Route

A route connects incoming alerts to a team, rotation, and notification channels.

Example:

```text
Source: alertmanager
Team: infra
Rotation: infra-primary
Channels: infra-mattermost
Matchers: {"labels": {"team": "infra"}}
```

### Channel

A channel is a notification destination.

Supported channel types:

```text
Mattermost
Slack
Telegram
Webhook
Discord
Teams
Email
```

Each route has an alert intake token. External systems use that token to send alerts to exactly that route.

## 9. Basic setup in the web UI

### Step 1. Create a group

Open:

```text
Administration → Groups
```

Create a group:

```text
Slug: production
Name: Production
```

### Step 2. Create users

Open:

```text
Administration → Users
```

Create users:

```text
ivan
petr
sergey
```

### Step 3. Add users to the group

Open:

```text
Administration → Groups
```

Use `Add user to group`.

Example:

```text
Group: Production
User: ivan
Role: rw
```

Repeat for all users.

You can view group members on the same page by clicking `Members` next to the group.

### Step 4. Create a team

Open:

```text
Teams
```

Create a team:

```text
Group: Production
Slug: infra
Name: Infrastructure
Escalate after reminders: 2
```

`Escalate after reminders` means how many reminder messages are sent before the alert is assigned to the next on-call user.

### Step 5. Add users to the team

Open:

```text
Teams
```

Click `Members` next to the team.

Use `Add user to selected team`.

Example:

```text
User: ivan
Role: rw
```

The team members table shows the current team composition.

### Step 6. Create a rotation

Open:

```text
Rotations
```

Create a rotation:

```text
Team: infra
Name: infra-primary
Type: daily
Handoff time: 09:00
Reminder interval: 300 seconds
```

### Step 7. Add rotation members

In `Rotations`, add users in order:

```text
Position 0: ivan
Position 1: petr
Position 2: sergey
```

### Step 8. Create a notification channel

Open:

```text
Channels
```

Select:

```text
Group: Production
Team: infra
```

Create a Mattermost channel in Bot API mode:

```text
Type: mattermost
Mode: Bot API with buttons and message updates
Mattermost URL: https://mattermost.example.com
Bot token: <bot token>
Channel ID: <channel id>
Callback secret: optional
```

Channels do not have alert intake tokens. They only define where notifications are sent.

If a route token is lost, open Routes and click `Regenerate token` next to the route.

### Step 9. Create a route

Open:

```text
Routes
```

Create a route:

```text
Team: infra
Source: alertmanager
Rotation: infra-primary
Channels: infra-mattermost
Matchers JSON: {"labels": {"team": "infra"}}
Group by JSON: ["alertname", "instance"]
```

## 10. Send Alertmanager alerts

Endpoint:

```text
POST /api/integrations/alertmanager
```

Required header:

```http
Authorization: Bearer <ROUTE_INTAKE_TOKEN>
```

Example:

```bash
curl -X POST http://127.0.0.1:8080/api/integrations/alertmanager \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ROUTE_INTAKE_TOKEN' \
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

Example response:

```json
[
  {
    "id": 1,
    "team_id": 1,
    "team_slug": "infra",
    "route_id": 1,
    "rotation_id": 1,
    "routing_error": null,
    "created": true,
    "status": "firing",
    "assignee": "ivan"
  }
]
```

If `route_id` is `null`, the alert did not match a route.

Check `routing_error` for details.

## 11. Alertmanager configuration example

```yaml
receivers:
  - name: incedentrelay-infra
    webhook_configs:
      - url: "https://incedentrelay.example.com/api/integrations/alertmanager"
        send_resolved: true
        http_config:
          authorization:
            type: Bearer
            credentials: "ROUTE_INTAKE_TOKEN"

route:
  receiver: incedentrelay-infra
  group_by:
    - alertname
    - instance
  group_wait: 10s
  group_interval: 1m
  repeat_interval: 30m
```

If your Alertmanager version cannot set the `Authorization` header, add it with a reverse proxy.

## 12. Mattermost behavior

Mattermost has two modes.

### Incoming webhook mode

This mode sends plain messages only.

It cannot:

- show buttons;
- update messages after acknowledge;
- update messages after resolve.

### Bot API mode

This mode is recommended.

It supports:

- `Acknowledge` button;
- `Resolve` button;
- message updates;
- colored attachment borders.

Colors:

```text
critical/high/error → red
warning/acknowledged → yellow
info → blue
resolved → green
```

After `Acknowledge`, the original Mattermost message is updated and keeps only the `Resolve` button.

After `Resolve`, the original Mattermost message is updated, the buttons are removed, and the border becomes green.

## 13. Work with alerts

Open:

```text
Alerts
```

You can:

- view status;
- view severity;
- view assignee;
- view route;
- view rotation;
- open details;
- acknowledge an alert;
- resolve an alert.

Alert statuses:

```text
firing
acknowledged
resolved
silenced
```

## 14. Silences

A silence temporarily suppresses notifications for matching alerts.

Open:

```text
Silences
```

Example matcher:

```json
{
  "labels": {
    "instance": "host1"
  }
}
```

## 15. Calendar

Open:

```text
Calendar
```

The calendar shows on-call duty by team.

It takes rotation members, member order, duration, and overrides into account.

## 16. Profile

Open Profile from the top right corner.

Users can:

- update display name;
- update email;
- update phone;
- set Telegram chat ID;
- set Slack user ID;
- set Mattermost user ID;
- change password;
- choose active group;
- create a personal API token.

Active group limits resource lists in the UI.

To see all accessible resources, select:

```text
All my groups
```

## 17. Personal API tokens

Users can create personal API tokens in Profile.

Available scopes:

```text
alerts:read
alerts:write
resources:read
resources:write
profile:read
profile:write
*
```

The token value is shown only once.

## 18. Swagger

Swagger UI:

```text
/docs
```

OpenAPI JSON:

```text
/api/openapi.json
```

## 19. Troubleshooting alert delivery

If an alert is not visible:

1. Check that the correct channel intake token was used.
2. Check that the route source is `alertmanager`.
3. Check that route matchers match alert labels.
4. Check that the group is active.
5. Check that the team is active.
6. Check that the top right active group is correct.
7. Select `All my groups` and reload the Alerts page.

The webhook response includes:

```text
route_id
rotation_id
routing_error
```

## 20. Logs

Logs are configured here:

```ini
[logging]
log_file = ./logs/incedentrelay.log
json = true
```

View logs:

```bash
tail -f ./logs/incedentrelay.log
```

## 21. Typical setup checklist

```text
1. Log in as admin
2. Create a group
3. Create users
4. Add users to the group
5. Create a team
6. Add users to the team
7. Create a rotation
8. Add rotation members
9. Create a channel
10. Copy the alert intake token
11. Create a route
12. Configure Alertmanager
13. Send a test alert
14. Check the Alerts page
15. Check the Mattermost message
```


## Rotation overrides

A rotation override temporarily replaces the normal on-call user for a selected rotation and time range.

Use it when someone is on vacation, sick, unavailable, or when another engineer needs to cover a specific period.

### Create an override in the web UI

Open:

```text
Rotations
```

In the `Create override` block:

1. Select a rotation.
2. Select the user who should cover the duty.
3. Set `Starts at`.
4. Set `Ends at`.
5. Optionally write a reason.
6. Click `Create override`.

The override appears in the `Overrides` table.

You can also click `Overrides` next to a rotation in the rotations table to load its override list.

### Delete an override

Open:

```text
Rotations
```

Select the rotation or click `Overrides`, then click `Delete` next to the override.

### API

Create override:

```bash
curl -X POST http://127.0.0.1:8080/api/rotations/1/overrides   -H 'Content-Type: application/json'   -H 'Authorization: Bearer JWT_TOKEN'   -d '{
    "user_id": 2,
    "starts_at": "2026-05-01T09:00:00",
    "ends_at": "2026-05-02T09:00:00",
    "reason": "Vacation cover"
  }'
```

List overrides:

```bash
curl -H 'Authorization: Bearer JWT_TOKEN'   http://127.0.0.1:8080/api/rotations/1/overrides
```

Delete override:

```bash
curl -X DELETE   -H 'Authorization: Bearer JWT_TOKEN'   http://127.0.0.1:8080/api/rotations/overrides/10
```


## Personal API token access

Personal API tokens created in Profile can be used with regular API endpoints:

```bash
curl -H 'Authorization: Bearer PERSONAL_API_TOKEN' \
  http://127.0.0.1:8080/api/alerts
```

Scopes control what the token can do:

```text
alerts:read       read alerts
alerts:write      acknowledge, resolve, and submit alerts
resources:read    read teams, groups, rotations, routes, channels, silences, calendar
resources:write   create or edit teams, groups, rotations, routes, channels, silences
profile:read      read profile
profile:write     edit profile
*                 all scopes
```

If the token is created for a specific group, API responses are limited to that group.
If the token has no group restriction, it uses the same group access as the token owner.

For example, to read teams and routes, create the token with:

```text
resources:read
```

To read alerts, create the token with:

```text
alerts:read
```


## Route intake tokens

Alert intake tokens belong to routes, not channels.

A route token identifies the exact alert path:

```text
Route token -> Route -> Team -> Rotation -> Notification channels
```

External systems should send alerts with the route token:

```bash
curl -X POST http://127.0.0.1:8080/api/integrations/alertmanager \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ROUTE_INTAKE_TOKEN' \
  -d '{...}'
```

Channels do not expose intake tokens. They are notification targets used by routes.

If you need a new token, open `Routes` and click `Regenerate token` next to the route.


## JSON error logs

Unhandled server errors return JSON with `error_id`:

```json
{
  "error": "Internal Server Error",
  "error_id": "uuid",
  "message": "Unexpected server error. Check JSON log by error_id."
}
```

Use the `error_id` to find the real traceback in the log file:

```bash
grep 'ERROR_ID_HERE' ./logs/incedentrelay.log
```


## Logging policy

The service writes only these JSON log records:

```text
user_action
alert_intake
error
```

Regular HTTP request logging is disabled by default:

```ini
[logging]
requests = false
```

User actions are logged through the audit layer. Incoming alerts are logged when
Alertmanager, Zabbix, or generic webhooks submit alerts. Unhandled server errors
are logged with `error_id`.


## Logging diagnostics

Request logging is hard-disabled in application code. The service JSON log file
accepts only these logger names:

```text
incedentrelay.audit
incedentrelay.alerts
incedentrelay.error
```

Check active logging settings:

```bash
curl -H 'Authorization: Bearer JWT_TOKEN' \
  http://127.0.0.1:8080/api/version/logging
```

Expected response:

```json
{
  "request_logging_registered": false,
  "allowed_loggers": ["incedentrelay.audit", "incedentrelay.alerts", "incedentrelay.error"]
}
```
## Editing memberships

The web UI supports editing and disabling memberships:

```text
Administration -> Groups -> Members
Teams -> Members
Rotations -> Members
```

For group and team memberships you can change:

```text
role
active flag
```

For rotation members you can change:

```text
position
active flag
```

Disabling a membership keeps historical records intact.


## Schema initialization check

After running migrations, you can check that all Peewee model tables and columns
exist in the configured database:

```bash
python app/check_schema.py
```

Expected output:

```text
Schema check OK: all model tables and columns exist.
```

Fresh initialization creates all application tables from
`app/migrations/20260427000001_initial_schema.py`.


## Demo data

Create demo data:

```bash
python manage.py demo-data
```

The command creates:

- admin user `admin` with password `admin123`;
- admin is not attached to any group and has no active group;
- `infra` group and `database` group;
- regular demo users with password `changeme123`;
- regular users are added to their group with `rw` role;
- regular users have `active_group` set;
- teams, rotations, channels, and alert routes;
- route intake tokens for Alertmanager routes.

Static demo-data check:

```bash
python app/check_demo_data.py
```

Expected output:

```text
Demo data check OK.
```


## create-admin group behavior

`python manage.py create-admin` creates or updates an administrator without group
memberships and without active_group. If the username already existed as a
regular user, existing group memberships are disabled.

## Route examples

Incoming alerts are routed by the route intake token.

The route token selects the exact route:

```text
ROUTE_INTAKE_TOKEN -> Route -> Team -> Rotation -> Channels
```

The endpoint must match the route `source`.

```text
route.source = alertmanager -> POST /api/integrations/alertmanager
route.source = webhook      -> POST /api/integrations/webhook
route.source = zabbix       -> POST /api/integrations/zabbix
```

If the route token belongs to an `alertmanager` route and you send the request to
`/api/integrations/webhook`, the service returns:

```json
{
  "routing_error": "route source 'alertmanager' does not match alert source 'webhook'"
}
```

### Alertmanager route

Create a route:

```text
Name: infra-alertmanager
Source: alertmanager
Team: infra
Rotation: infra-primary
Channels: infra-mattermost
Matchers JSON: {"labels": {"team": "infra"}}
Group by JSON: ["alertname", "instance"]
```

Copy the route intake token after creating the route.

Send a test Alertmanager payload:

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

Send resolved event:

```bash
curl -X POST http://127.0.0.1:8080/api/integrations/alertmanager \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ALERTMANAGER_ROUTE_TOKEN' \
  -d '{
    "status": "resolved",
    "alerts": [
      {
        "status": "resolved",
        "labels": {
          "alertname": "DiskFull",
          "severity": "critical",
          "team": "infra",
          "instance": "host1"
        },
        "annotations": {
          "summary": "Disk is full",
          "description": "/var is OK"
        },
        "fingerprint": "disk-full-host1-var"
      }
    ]
  }'
```

Alertmanager receiver example:

```yaml
receivers:
  - name: incidentrelay-infra
    webhook_configs:
      - url: "https://incidentrelay.example.com/api/integrations/alertmanager"
        send_resolved: true
        http_config:
          authorization:
            type: Bearer
            credentials: "ALERTMANAGER_ROUTE_TOKEN"

route:
  receiver: incidentrelay-infra
  group_by:
    - alertname
    - instance
  group_wait: 10s
  group_interval: 1m
  repeat_interval: 30m
```

### Generic webhook route

Create a route:

```text
Name: infra-webhook
Source: webhook
Team: infra
Rotation: infra-primary
Channels: infra-mattermost
Matchers JSON: {}
Group by JSON: ["alertname", "instance"]
```

Copy the route intake token after creating the route.

Send a firing webhook alert:

```bash
curl -X POST http://127.0.0.1:8080/api/integrations/webhook \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer WEBHOOK_ROUTE_TOKEN' \
  -d '{
    "title": "Disk is full",
    "message": "/var is 95% full",
    "severity": "critical",
    "status": "firing",
    "fingerprint": "disk-full-host1-var",
    "labels": {
      "team": "infra",
      "instance": "host1",
      "alertname": "DiskFull"
    }
  }'
```

Send a resolved webhook alert:

```bash
curl -X POST http://127.0.0.1:8080/api/integrations/webhook \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer WEBHOOK_ROUTE_TOKEN' \
  -d '{
    "title": "Disk is full",
    "message": "/var is OK",
    "severity": "critical",
    "status": "resolved",
    "fingerprint": "disk-full-host1-var",
    "labels": {
      "team": "infra",
      "instance": "host1",
      "alertname": "DiskFull"
    }
  }'
```

Use the same `fingerprint` for `firing` and `resolved`.

### Zabbix route

Create a route:

```text
Name: infra-zabbix
Source: zabbix
Team: infra
Rotation: infra-primary
Channels: infra-mattermost
Matchers JSON: {}
Group by JSON: ["host", "trigger"]
```

Copy the route intake token after creating the route.

Send a Zabbix-style firing event:

```bash
curl -X POST http://127.0.0.1:8080/api/integrations/zabbix \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ZABBIX_ROUTE_TOKEN' \
  -d '{
    "event_id": "100500",
    "status": "firing",
    "severity": "high",
    "host": "host1",
    "trigger": "Disk space is low",
    "message": "/var is 95% full",
    "labels": {
      "team": "infra",
      "host": "host1",
      "trigger": "DiskSpaceLow"
    }
  }'
```

Send a Zabbix-style resolved event:

```bash
curl -X POST http://127.0.0.1:8080/api/integrations/zabbix \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer ZABBIX_ROUTE_TOKEN' \
  -d '{
    "event_id": "100500",
    "status": "resolved",
    "severity": "high",
    "host": "host1",
    "trigger": "Disk space is low",
    "message": "/var is OK",
    "labels": {
      "team": "infra",
      "host": "host1",
      "trigger": "DiskSpaceLow"
    }
  }'
```

Use the same `event_id` for `firing` and `resolved`.

### Multiple routes for one team

One team can have multiple independent intake routes:

```text
infra-alertmanager -> source alertmanager -> Alertmanager token
infra-webhook      -> source webhook      -> Generic webhook token
infra-zabbix       -> source zabbix       -> Zabbix token
```

They can all point to the same team, rotation and notification channels.

This is useful when the same on-call team receives alerts from different systems.
