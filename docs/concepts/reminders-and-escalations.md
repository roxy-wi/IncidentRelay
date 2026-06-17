---
title: Reminders and Escalations
description: Reminder intervals, escalation timing and scheduler behavior.
---

# Reminders and Escalations

IncidentRelay can send repeated reminders for unacknowledged firing alerts and escalate an alert to the next on-call user after a configured number of reminders.

## Reminder interval

Reminder interval is configured on the rotation.

```text
0       disables reminders for this rotation
>= 60   enables reminders with this interval in seconds
1..59   invalid
```

Examples:

| Value | Meaning |
|---:|---|
| `0` | Do not send reminders |
| `60` | Send reminders every 60 seconds |
| `300` | Send reminders every 5 minutes |
| `900` | Send reminders every 15 minutes |

## Scheduler interval versus reminder interval

The scheduler has its own wake-up interval. That value controls how often the scheduler checks for work.

The rotation reminder interval controls whether a specific alert is due for a reminder.

These are different settings:

```text
scheduler interval       -> how often the scheduler wakes up
rotation reminder interval -> how often alerts assigned by that rotation receive reminders
```

## When reminders stop

Reminders stop when the alert is:

- acknowledged;
- resolved;
- silenced;
- no longer firing;
- assigned through a rotation with reminder interval `0`.

## Escalation after reminders

Team setting `Escalate after reminders` controls how many reminders are sent before the alert is escalated to the next on-call user.

Example:

```text
reminder_interval_seconds = 300
escalation_after_reminders = 2
```

The alert is escalated after two reminder messages if it is still unacknowledged.

If reminders are disabled with `0`, reminder-based escalation will not progress for alerts using that rotation.
