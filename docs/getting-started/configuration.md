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

## Outbound HTTP network policy

IncidentRelay protects administrator-configured outbound HTTP requests against
server-side request forgery (SSRF). Private, loopback, link-local, multicast,
reserved and unspecified destination addresses are blocked by default.

The policy is controlled by the `[security]` section:

```ini
[security]
outbound_private_network_allowlist =
outbound_http_max_redirects = 3
outbound_http_max_response_bytes = 1048576
```

`outbound_private_network_allowlist` is a comma- or semicolon-separated list of
IPv4/IPv6 addresses and CIDR networks that IncidentRelay is explicitly allowed
to contact when they are otherwise considered private or unsafe.

Examples:

```ini
# One internal service only.
outbound_private_network_allowlist = 192.168.50.10/32
```

```ini
# Several approved internal networks/addresses.
outbound_private_network_allowlist = 10.20.0.0/16,192.168.50.10/32,fd00:1234::/48
```

A single IP may also be written without the prefix length, but `/32` for IPv4
and `/128` for IPv6 make the intended scope explicit. Prefer the narrowest
possible entries instead of allowlisting whole private address ranges.

This policy is used by the shared outbound HTTP client, including OIDC metadata
and JWKS retrieval and outgoing integrations such as generic/Teams/Discord
webhooks, Slack webhooks and Mattermost API requests. The list is not a hostname
allowlist: IncidentRelay resolves the hostname first and checks the resolved IP
addresses.

For DNS names, **every address returned by DNS must be public or explicitly
allowlisted**. If even one returned address is blocked, the request fails
closed. Redirect targets are resolved and checked again before IncidentRelay
follows them.

!!! warning "Upgrade impact in 2.1"
    IncidentRelay 2.1 enforces this policy for outbound requests. An installation
    upgraded from 1.2 can therefore lose access to an existing internal OIDC
    metadata/JWKS endpoint or outgoing integration even though its URL did not
    change. Before upgrading, resolve every internal endpoint from the
    IncidentRelay host/pod and add only the required IPs or CIDRs.

For example, if an internal identity provider resolves to `10.42.7.15`:

```ini
[security]
outbound_private_network_allowlist = 10.42.7.15/32
```

After changing this setting, restart every IncidentRelay process that can make
outbound requests.

The allowlist changes only the destination network policy. It does **not**
disable HTTPS certificate verification or trust a private certificate
authority. Internal HTTPS endpoints using a private CA must also have that CA
installed in the operating system/container trust store.

## Alert processing trace

The global Explain Trace detail level is configured in `[alerts]`:

```ini
[alerts]
explain_trace_level = full
```

Supported values are `full`, `compact` and `disabled`. `full` preserves the existing detailed trace. `compact` keeps ordered processing steps but omits `input_summary`, result payloads and per-step `data`. `disabled` stores no Alert Explain Trace rows. A global Event Orchestration rule can override this value for matching events with the `set_trace_level` action.

## Alert event history

Incoming child-alert history can be controlled independently from alert lifecycle processing:

```ini
[alerts]
event_history = full
```

Supported values are `full`, `initial` and `disabled`. `full` stores incoming child-alert `created`, `updated` and `resolved` events. `initial` stores only the initial child-alert `created` event. `disabled` stores none of those incoming child-alert history rows. Alert state updates, grouping, notifications, escalation and resolution continue normally in every mode. Operational incident timeline entries such as acknowledgements, comments, reminders, maintenance, correlations, responders and stakeholders are always preserved.

Global and service Event Orchestration can override the configured default for matching events with `set_alert_event_history`. If several matching actions set a level, the last applied action wins.


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
