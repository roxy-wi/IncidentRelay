---
title: Webhook-Based Notification Channels
description: Discord, Microsoft Teams and generic webhook channels.
---

# Webhook-based notification channels

Webhook-based notification channels send outgoing HTTP requests to external services.

This page covers:

```text
discord
teams
webhook
```

Do not confuse outgoing webhook channels with the incoming [Generic webhook integration](generic-webhook.md).

Slack also has an incoming-webhook delivery mode, but Slack configuration, Bot API actions and Socket Mode are documented separately: [Slack channel](slack.md).

## Discord

Discord channel uses a Discord webhook URL.

Typical config:

```json
{
  "webhook_url": "https://discord.com/api/webhooks/..."
}
```

## Microsoft Teams

Microsoft Teams channel uses a Teams webhook URL.

Typical config:

```json
{
  "webhook_url": "https://..."
}
```

## Generic outgoing webhook

Generic outgoing webhook sends IncidentRelay notification payloads to a custom HTTP endpoint.

Typical config:

```json
{
  "webhook_url": "https://example.com/incidentrelay/notifications"
}
```

## Severity filter

All webhook-based channels support `notify_on_severities`:

```json
{
  "webhook_url": "https://example.com/hook",
  "notify_on_severities": ["critical", "high"]
}
```
