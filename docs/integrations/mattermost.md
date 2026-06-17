---
title: Mattermost Channel
description: Mattermost webhook and Bot API notification setup.
---

# Mattermost channel

Mattermost is an outgoing notification channel.

IncidentRelay supports two Mattermost delivery styles:

1. Incoming webhook mode.
2. Bot API mode with interactive buttons and message updates.

Bot API mode is recommended when you want ACK/Resolve buttons.

## Incoming webhook mode

Use this mode when you only need one-way notifications.

Typical config:

```json
{
  "webhook_url": "https://mattermost.example.com/hooks/..."
}
```

## Bot API mode

Use this mode for:

- Acknowledge button;
- Resolve button;
- message updates after ACK/Resolve;
- better user attribution.

Typical config fields:

```json
{
  "base_url": "https://mattermost.example.com",
  "bot_token": "...",
  "channel_id": "...",
  "callback_secret": "change-me"
}
```

Set `[server] public_base_url` correctly, because buttons need callback URLs that Mattermost can reach.

## Mattermost user ID

A user can have a Mattermost user ID in their profile. This is useful for attribution when the user clicks ACK/Resolve buttons.

## Test button

The channel test sends a test notification through the configured Mattermost channel. It does not prove that a real alert route will match or that severity filters will allow the alert.

## Troubleshooting

Check:

1. Channel is enabled.
2. Channel is attached to the matched route.
3. Severity filter allows the alert severity.
4. Bot token or webhook URL is correct.
5. `public_base_url` is reachable from Mattermost for buttons.
