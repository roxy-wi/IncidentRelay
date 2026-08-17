---
title: Voice Call Channel
description: Voice call notification channel setup and DTMF actions.
---

# Voice call channel

Voice call is an outgoing notification channel. It calls the assigned user's profile phone number through the globally configured voice provider.

## Delivery model

```text
Alert assignee -> assignee.phone -> configured voice provider
```

Required data:

| Location | Required value |
|---|---|
| User profile | `phone` |
| Global config | `[voice]` provider settings |
| Voice channel config | optional channel policy and severity filter |

## Global voice config

```ini
[voice]
provider = stub
providers_dir = /usr/local/lib/incidentrelay/voice_providers
callback_secret =
```

Custom providers are documented in [Voice Providers](../voice-providers/index.md).

## Severity filter

Use the common channel severity filter:

```json
{
  "notify_on_severities": ["critical"]
}
```

Do not use channel-specific severity keys.

## DTMF actions

A custom provider can support DTMF actions for ACK/Resolve flows. See:

- [Provider API](../voice-providers/provider-api.md)
- [Callbacks and DTMF](../voice-providers/callbacks.md)
- [Security](../voice-providers/security.md)

## Test button

The channel test uses the current user's profile phone number.

Real alert delivery uses the assigned user's profile phone number.
