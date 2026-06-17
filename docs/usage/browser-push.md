---
title: Browser Push
description: Profile-level PWA and browser push notifications for assigned users.
---

# Browser Push

Browser push notifications let users receive IncidentRelay alerts directly in a browser or installed PWA.

Browser push is **profile-level**, not a notification channel:

```text
User Profile -> Enable push on this device
Alert assigned to user -> Browser push to that user's active browser/PWA devices
```

Do not create a `browser_push` notification channel and do not attach browser push to routes. If a user enables browser push in Profile, IncidentRelay can send alert notifications to that user's active browser/PWA devices automatically when an alert is assigned to them.

## Requirements

Browser push requires:

- an HTTPS public URL for the web UI;
- a working `/service-worker.js` served from the root scope;
- VAPID public/private keys configured on the server;
- an active browser push subscription in the user's profile;
- an alert with `assignee_id` set to that user.

For local testing, browser push generally requires HTTPS, except for browser-specific localhost exceptions.

## Configuration

Add the browser push section to the main IncidentRelay config:

```ini
[browser_push]
enabled = true
vapid_public_key = CHANGE_ME_PUBLIC_KEY
vapid_private_key = /etc/incidentrelay/vapid/private_key.pem
vapid_subject = mailto:admin@example.com
action_token_ttl_seconds = 900
```

| Option | Description |
|---|---|
| `enabled` | Enables or disables browser push globally |
| `vapid_public_key` | Public VAPID key returned to the browser for `PushManager.subscribe()` |
| `vapid_private_key` | Private VAPID key or PEM file path used by the server to send Web Push messages |
| `vapid_subject` | Contact URI included in VAPID claims, usually `mailto:admin@example.com` |
| `action_token_ttl_seconds` | Lifetime of one-time ACK/Resolve action tokens embedded into push notifications |

Restart the web service after changing the config. Restart the scheduler too if alert notifications are sent by the scheduler process in your installation.

## Generate VAPID keys

One reliable option is to generate a PEM private key and a base64url public key with `py-vapid`:

```bash
mkdir -p /etc/incidentrelay/vapid

python3 - <<'PY'
from py_vapid import Vapid01
from py_vapid.utils import b64urlencode
from cryptography.hazmat.primitives import serialization

private_key_file = "/etc/incidentrelay/vapid/private_key.pem"

vapid = Vapid01()
vapid.generate_keys()
vapid.save_key(private_key_file)

public_key = b64urlencode(
    vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
)

if isinstance(public_key, bytes):
    public_key = public_key.decode("utf-8")

print("vapid_public_key = " + public_key)
print("vapid_private_key = " + private_key_file)
PY

chown -R incidentrelay:incidentrelay /etc/incidentrelay/vapid
chmod 700 /etc/incidentrelay/vapid
chmod 600 /etc/incidentrelay/vapid/private_key.pem
```

Use the printed values in the `[browser_push]` config section.

## User setup

Open:

```text
Profile
```

Then use the browser push block:

1. Enter a device name, for example `Work laptop` or `Android phone`.
2. Click `Enable push on this device`.
3. Allow notifications in the browser prompt.
4. Click `Send test push`.

The profile page lists active browser push devices. Users can disable old devices from the same page.

## Alert delivery behavior

Browser push is sent to the assigned user only:

```text
alert.assignee_id -> active browser push subscriptions for that user
```

A route does not need a browser push channel. Regular notification channels still use route-channel bindings, but browser push is automatically checked for the assigned user.

If a test push works but a real alert does not, check that:

1. The alert has an assignee.
2. The assignee is the same user who enabled push in Profile.
3. Browser push is enabled in config.
4. The subscription is enabled and not deleted.
5. The service worker is current in the user's browser.

Browser push is considered a deliverable target for reminders and escalations when the assigned user has active push subscriptions.

## ACK and Resolve buttons

Alert push notifications can include `Acknowledge` and `Resolve` actions. These buttons use short-lived one-time action tokens embedded in the notification payload.

The action endpoint is intentionally public:

```text
POST /api/push/actions
```

It does not require a personal API token or login cookie. The one-time action token authenticates the push action.

Default token lifetime:

```text
900 seconds
```

Change it with:

```ini
[browser_push]
action_token_ttl_seconds = 900
```

`token_expired` means the action token is older than `action_token_ttl_seconds`. `token_already_used` means the same notification action token was already consumed.

## Notification sound and vibration

IncidentRelay does not configure a custom audio file for browser push notifications. The browser and operating system use the default notification behavior when notifications are allowed and the device is not in silent or Do Not Disturb mode.

Push payloads should not set `silent: true` for alert notifications. Mobile browsers that support vibration can use the notification vibration pattern when available.

## Service worker updates

The service worker should be served from:

```text
/service-worker.js
```

Recommended headers:

```text
Cache-Control: no-cache, no-store, must-revalidate
Service-Worker-Allowed: /
```

When `service-worker.js` changes, increment the PWA/service worker cache version so browsers pick up the new notification click/action logic.

## API endpoints

Authenticated profile endpoints:

```text
GET    /api/profile/push/vapid-public-key
GET    /api/profile/push/subscriptions
POST   /api/profile/push/subscriptions
DELETE /api/profile/push/subscriptions/{subscription_id}
POST   /api/profile/push/test
```

Public one-time action endpoint:

```text
POST /api/push/actions
```

## Troubleshooting

### Browser push is disabled or VAPID public key is not configured

Check:

```text
GET /api/profile/push/vapid-public-key
```

Expected response:

```json
{
  "enabled": true,
  "public_key": "B..."
}
```

If `enabled` is false or `public_key` is null, fix the `[browser_push]` config and restart the service.

### Test push works but real alerts do not

Test push sends to the current profile user. Real alert push sends to `alert.assignee_id`.

Check the latest alerts:

```sql
select id, status, assignee_id, route_id, last_notification_at
from alert
order by id desc
limit 5;
```

Then check subscriptions:

```sql
select id, user_id, device_name, enabled, deleted, last_seen_at
from browser_push_subscription
order by id desc;
```

The subscription `user_id` must match the alert `assignee_id`.

### Push action returns token_expired

The one-time action token was older than `action_token_ttl_seconds` when the browser sent the action.

### Push action returns token_already_used

The same ACK/Resolve action token was already used. This can happen after a double click, browser retry, or if the user clicked the same notification action more than once.
