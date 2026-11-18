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

## User color

Each account has a stable automatic color based on its ID. In **Profile → User color**, choose a different color and save. The color is shared across avatars, comments, incident participants and stakeholders, and on-call shifts. Text uses a contrasting black or white color. Manual color choices may match another user.

The profile API accepts `color` as `#RRGGBB` and returns lowercase hex. Send `null` to restore the automatic color. Existing accounts receive their automatic color without rewriting historical records.

## Contact fields

Fill contact fields used by notification channels.

| Field | Used by |
|---|---|
| Email | Email channel |
| Phone | Voice call channel |
| Mattermost user ID | Mattermost action attribution |
| Telegram user ID | Telegram actions |
| Slack user ID | Attribution of Slack ACK/Resolve/Shelve actions; also used by Slack usergroup admin sync |

Email and voice call channels send to the assigned user's profile contact data, not to channel-level recipient lists.

## Browser push notifications

Browser push notifications are configured per user in Profile.

Use:

```text
Enable push on this device
Send test push
Disable
```

Browser push is not a notification channel. When an alert is assigned to the user, IncidentRelay can send push notifications to the user's active browser/PWA devices. ACK, Resolve, Shelve and Unshelve buttons use short-lived one-time action tokens.

Read more: [Browser Push](browser-push.md).

## Active group

The active group controls the current group context in the UI and for group-scoped operations.

A normal user sees groups where they have active membership. A global admin can access all active groups according to global admin behavior.

## Team memberships

The **Teams** section in your profile lists your current team memberships across groups, with each team's group and your role. Disabled teams are marked; deleted teams and inactive memberships are omitted. Selecting an active group does not narrow this personal list. Administrative access alone does not count as team membership.

The user details modal in **Administration → Users** shows the selected user's memberships. Group administrators see teams only within their current user-management scope. These lists are read-only; manage membership from the team page.

## Personal API tokens

Personal tokens allow API access as the current user.

Access is the intersection of the token's scopes, its Group/Team bounds and the
owner's current permissions. A global administrator's token still respects its
Group/Team bounds. These bounds also apply to resource lists, alert intake,
maintenance windows and CalDAV; CalDAV additionally requires Team membership.
Tokens belonging to inactive or deleted users are rejected.
Orchestration administration is Group-scoped and requires a token without a
Team bound, even for service orchestrations.

When a personal token creates another token through `/api/profile/tokens`, the
new token cannot gain additional scopes or switch to another Group. Omitted or
`null` Group bounds inherit the parent's Group, and Team bounds are always
inherited. The new token's expiry cannot exceed the parent's expiry. Tokens
remain independently revocable; revoking the parent does not revoke its children.

Legacy intake tokens without a user must have an explicit Group or Team bound.
Route intake tokens remain limited to their route, including when orchestration
selects a destination. Matching fingerprints in other routes do not update or
resolve that route's alerts or pending events.

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
| Change integration administration | `change-integrations:read` | `change-integrations:write` |
| System settings | `system-settings:read` | `system-settings:write` |
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

`/api/admin/change-integrations` accepts a personal API token owned by a global
administrator or an administrator of the integration's owning Group. A
Group-bound token can manage only that Group's integrations. Central integrations
and the root job administration endpoints require an unrestricted global
administrator token. Team-bound tokens cannot administer integrations.

`/api/admin/system-settings` requires a global administrator token without Group
or Team bounds. These administrative endpoints accept their dedicated scopes or
`*`; `resources:*` and `changes:*` do not grant access. Send the token as
`Authorization: Bearer <api-token>`. JWT authentication remains available to the
web UI. Machine `changes:ingest` credentials remain limited to event intake.

For Terraform automation that manages both integration configuration and system
settings, issue an unrestricted global administrator's personal token with:

```text
change-integrations:read
change-integrations:write
system-settings:read
system-settings:write
```

Reading the current state and applying changes require both read and write
scopes. When updating integration configuration, pass the `auth_revision` from
the GET response as `expected_revision`. A `409` response means the configuration
changed concurrently; read the current state and reconcile the intended change
before trying again.

API-token scope enforcement is fail closed. A protected `/api/...` endpoint
must be mapped to a scope before an API token can access it. This prevents new
API endpoints from silently becoming available to existing tokens.
