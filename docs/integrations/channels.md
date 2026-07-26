---
title: Notification channels
description: Common behavior for IncidentRelay outgoing notification channels
---

# Notification channels

A channel is an outgoing notification target. Channels do not receive alerts directly and do not have intake tokens.

```text
Incoming alert -> Route -> Notification channels
```

A route can have one or more channels. When an alert is created or updated, IncidentRelay checks every channel attached to the matched route.

!!! note "Browser push is profile-level"
    Browser push is not a channel type. Users enable browser/PWA push in Profile, and alerts are sent to active browser push devices of the assigned user.

    Browser push does not need a route-channel binding. Read more: [Browser Push](../usage/browser-push.md).

## Delivery checks

For each channel IncidentRelay checks:

```text
1. Is the channel enabled?
2. Is the channel attached to the matched route?
3. Does notify_on_severities allow this alert severity?
4. Does the notifier have all required channel or global settings?
5. Does the assigned user have the required contact field, if the channel needs one?
```

## Supported channel types

| Type | Required channel config | User profile requirement | Global config requirement |
|---|---|---|---|
| `mattermost` | Webhook URL or Bot API settings | Optional Mattermost user ID for user attribution | `public_base_url` for buttons |
| `telegram` | `bot_token`, `chat_id` | Telegram user ID for actions | Optional Telegram proxy |
| `email` | Optional `html_template` | Assigned user must have `email` | SMTP settings |
| `slack` | Webhook mode: `webhook_url`; Bot API: `bot_token`, `channel_id`, and either `signing_secret` or `app_token` | Optional Slack user ID for action attribution | Public HTTPS endpoint for HTTP actions, or Slack worker for Socket Mode |
| `discord` | `webhook_url` | None | None |
| `teams` | `webhook_url` | None | None |
| `webhook` | `webhook_url` | None | None |
| `voice_call` | Optional notification policy | Assigned user must have `phone` | Voice provider settings |

## Severity filter

Every channel can limit which severities it receives using the canonical `notify_on_severities` key in channel config.

Example:

```json
{
  "notify_on_severities": ["critical", "high"]
}
```

If `notify_on_severities` is missing or empty, the channel receives all alert severities attached to its route.

Use canonical severity names:

```text
critical
high
medium
warning
low
info
```

IncidentRelay normalizes common incoming severity aliases before comparing them with the filter.

| Incoming value | Normalized value |
|---|---|
| `crit`, `error`, `fatal`, `disaster` | `critical` |
| `avg`, `average` | `medium` |
| `warn` | `warning` |
| `information`, `informational`, `not_classified`, `not classified` | `info` |

Do not use old or channel-specific severity fields such as `severities` or `call_on_severities`. Use `notify_on_severities` for every channel type.

## Notification updates

Some channels can update an existing notification after ACK or Resolve.

| Channel | Supports updates | Notes |
|---|---:|---|
| Mattermost Bot API | Yes | Requires Bot API mode |
| Slack Bot API | Yes | Requires stored Slack channel/message metadata |
| Telegram | Yes | Requires stored Telegram message metadata and polling for actions |
| Email | No | New email can be sent for notification events |
| Voice call | No | Calls are one-way notifications |
| Slack incoming webhook, Discord, Teams, generic webhook | No | Webhook delivery creates new messages and cannot update the original notification |

## Channel-specific pages

- [Mattermost](mattermost.md)
- [Slack](slack.md)
- [Telegram](telegram.md)
- [Email](email.md)
- [Email templates](email-channel-templates.md)
- [Webhook-based channels](webhook-channels.md)
- [Voice call](voice-call.md)

## Troubleshooting

### Channel is not called for a real alert

Check:

1. The alert has a `route_id`.
2. The channel is attached to that route.
3. The channel is enabled.
4. The alert is not silenced.
5. The channel severity filter allows the alert severity.
6. The assigned user has required contact data, such as email or phone.

### Test works but real alert does not

A channel test bypasses some of the real alert routing path.

Real alerts still require:

```text
route match -> route channel binding -> allowed severity -> assignee contact data
```

For browser push, the check is different:

```text
alert assignee -> assignee has active browser push subscription
```

Browser push test sends to the current profile user. Real alert push sends to the assigned user.

### Logs show `notification sent`, but the user did not receive it

`notification sent` means IncidentRelay handed the message to the external provider or SMTP relay without an exception. It does not guarantee final mailbox, chat or phone delivery. Check the downstream provider logs as well.
