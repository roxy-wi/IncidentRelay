---
title: Channels
description: Notification channel concepts
---

# Channels

A channel is an outgoing notification destination.

Supported channel types:

```text
mattermost
telegram
slack
webhook
discord
teams
email
voice_call
```

Browser push is intentionally not listed here. It is profile-level: users enable it in Profile, and IncidentRelay sends push notifications to active browser/PWA devices of the assigned user.

Read more: [Browser Push](../usage/browser-push.md).

Channels do not have alert intake tokens. A route receives alerts through its route intake token and then sends notifications to one or more channels.

```text
Incoming alert -> Route -> Notification channels
```

## Channel severity filter

A channel can limit which alert severities it receives using `notify_on_severities`:

```json
{
  "notify_on_severities": ["critical", "high"]
}
```

If the key is missing or empty, the channel receives all severities attached to its route.

Use canonical severity names:

```text
critical
high
medium
warning
low
info
```

## Channels that require user contact fields

Some channels send notifications directly to the assigned user.

| Channel | Required user profile field |
|---|---|
| `email` | `email` |
| `voice_call` | `phone` |

For channel tests, IncidentRelay should use the current user's matching profile field.

## Channels that support actions

Some channels can support ACK/Resolve actions from the message itself.

| Channel | Action support |
|---|---|
| Mattermost Bot API | ACK/Resolve buttons and message updates |
| Slack Bot API | ACK/Resolve buttons and message updates through HTTP actions or Socket Mode |
| Telegram | Inline actions and message updates |
| Voice call | DTMF actions if provider supports callbacks |
| Email | No interactive actions |
| Slack incoming webhook, Discord, Teams, generic webhook | One-way notification only |

Browser push notifications can also include ACK/Resolve actions, but browser push is profile-level and is not configured as a channel.

Read more in [Notification channels](../integrations/channels.md).
