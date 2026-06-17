---
title: Telegram Channel
description: Telegram Bot notification setup and troubleshooting.
---

# Telegram channel

Telegram is an outgoing notification channel based on Telegram Bot API.

It can send alert notifications and can support inline actions when polling/callback handling is enabled.

## Required channel config

Typical config:

```json
{
  "bot_token": "123456789:AA...",
  "chat_id": "-1001234567890"
}
```

`bot_token` must contain a colon. Use BotFather to create a bot and get the token.

## Telegram worker

If Telegram actions or polling are used, run the Telegram worker service if your installation provides one:

```bash
systemctl enable --now incidentrelay-telegram-worker
```

For RPM installations:

```bash
journalctl -u incidentrelay-telegram-worker -f
```

## User Telegram ID

A user can have a Telegram user ID in their profile. This can be used for action attribution and future direct-user workflows.

## Proxy

If the server needs a proxy to reach Telegram, configure the proxy globally. Keep bot token and chat ID in the channel configuration.

## Troubleshooting

Check:

1. Token contains `:`.
2. Bot is added to the target chat or channel.
3. `chat_id` is correct.
4. Worker is running if actions are expected.
5. Proxy is configured if the server cannot reach Telegram directly.
