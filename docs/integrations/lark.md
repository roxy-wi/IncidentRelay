---
title: Feishu / Lark
description: Send IncidentRelay notifications to Feishu or Lark custom bots
---

# Feishu / Lark

IncidentRelay can send alert notifications to a Feishu or Lark group through
a custom bot webhook. Both `open.feishu.cn` and `open.larksuite.com` webhook
URLs are supported.

## Create the custom bot

1. Open the target Feishu or Lark group.
2. Add a custom bot and copy its webhook URL.
3. Optionally enable signature verification and copy the signing secret.
4. Keep the webhook URL and signing secret private.

## Configure IncidentRelay

Create a notification channel with type **Feishu / Lark** and set:

| Field | Required | Description |
|---|---:|---|
| Webhook URL | Yes | The full custom bot URL from Feishu or Lark |
| Signing secret | No | The secret configured for signature verification |

Typical webhook hosts are:

```text
https://open.feishu.cn/open-apis/bot/v2/hook/...
https://open.larksuite.com/open-apis/bot/v2/hook/...
```

Attach the channel to a route, then use **Test** on the Channels page to verify
delivery.

## Message format

The notifier sends the rendered IncidentRelay notification as a custom bot
text message:

```json
{
  "msg_type": "text",
  "content": {
    "text": "..."
  }
}
```

When a signing secret is configured, IncidentRelay also adds the `timestamp`
and `sign` fields required by Feishu/Lark. Delivery fails when the provider
returns either an HTTP error or a non-zero application response code.

## Current limitations

The Feishu/Lark channel sends text notifications only. Interactive
ACK/Resolve/Shelve buttons and updates to previously sent messages are not
supported.

The webhook URL and signing secret are masked in API and UI responses. To keep
an existing value while editing a channel, leave the masked value unchanged.
