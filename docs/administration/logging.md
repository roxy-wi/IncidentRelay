---
title: Logging
description: IncidentRelay logging locations, fields and troubleshooting notes.
---

# Logging

IncidentRelay writes structured JSON-style logs for alert intake, notifications, scheduler activity and errors.

## Where to look

Systemd installations:

```bash
journalctl -u incidentrelay -f
journalctl -u incidentrelay-scheduler -f
```

RPM installations use the same service names:

```bash
journalctl -u incidentrelay -f
journalctl -u incidentrelay-scheduler -f
journalctl -u incidentrelay-telegram-worker -f
```

Docker installations:

```bash
docker compose logs -f incidentrelay
docker compose logs -f incidentrelay-scheduler
```

If file logging is configured:

```bash
tail -f /var/log/incidentrelay/incidentrelay.log
```

## Useful fields

Common fields:

```text
timestamp
level
logger
message
module
function
line
```

Alert and notification fields:

```text
alert_id
team
route_id
routing_error
channel_id
channel_name
channel_type
event_type
provider
error
```

## Notification logs

`notification sent` means IncidentRelay handed the message to the downstream provider or SMTP relay without an exception. It does not guarantee final delivery.

If a user did not receive a message, check the downstream service logs as well.
