---
title: IncidentRelay Documentation
description: Documentation for IncidentRelay self-hosted on-call scheduling, alert routing and notification service
---

# IncidentRelay Documentation

IncidentRelay is a self-hosted on-call scheduling, alert routing and notification service. It keeps teams, rotations, routes, notification channels, browser push subscriptions, acknowledgements, resolves, reminders and escalations inside your own infrastructure.

!!! warning "Beta status"
    IncidentRelay is currently in **beta**.
    APIs, UI behavior, database schema, configuration options and packaging details may still change.

## Alert flow

```text
Monitoring system
  -> Incoming integration endpoint
  -> Route intake token
  -> Route match
  -> Service
  -> Team and rotation
  -> Assigned on-call user
  -> Notification channels and profile browser push
  -> ACK / Resolve
```

Browser push notifications are enabled by users in Profile and are delivered automatically to assigned users. They are not route channels.

## Installation paths

Choose one installation method:

| Method | Recommended for | Start here |
|---|---|---|
| Docker Compose | quick start, testing, simple self-hosted deployments | [Docker Installation](getting-started/docker.md) |
| RPM package | RHEL, Rocky Linux, AlmaLinux, CentOS Stream | [RPM Installation](getting-started/rpm-installation.md) |
| Manual systemd | source checkout, custom Python environment, classic Linux VM | [Manual systemd Installation](getting-started/systemd.md) |

All production installations should run two processes:

```text
incidentrelay             # HTTP API, UI, incoming webhooks
incidentrelay-scheduler   # reminders, escalations, periodic jobs
```

Do not run scheduler jobs inside every web worker.

## Configuration

IncidentRelay reads the config path from:

```text
INCIDENTRELAY_CONFIG_FILE
```

Example:

```bash
export INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
```

The old `ONCALL_CONFIG_FILE` name should not be used.

Read more: [Configuration](getting-started/configuration.md).

For browser/PWA notifications, configure `[browser_push]` and VAPID keys. Read more: [Browser Push Notifications](usage/browser-push.md).

## Core concepts

| Concept | Description |
|---|---|
| Group | Access boundary and group-level administration scope |
| User | Person who can log in, be on-call, receive notifications, enable browser push or use personal API tokens |
| Team | Operational unit inside a group |
| Rotation | On-call schedule for a team |
| Route | Alert routing rule with its own intake token |
| Channel | Outgoing notification target such as Mattermost, Telegram, email, webhook or voice call |
| Browser push | Profile-level browser/PWA notification delivery for assigned users |
| Alert | IncidentRelay alert created from an incoming integration |
| Silence | Rule that suppresses notifications for matching new alerts |
| Override | Temporary replacement for a rotation member |

Read more:

- [Groups and RBAC](concepts/groups-and-rbac.md)
- [Teams, Rotations and Routes](concepts/teams-rotations-routes.md)
- [Route Intake Tokens](concepts/route-intake-tokens.md)
- [Channels](concepts/channels.md)
- [Browser Push Notifications](usage/browser-push.md)
- [Reminders and Escalations](concepts/reminders-and-escalations.md)

## RBAC summary

IncidentRelay uses two permission layers:

| Layer | Purpose |
|---|---|
| Group role | Defines access boundary and group-level user administration |
| Team role | Defines what a user can do inside a specific team |

Current role names:

```text
Group roles: viewer, editor, user_admin
Team roles:  viewer, responder, manager
```

Important rules:

- A user must belong to a group before they can be added to a team in that group.
- Adding a user to a team does not add the user to the group automatically.
- `user_admin` can create users only inside the selected group boundary.
- `editor` can create teams in a group, but does not automatically manage all teams.
- `manager` is the write role for a specific team.
- `responder` can acknowledge and resolve alerts without changing team settings.

Read more: [Groups and RBAC](concepts/groups-and-rbac.md).

## Integrations

IncidentRelay has two integration layers.

### Incoming alert sources

| Source              | Endpoint                                   | Documentation                                             |
|---------------------|--------------------------------------------|-----------------------------------------------------------|
| Alertmanager        | `POST /api/integrations/alertmanager`      | [Alertmanager](integrations/alertmanager.md)              |
| AWS SNS/Cloud watch | `POST /api/integrations/aws-sns`           | [AWS SNS/Cloud watch](integrations/aws-sns-cloudwatch.md) |
| Grafana             | `POST /api/integrations/grafana`           | [Grafana](integrations/grafana.md)                        |
| RMON                | `POST /api/integrations/rmon`              | [Grafana](integrations/rmon.md)                           |
| Zabbix              | `POST /api/integrations/zabbix`            | [Zabbix](integrations/zabbix.md)                          |
| Sentry              | `POST /api/integrations/sentry/<route_id>` | [Sentry](integrations/sentry.md)                          |
| LibreNMS            | `POST /api/integrations/librenms`          | [LibreNMS](integrations/librenms.md)                      |
| Generic webhook     | `POST /api/integrations/webhook`           | [Generic webhook](integrations/generic-webhook.md)        |

Incoming integrations use route intake tokens.

### Notification delivery

| Delivery method                          | Documentation                                              |
|------------------------------------------|------------------------------------------------------------|
| Common channel behavior                  | [Notification channels](integrations/channels.md)          |
| Mattermost                               | [Mattermost](integrations/mattermost.md)                   |
| Telegram                                 | [Telegram](integrations/telegram.md)                       |
| Email                                    | [Email](integrations/email.md)                             |
| Slack                                    | [docs/integrations/slack.md](docs/integrations/slack.md)   |
| Discord, Microsoft Teams, custom webhook | [Webhook-based channels](integrations/webhook-channels.md) |
| Voice call                               | [Voice call](integrations/voice-call.md)                   |
| Browser/PWA push                         | [Browser Push Notifications](usage/browser-push.md)        |

Notification channels do not have intake tokens. Routes receive alerts, then send notifications to attached channels. Browser push is profile-level and is sent to the assigned user's active browser devices.

### Calendar sync

| Sync method | Best for | Documentation |
|---|---|---|
| CalDAV | Apple Calendar, Thunderbird, DAVx5 and other CalDAV clients | [CalDAV Calendar Sync](integrations/caldav.md) |
| ICS subscription feed | Outlook, Google Calendar and web calendar subscriptions | [ICS Calendar Feed](integrations/ics-calendar-feed.md) |

CalDAV uses personal API tokens with the `calendar:read` scope.
ICS calendar feeds use secret subscription URLs and do not require login.


## Incident management

- [Alerts and alert groups](usage/alerts.md)
- [Incident priorities](incidents/priorities.md)
- [Incident responders](incidents/responders.md)
- [Incident stakeholders](incidents/stakeholders.md)
- [Alert comments](usage/alert-comments.md)
- [Silences](usage/silences.md)
- [Maintenance Windows](concepts/maintenance-windows.md)

## Services

- [Services](concepts/services.md)
- [Service default stakeholders](services/default-stakeholders.md)

## Scheduling

- [Calendar](usage/calendar.md)
- [Rotation Layers](usage/rotation-layers.md)
- [Rotation Overrides](usage/rotation-overrides.md)
- [Teams, Rotations, Layers and Routes](concepts/teams-rotations-routes.md)

## API and automation

Swagger UI:

```text
/docs
```

OpenAPI JSON:

```text
/api/openapi.json
```

Useful pages:

- [API Overview](api/index.md)
- [Services API](api/services.md)
- [Escalation Policies API](api/escalation-policies.md)
- [Sentry Integration API](api/sentry-integration.md)
- [Profile and Personal API Tokens](usage/profile-and-tokens.md)
- [Browser Push Notifications](usage/browser-push.md)
- [Voice Call OpenAPI Notes](api/voice-call-openapi.md)

## First setup flow

```text
1. Install IncidentRelay
2. Configure the service and public_base_url
3. Configure browser push VAPID keys if browser/PWA notifications are required
4. Run migrations
5. Create the first global admin
6. Create a group
7. Create or add users to the group
8. Assign group roles: viewer, editor, user_admin
9. Create a team
10. Add group users to the team
11. Assign team roles: viewer, responder, manager
12. Create a rotation
13. Add rotation members
14. Create a service
15. Add service links and runbooks
16. Create notification channels
17. Ask users to enable browser push in Profile if required
18. Create a route and attach channels
19. Select a default service or configure service match rules
20. Copy the route intake token
21. Configure Alertmanager, Zabbix or webhook sender
22. Send a test alert
23. Acknowledge or resolve the alert
```

Read more: [First Login and Setup](getting-started/first-login.md).

## Project links

- Repository: [https://github.com/roxy-wi/IncidentRelay](https://github.com/roxy-wi/IncidentRelay)
- Swagger UI: `/docs`
- OpenAPI JSON: `/api/openapi.json`
