---
title: Email Channel
description: Email notification channel setup and troubleshooting.
---

# Email channel

Email is an outgoing notification channel. It sends alert notifications to the assigned user's profile email address.

Email channels do not store recipients and do not store SMTP transport settings.

## Delivery model

```text
Alert assignee -> assignee.email -> global SMTP server
```

Required data:

| Location | Required value |
|---|---|
| User profile | `email` |
| Global config | `[smtp]` settings |
| Email channel config | optional `html_template`, optional `notify_on_severities` |

If the assigned user has no email address, email delivery fails with a clear error.

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

If the SMTP server does not support AUTH, leave `user` and `password` empty.

## Channel config

Minimal email channel config:

```json
{}
```

With a custom HTML template:

```json
{
  "html_template": "<h1>{event_type}: {title}</h1><p>{message}</p>"
}
```

With severity filter:

```json
{
  "notify_on_severities": ["critical", "high"],
  "html_template": "<h1>{event_type}: {title}</h1><p>{message}</p>"
}
```

## Test button

When testing an email channel, IncidentRelay sends the test email to the current user's profile email address.

If the current user has no email address, the test returns an error telling the user to set email in their profile.

## Troubleshooting

### Test works but real alerts do not arrive

Check the real alert assignee:

- alert has an assignee;
- assigned user has an email address;
- channel is attached to the matched route;
- channel severity filter allows the alert severity;
- SMTP relay accepted and delivered the message.

### Log says `notification sent`, but mailbox is empty

The SMTP server accepted the message from IncidentRelay. Check downstream SMTP relay logs, spam quarantine, recipient policy, SPF/DMARC and mailbox rules.
