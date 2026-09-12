---
title: Telegram Channel
description: Telegram Bot notification setup and troubleshooting.
---

# Telegram channel

Telegram is an outgoing notification channel based on Telegram Bot API.

It can send alert notifications and supports inline Acknowledge, Resolve, Shelve 1h and Unshelve actions when polling/callback handling is enabled.

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

## Shelving

Interactive alert messages include **Shelve 1h** for open groups and **Unshelve** while a shelf is active. The Telegram account must be linked to an IncidentRelay user with responder access to the alert team. Shelving does not change the technical alert status. See [Alert shelving](../usage/shelving.md).
