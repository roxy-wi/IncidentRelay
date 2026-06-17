---
title: Webhook-Based Notification Channels
description: Slack, Discord, Microsoft Teams and generic webhook channels.
---

# Webhook-based notification channels

Webhook-based notification channels send outgoing HTTP requests to external services.

This page covers:

```text
slack
discord
teams
webhook
```

Do not confuse outgoing webhook channels with the incoming [Generic webhook integration](generic-webhook.md).

## Slack

Slack channel uses an incoming webhook URL.

Typical config:

```json
{
  "webhook_url": "https://hooks.slack.com/services/..."
}
```

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
