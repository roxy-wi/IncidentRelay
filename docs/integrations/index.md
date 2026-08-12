---
title: Integrations
description: Incoming alert sources and outgoing notification channels
---

# Integrations

IncidentRelay has two different integration layers. Keep them separate when configuring or troubleshooting the system.

```text
Monitoring system -> Incoming integration -> Route -> Notification channels -> User action
```

Profile-level browser push is separate from notification channels. Users enable browser/PWA push in Profile, and alerts are delivered to active browser push devices of the assigned user. Read more: [Browser Push](../usage/browser-push.md).

## Incoming alert integrations

Incoming integrations create or update alerts in IncidentRelay. They are selected by the route `source` field and require a route intake token.

| Source              | Endpoint                                   | Documentation                                             |
|---------------------|--------------------------------------------|-----------------------------------------------------------|
| Alertmanager        | `POST /api/integrations/alertmanager`      | [Alertmanager](alertmanager.md)                           |
| AWS SNS/Cloud watch | `POST /api/integrations/aws-sns`           | [AWS SNS/Cloud watch](integrations/aws-sns-cloudwatch.md) |
| Grafana             | `POST /api/integrations/grafana`           | [Grafana](grafana.md)                                     |
| Datadog             | `POST /api/integrations/datadog`           | [Datadog](datadog.md)                                     |
| Uptime Kuma         | `POST /api/integrations/uptime-kuma`       | [Uptime Kuma](uptime-kuma.md)                             |
| RMON                | `POST /api/integrations/rmon`              | [Grafana](rmon.md)                                        |
| Zabbix              | `POST /api/integrations/zabbix`            | [Zabbix](zabbix.md)                                       |
| Sentry              | `POST /api/integrations/sentry/<route_id>` | [Sentry](sentry.md)                                       |
| LibreNMS            | `POST /api/integrations/librenms`          | [LibreNMS](librenms.md)                                   |
| Generic webhook / PagerDuty Events API v2 | `POST /api/integrations/webhook` | [Generic webhook](generic-webhook.md) |

Route intake tokens belong to routes, not to channels. Create a route first, copy its intake token, and use that token in the monitoring system.

## Notification channels

Notification channels deliver alerts after a route has matched an incoming alert.

| Channel type    | Purpose                                                                        | Documentation                                 |
|-----------------|--------------------------------------------------------------------------------|-----------------------------------------------|
| Mattermost      | Chat notifications, optional ACK/Resolve buttons, message updates              | [Mattermost channel](mattermost.md)           |
| Telegram        | Telegram Bot API notifications, optional inline actions                        | [Telegram channel](telegram.md)               |
| Email           | Sends email to the assigned user's profile email                               | [Email channel](email.md)                     |
| Slack           | Incoming webhook or Bot API notifications with ACK/Resolve actions and updates   | [Slack channel](slack.md)                      |
| Discord         | Sends notifications to a Discord webhook                                       | [Webhook-based channels](webhook-channels.md) |
| Microsoft Teams | Sends notifications to a Teams webhook                                         | [Webhook-based channels](webhook-channels.md) |
| Webhook         | Sends notification payloads to a custom HTTP endpoint                          | [Webhook-based channels](webhook-channels.md) |
| Voice call      | Calls the assigned user's phone through the globally configured voice provider | [Voice call channel](voice-call.md)           |

Read the common channel behavior first: [Notification channels](channels.md).

## Common setup order

```text
1. Create a group
2. Create users and fill contact fields, such as email, phone, Telegram ID
3. Optional: configure browser push and ask users to enable it in Profile
4. Create a team
5. Create a rotation and assign on-call users
6. Create notification channels
7. Create a route and attach channels
8. Copy the route intake token
9. Configure Alertmanager, Zabbix, or webhook sender
10. Send a test alert
11. Verify notification delivery and ACK/Resolve flow
```

## Troubleshooting direction

When an alert does not notify a user through a channel, check the chain in order:

```text
Incoming payload -> route match -> route channels -> channel severity filter -> notifier -> external provider
```

For browser push, check the profile-level chain instead:

```text
alert assignee -> assignee has active browser push subscription -> service worker/browser notification
```

If a test channel notification works but real alerts do not, the issue is usually route matching, route-channel binding, severity filtering, missing assignee contact data, or a silence rule.

If the browser push test works but the real alert push does not, check that the alert is assigned to the same user who enabled push in Profile.
