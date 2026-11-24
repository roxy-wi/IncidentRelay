---
title: Telegram Channel
description: Telegram Bot notification setup and troubleshooting.
---

# Telegram channel

Telegram is an outgoing notification channel based on Telegram Bot API.

It can send alert notifications and supports inline Acknowledge, Resolve, Shelve and Unshelve actions when polling/callback handling is enabled. The shelve buttons come from `shelve_durations` in the `[telegram]` section (`1h` by default; `4h` and `7d` can be added).

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

## Several channels on one bot

`getUpdates` belongs to the bot token, not to a channel. Channels that use the same `bot_token` are polled once, and a button press is handled by the channel id stored in the signed callback (`ir:<action>:<alert>:<channel>:<signature>`). A press for a channel this bot does not serve is rejected and the message is not edited. Distinct bot tokens are still polled one after another.

## User Telegram ID

A user can have a Telegram user ID in their profile. Callbacks are attributed to that user. When `[telegram] dm_priorities` is set, the same id is the private chat the bot writes to. The user has to press Start in the bot once, or Telegram refuses the message. That refusal is logged and the channel post is still delivered.

## Direct messages

With `dm_priorities` empty, nothing here changes. With `dm_priorities = p1,p2`, a firing notification or reminder at those priorities also sends the assignee a private message: the alert title, a short journal, the same action buttons, and a link to the channel post. An escalation sends that message to the new assignee at any priority. Acknowledge, Resolve and Shelve from the private message update both the private message and the channel post.

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

Interactive alert messages include the configured shelve buttons ( **Shelve 1h** by default) for open groups and **Unshelve** while a shelf is active. The Telegram account must be linked to an IncidentRelay user with responder access to the alert team. Shelving does not change the technical alert status. See [Alert shelving](../usage/shelving.md).
