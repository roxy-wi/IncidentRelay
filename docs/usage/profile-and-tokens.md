---
title: Profile and Personal API Tokens
description: User profile settings, contact fields and personal API tokens.
---

# Profile and Personal API Tokens

Open:

```text
Profile
```

The profile page contains user identity, contact fields, active group context and personal API tokens.

## Contact fields

Fill contact fields used by notification channels.

| Field | Used by |
|---|---|
| Email | Email channel |
| Phone | Voice call channel |
| Mattermost user ID | Mattermost action attribution |
| Telegram user ID | Telegram actions |
| Slack user ID | Future or external Slack workflows |

Email and voice call channels send to the assigned user's profile contact data, not to channel-level recipient lists.

## Browser push notifications

Browser push notifications are configured per user in Profile.

Use:

```text
Enable push on this device
Send test push
Disable
```

Browser push is not a notification channel. When an alert is assigned to the user, IncidentRelay can send push notifications to the user's active browser/PWA devices. ACK and Resolve buttons use short-lived one-time action tokens.

Read more: [Browser Push](browser-push.md).

## Active group

The active group controls the current group context in the UI and for group-scoped operations.

A normal user sees groups where they have active membership. A global admin can access all active groups according to global admin behavior.

## Personal API tokens

Personal tokens allow API access as the current user.

Recommended practices:

- use short-lived tokens where possible;
- restrict token usage to the needed group when the UI/API supports it;
- rotate tokens after exposure;
- delete unused tokens.
