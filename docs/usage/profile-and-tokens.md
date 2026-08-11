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
| Slack user ID | Attribution of Slack ACK/Resolve actions; also used by Slack usergroup admin sync |

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

### Token scopes

A token can contain any combination of granular scopes. Use `:read` scopes for
reporting and read-only integrations, and add the corresponding `:write` scope
only when the integration must modify that resource.

| Resource | Read | Write |
|---|---|---|
| Alerts | `alerts:read` | `alerts:write` |
| Incidents | `incidents:read` | `incidents:write` |
| Services, including Business Services | `services:read` | `services:write` |
| Teams | `teams:read` | `teams:write` |
| Groups | `groups:read` | `groups:write` |
| Users | `users:read` | `users:write` |
| Rotations and on-call health | `rotations:read` | `rotations:write` |
| Calendar | `calendar:read` | `calendar:write` |
| Routes | `routes:read` | `routes:write` |
| Channels | `channels:read` | `channels:write` |
| Maintenance windows and silences | `maintenance:read` | `maintenance:write` |
| Heartbeats | `heartbeats:read` | `heartbeats:write` |
| Escalation, notification, priority and matcher policies | `policies:read` | `policies:write` |
| Event orchestrations | `orchestrations:read` | `orchestrations:write` |
| Audit log | `audit:read` | — |
| SSO administration | `sso:read` | `sso:write` |
| Current profile and personal notification settings | `profile:read` | `profile:write` |

For example, a read-only reporting token that joins alerts with service,
incident and team metadata can use:

```text
alerts:read
services:read
incidents:read
teams:read
```

`resources:read` and `resources:write` are legacy aggregate scopes. They remain
supported for existing clients and imply the corresponding granular resource
scopes, but new integrations should prefer granular scopes.

`*` grants every configured scope and is available to global admins only.
Write scopes do not automatically imply read scopes; select both when a client
needs both operations.

API-token scope enforcement is fail closed. A protected `/api/...` endpoint
must be mapped to a scope before an API token can access it. This prevents new
API endpoints from silently becoming available to existing tokens.
