---
title: Slack mentions and participant notifications
description: Configure Slack alert messages to ping the on-call responder, and notify users when they are added to an incident.
---

# Slack mentions and participant notifications

By default a Slack alert message shows the responsible person's name as plain text, so nobody receives a Slack notification. This page describes how to configure Slack messages to mention real users, and how users are notified when they are added to an incident as a responder or stakeholder.

Two capabilities are covered:

| Capability | Effect |
|---|---|
| Mentions in alert messages | The alert assignee and the current on-call user are rendered as `<@SLACK_USER_ID>`, so Slack pings them |
| Participant notifications | A user added as a responder or stakeholder is notified over Slack, email and browser push |

Both are additive. A Slack channel with no mention configuration renders exactly as it did before this feature existed.

---

## Prerequisites

- A working Slack channel in IncidentRelay. See [Slack channel](slack.md) for app creation, tokens and interactive actions.
- A Slack user ID on each IncidentRelay user profile that should be mentioned.
- For private participant direct messages: Bot API mode plus the `im:write` scope.
- Global SMTP configured for the email half. See [Email channel](email.md).

---

## Step 1 — Find each Slack user ID

In Slack, open the member's profile, then **More** (⋮) → **Copy member ID**.

A Slack user ID looks like:

```text
U012ABCDEF
```

IDs start with `U`, or `W` on Enterprise Grid. This is not the display name and not the `@handle`.

---

## Step 2 — Store the Slack user ID on the IncidentRelay profile

The ID must be present on the user profile, otherwise that user cannot be mentioned.

### Option A — user sets it themselves

Each user opens **Profile** and fills in the Slack user ID field.

### Option B — administrator sets it

An administrator can set `slack_user_id` when managing group users.

### Option C — populate from SSO claims

If users log in through SSO, the Slack user ID can be mapped from an identity provider claim using the SSO provider's profile claim mappings. Supported targets are:

```text
slack_user_id
telegram_user_id
mattermost_user_id
```

Important caveat: SSO fills a profile field **only when it is currently empty**, and never overwrites an existing value on later logins. If a user already has a Slack user ID, changing the claim will not update it. See [SSO](../administration/sso.md).

---

## Step 3 — Enable mentions on the Slack channel

Open the Slack channel and use the **Mentions** section of the channel form, or set the config keys directly.

| Key | Type | Default | Effect |
|---|---|---|---|
| `mention_assignee` | boolean | `false` | Renders the alert assignee as a Slack mention |
| `mention_oncall` | boolean | `false` | Adds an `On-call` field mentioning the user on call at send time |

Bot API mode example:

```json
{
  "mode": "bot_api",
  "bot_token": "xoxb-...",
  "channel_id": "C0123456789",
  "signing_secret": "...",
  "mention_assignee": true,
  "mention_oncall": true
}
```

Incoming webhook mode example:

```json
{
  "mode": "webhook",
  "webhook_url": "https://hooks.slack.com/services/...",
  "mention_assignee": true,
  "mention_oncall": true
}
```

Both flags work in either mode and produce identical mention markup.

Values must be real booleans. A quoted string is rejected at create/update:

```json
{ "mention_oncall": "true" }
```

```json
HTTP 400
{
  "error": "validation_error",
  "message": "Request validation failed"
}
```

Only a literal `true` enables a flag. Any other value, including `"true"`, `1` or `null`, is either rejected by the API or treated as disabled, so a mistyped config can never silently start pinging people.

---

## Step 4 — Attach the channel to a route

Mentions only appear in messages that are actually sent, so the channel must be attached to the route that matches your alerts, or selected by a service Notification Policy.

See [Teams, rotations and routes](../concepts/teams-rotations-routes.md) and [Notification Policies](../services/notification-policies.md).

---

## Step 5 — Verify

Send a test alert through the route and confirm the Slack message contains a mention:

```text
Assignee   = <@U012ABCDEF>
```

If the alert has a rotation with someone on call, an extra field appears:

```text
On-call    = <@U0999BOB>
```

Notification delivery is performed by the scheduler rather than inline with alert intake, so allow up to a minute after the alert is created before concluding that nothing was sent.

---

## How the on-call user is resolved

`mention_oncall` resolves the on-call user **at the moment the message is sent**, using the rotation stored on the alert group.

This means:

- reminders and escalations ping whoever is on call at that moment, not whoever was on call when the alert first fired;
- an active rotation override wins, because resolution uses the same effective on-call logic as the rest of IncidentRelay;
- if no rotation is attached, the rotation is disabled, or nobody is currently on call, the `On-call` field is omitted and the message stays valid.

---

## Mention behaviour rules

| Situation | Result |
|---|---|
| User has a valid Slack user ID | Rendered as `<@ID>`, Slack notifies the user |
| User has no Slack user ID | Rendered as the display name, exactly as before |
| Slack user ID is malformed | Rendered as the display name; never emitted as broken markup |
| Alert has no assignee | `Assignee` shows `-` |
| On-call user is also the assignee | Mentioned once, not twice; the second field falls back to the display name |
| Channel has no mention keys | Output is unchanged from before this feature |
| Mention flag set to a non-boolean | Rejected by the API at create/update |

A Slack user ID is validated against the expected Slack format before it is inserted into mention markup. This matters because the field is free text that can come from a profile form or an SSO claim, so an unvalidated value could otherwise inject Slack markup.

---

## Participant notifications

When a user is added to an incident, they are notified so that being pulled in does not go unnoticed.

> **Scope (IncidentRelay 2.3):** responder and stakeholder participant notifications are **AlertGroup-scoped** technical notifications. Canonical first-class Incident collaboration is planned for 2.5 and is kept separate from these.

| Event | Trigger |
|---|---|
| Responder added | A responder request targets a user, team, rotation or escalation policy |
| Stakeholder added | A stakeholder is added manually to an incident |

### Channels used

| Channel | Requirement |
|---|---|
| Email | The user has an email address in their profile |
| Slack | The user has a Slack user ID and the incident has a Slack channel that accepts the incident severity |
| Browser push | The user has an active browser push subscription |

The Slack channel is selected with the incident's normal notification channel resolution, so a channel restricted by `notify_on_severities` is skipped for a severity it excludes.

### Slack delivery mode

- **Bot API mode**: sent as a private direct message using `conversations.open` followed by `chat.postMessage`. This requires the `im:write` scope in addition to `chat:write`.
- **Incoming webhook mode**: a direct message is not possible. To keep the note private it is **not** posted to the shared channel by default — Slack delivery for that recipient simply fails. Enable `allow_dm_channel_fallback` on the channel to post the message in the channel (with the user mentioned) instead; the message is then visible to the whole channel.

Use Bot API mode if participant notifications must stay private.

### Asynchronous, retryable delivery

Adding a responder or stakeholder only **enqueues** the notifications; a background scheduler delivers them. Each recipient and channel is a separate persisted delivery:

- `notification_status` starts as `queued` and becomes `sent` or `failed` once every enqueued delivery for the request is terminal;
- one recipient's success does not hide another's failure — partial failures are recorded per recipient;
- transient transport errors are retried with exponential backoff up to a fixed number of attempts;
- enqueuing is idempotent, so a retried request does not send duplicates;
- a missing email address, unreachable Slack channel or absent push subscription is a skip, not a hard failure;
- inactive and soft-deleted users are skipped and are not counted as failures;
- delivery, and any delivery failure, never prevents the responder request or stakeholder from being created.

Example of a successful responder notification that still records a partial failure:

```json
{
  "notification_status": "sent",
  "notification_error": "Ivan (slack): no Slack channel configured for this incident"
}
```

### Scope notes

- Stakeholders added automatically from service default stakeholders are **not** notified on add, so incident creation does not fan out a burst of notifications. Only manual additions are notified.
- A user who adds themselves as a stakeholder is not notified.
- A stakeholder added by email address only, with no linked IncidentRelay user, is notified by email only. Slack and browser push are not attempted because there is no profile to look up.
- The added-as-stakeholder notification is separate from the lifecycle stakeholder notifications and is not controlled by the `notify_on_*` flags.

See [Responders](../incidents/responders.md) and [Stakeholders](../incidents/stakeholders.md).

---

## Audit trail

Every participant notification writes a timeline event on the incident:

| Event type | Meaning |
|---|---|
| `responder_notification_queued` | The responder notifications were enqueued for delivery |
| `responder_notification_sent` | Delivered on at least one channel; lists the channels and any partial failures |
| `responder_notification_failed` | Every channel failed; includes the per-channel error text |
| `stakeholder_added_notification_queued` | The stakeholder-added notification was enqueued for delivery |
| `stakeholder_added_notification_sent` | Delivered on at least one channel |
| `stakeholder_added_notification_failed` | Every channel failed |

Example message, where email succeeded and the other two channels did not:

```text
Responder notification sent via email (partial failures: Ivan (slack): no Slack channel configured for this incident; Ivan (browser_push): no active push subscriptions)
```

---

## Troubleshooting

### The name appears as plain text instead of a mention

Check, in order:

1. the mention flag is enabled on the channel and is a real boolean, not a string;
2. the user has a Slack user ID in their profile;
3. the Slack user ID is well formed, starting with `U` or `W`;
4. for `mention_oncall`, the alert has a rotation and somebody is currently on call.

### The `On-call` field never appears

The alert has no rotation, the rotation is disabled, or no user is on call at send time. Confirm the route or service assigns a rotation, and check the on-call calendar for coverage.

### The on-call user is mentioned but the assignee is not

Expected when both resolve to the same person. That user is deliberately mentioned only once, and the second field shows the display name.

### Nothing is delivered at all

Mentions do not change delivery. Verify the channel is enabled, attached to the matched route, and that the channel severity filter allows the alert severity. See [Notification channels](channels.md).

### Participant Slack notification fails with a missing Slack channel

The incident has no Slack channel resolved from its route or service Notification Policy. Attach a Slack channel to the route.

### Participant direct messages are posted to the channel instead

The Slack channel is in incoming-webhook mode, which cannot send direct messages. Switch to Bot API mode and grant `im:write`.

### Slack returns `missing_scope`

Add `im:write` to the bot token scopes and reinstall the Slack app.

---

## Testing on a local installation

When pointing a Slack channel at a local sink for testing rather than at Slack, note that IncidentRelay blocks outbound webhook requests to private and loopback addresses as SSRF protection. A local target fails with:

```text
outbound target resolves to a blocked network
```

For a development installation only, loopback can be allowlisted:

```ini
[security]
outbound_private_network_allowlist = 127.0.0.0/8
```

Never set this in production. It weakens SSRF protection for all administrator-configured outbound integrations.

---

## Related pages

- [Slack channel](slack.md)
- [Notification channels](channels.md)
- [Responders](../incidents/responders.md)
- [Stakeholders](../incidents/stakeholders.md)
- [Notification Policies](../services/notification-policies.md)
- [SSO](../administration/sso.md)
