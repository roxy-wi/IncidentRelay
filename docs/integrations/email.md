---
title: Email Channel
description: Email notification channel setup, assignee fallback and fixed recipients.
---

# Email channel

Email is an outgoing notification channel. It uses the globally configured SMTP server, but the **recipient may be selected per Email channel**. Routes, Notification Policies, severity filtering and escalations work as before; no extra rotation is required.

## Recipient modes

Choose **Recipient mode** in the Email channel form:

| Mode | Real alert recipient | When to use |
|---|---|---|
| `assignee` (default) | Assigned user's profile `email` | Current behavior; existing channels are unchanged |
| `fallback` | Assignee email, or `recipient_email` when none is available | Simple Rotation / unassigned alerts |
| `fixed` | Always the configured `recipient_email` | Shared mailbox and parallel backup notifications |

The `recipient_email` field is **required** for `fallback` and `fixed`. Only one valid mailbox address is accepted (not a comma-separated list or display name). The address is not an SMTP credential or a separate notification policy. The channel's configuration is visible to users with channel-read access; use a team mailbox, not a sensitive personal address, when appropriate.

```text
Incoming alert -> Route / Notification Policy -> Email channel
                                          assignee -> assignee.email
                                          fallback -> assignee.email or recipient_email
                                          fixed    -> recipient_email
                                                   -> global SMTP server
```

When neither the assignee email nor a configured fallback is available, assignee-only delivery fails and is recorded as a delivery error. In `fallback` mode, a valid fallback address is always configured, so an unassigned alert can still be delivered.

**Important:** `fallback` does not detect failures of Telegram, Slack, Mattermost or other channels. For a mailbox that receives notifications alongside primary channels, choose `fixed` and attach that Email channel to the same route or Notification Policy. Neither mode implements automatic delivery failover or retries for another provider.

## Global SMTP config

Configure SMTP in the global config file:

```ini
[smtp]
host = 127.0.0.1
port = 25
from = incidentrelay@example.com
use_tls = false
user =
password =
```

For an authenticated SMTP server:

```ini
[smtp]
host = smtp.example.com
port = 587
from = incidentrelay@example.com
use_tls = true
user = incidentrelay@example.com
password = change-me
```

If the SMTP server does not support AUTH, leave `user` and `password` empty. Channel configs do not store SMTP transport credentials.

## Channel config examples

An existing channel needs no changes:

```json
{}
```

Assignee email with a fallback address:

```json
{
  "recipient_mode": "fallback",
  "recipient_email": "oncall-backup@example.com"
}
```

A fixed team mailbox with an optional severity filter and HTML template:

```json
{
  "recipient_mode": "fixed",
  "recipient_email": "ops@example.com",
  "notify_on_severities": ["critical", "high"],
  "html_template": "<h1>{event_type}: {title}</h1><p>{message}</p>"
}
```

Omitting `recipient_mode` preserves the legacy assignee-only behavior. Switching back to `assignee` removes any stored `recipient_email` from the channel config. No database migration is necessary.

## Test button

The **Test** action always sends to the **current user's profile email**, including for `fixed` and `fallback` channels. It does not send to the configured shared mailbox. This avoids surprising or unauthorized mail to a team address when someone clicks Test; it verifies SMTP and rendering, **not** that the configured fixed/fallback destination accepts mail. Test normal route delivery separately to verify recipient selection.

If the current user has no email in their profile, Test returns an error requesting that the user set one.

## Troubleshooting

### Test works but real alerts do not arrive

Check:

- the recipient mode and `recipient_email` value;
- for assignee-only mode, whether an assignee and profile email exist;
- for fallback mode, whether the assignee email is missing (otherwise fallback is not used);
- channel attachment to the route or Notification Policy;
- severity filtering and SMTP relay delivery.

### SMTP accepted the message, but mailbox is empty

Check downstream SMTP relay logs, spam quarantine, recipient policy, SPF/DMARC and mailbox rules.

For non-test deliveries the persisted notification payload records only `recipient_source`, not the recipient address.
