---
title: Incident Priorities
description: P1-P5 incident priority behavior, automatic priority updates and notification output.
---

# Incident Priorities

IncidentRelay uses a P1-P5 priority scale for alert groups / incidents.

| Priority | Meaning |
|---|---|
| `p1` | P1 Critical |
| `p2` | P2 High |
| `p3` | P3 Medium |
| `p4` | P4 Low |
| `p5` | P5 Informational |

Priority is separate from alert severity. Severity describes the incoming signal. Priority describes the response importance of the incident.

## Automatic priority

When an incoming alert creates or updates an incident, IncidentRelay can resolve a priority from the alert severity.

Automatic priority changes follow conservative rules:

- a new incident gets a priority derived from the incoming alert severity;
- an automatic priority can be raised when a more important signal arrives;
- an automatic priority is not lowered by a later less important signal;
- a manually selected priority is not overwritten by incoming alert severity.

This keeps automated routing useful without losing responder intent.

## Manual priority

Responders can manually set incident priority from the incident details experience.

Manual priority changes:

- mark the priority as manually selected;
- update editable notification messages where supported;
- add timeline context;
- can notify stakeholders that requested priority-change notifications.

## Filtering and sorting

The Alerts page supports filtering by priority and sorting priority-first. Priority is also shown in alert details and dashboard summaries.

Use priority filters when a large incident list needs triage by response importance rather than by raw severity.

## Notifications

Priority is included in notification output for supported channels:

- email;
- Mattermost;
- Telegram;
- browser push.

Notification titles can include the short priority label, for example:

```text
[P1] Database unavailable
```

