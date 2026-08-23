---
title: Configuration
description: IncidentRelay configuration file reference
---

# Configuration

IncidentRelay reads the config file path from:

```text
INCIDENTRELAY_CONFIG_FILE
```

Example:

```bash
export INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
```

For systemd:

```ini
Environment=INCIDENTRELAY_CONFIG_FILE=/etc/incidentrelay/incidentrelay.conf
```

For Docker Compose:

```yaml
environment:
  INCIDENTRELAY_CONFIG_FILE: /etc/incidentrelay/incidentrelay.conf
```

The old `ONCALL_CONFIG_FILE` name should not be used.

## Main and authentication secrets

Generate two different random values and keep them stable across restarts and
upgrades:

```bash
openssl rand -hex 32
openssl rand -hex 32
```

```ini
[main]
secret_key = replace-with-the-first-random-value

[auth]
jwt_secret = replace-with-the-second-random-value
jwt_cookie_secure = true
```

`secret_key` belongs to `[main]`, not `[server]`. `jwt_secret` belongs to
`[auth]`. Do not reuse the same value for both settings. Set
`jwt_cookie_secure = true` when `public_base_url` uses HTTPS.

## Server section

```ini
[server]
host = 0.0.0.0
port = 8080
public_base_url = https://incidentrelay.example.com
```

| Option | Description |
|---|---|
| `host` | Address to bind the web service to |
| `port` | HTTP port |
| `public_base_url` | External URL used in alert links, buttons and callbacks |

In production, `public_base_url` must be the real external HTTPS URL.

## Database: SQLite

```ini
[database]
type = sqlite
name = /var/lib/incidentrelay/incidentrelay.db

[sqlite]
wal = true
busy_timeout = 5000
```

SQLite is suitable for small self-hosted installations. Keep one web worker when using SQLite.

## Database: PostgreSQL

```ini
[database]
type = postgresql
host = 127.0.0.1
port = 5432
name = incidentrelay
user = incidentrelay
password = change-me
```

Use PostgreSQL for larger installations, higher alert volume, multiple web workers, or long-term production deployments.

## Alert processing trace

The global Explain Trace detail level is configured in `[alerts]`:

```ini
[alerts]
explain_trace_level = full
```

Supported values are `full`, `compact` and `disabled`. `full` preserves the existing detailed trace. `compact` keeps ordered processing steps but omits `input_summary`, result payloads and per-step `data`. `disabled` stores no Alert Explain Trace rows. A global Event Orchestration rule can override this value for matching events with the `set_trace_level` action.


## Data retention

IncidentRelay 2.1 keeps retention settings in one section:

```ini
[retention]
alert_days = 30
# explain_trace_days = 30
# orchestration_execution_days = 30
cleanup_interval_seconds = 86400
batch_size = 500
```

`alert_days = 0` is the default and keeps resolved alert history indefinitely. Explain Trace and general Event Orchestration execution retention inherit `alert_days` unless their optional override is set. See [Data Retention](../administration/data-retention.md) for deletion rules and upgrade compatibility.

## SMTP section

Email notification channels use global SMTP settings. SMTP transport is not configured per channel.

```ini
[smtp]
host = 127.0.0.1
port = 25
from = incidentrelay@example.com
use_tls = false
user =
password =
```

For an unauthenticated local relay, leave `user` and `password` empty.

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

Email notifications are sent to the assigned user's profile email address.

## Telegram proxy

If the environment requires a proxy for Telegram Bot API calls, configure it globally. Keep token values in channel configuration, not in the global config.

Example option names depend on the current service config implementation. Use the same config file for web and Telegram worker processes.

## Voice section

```ini
[voice]
provider = stub
providers_dir = /usr/local/lib/incidentrelay/voice_providers
callback_secret =
```

| Option | Description |
|---|---|
| `provider` | Voice provider name |
| `providers_dir` | Directory with custom provider modules |
| `callback_secret` | Secret used for callback validation |

Voice call notifications are sent to the assigned user's profile phone number.

## Browser push section

Browser push notifications are profile-level PWA/browser notifications. They are not configured as notification channels.

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
| `action_token_ttl_seconds` | Lifetime of one-time ACK/Resolve tokens embedded into push notifications |

After changing browser push settings, restart the web service. Restart the scheduler too if it sends notifications in your installation.

Read more: [Browser Push](../usage/browser-push.md).

## Scheduler settings

The scheduler process checks reminders, escalations and periodic jobs.

The scheduler wake-up interval is separate from rotation reminder intervals. Rotation reminder intervals are configured per rotation:

```text
0 disables reminders for that rotation
>= 60 sends reminders at that interval in seconds
1..59 invalid
```

Do not use a global reminder-after setting as a runtime fallback when rotations require an explicit interval.

## Logging

If file logging is enabled, use a writable path:

```ini
[main]
log_level = INFO
log_file = /var/log/incidentrelay/incidentrelay.log
```

For systemd and containers, also check journal or container logs.
