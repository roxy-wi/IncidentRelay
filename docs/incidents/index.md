---
title: Incident Management
description: Incident management workflows for alerts, priorities, responders, stakeholders, comments and silences.
---

# Incident Management

IncidentRelay groups incoming signals into alert groups that act as incidents for day-to-day response.

Use this section for responder workflows:

- [Alerts and alert groups](../usage/alerts.md)
- [Incident priorities](priorities.md)
- [Incident responders](responders.md)
- [Notification Center](notification-center.md)
- [Incident stakeholders](stakeholders.md)
- [Alert comments](../usage/alert-comments.md)
- [Silences](../usage/silences.md)
- [Maintenance Windows](../concepts/maintenance-windows.md)
- [Explain Trace](explain-trace.md)

## Response model

```text
Incoming alert
  -> route match
  -> alert group / incident
  -> priority and service context
  -> assignee and responders
  -> notifications, comments, ACK and resolve
```

The assignee is the primary owner of the incident. Responders are additional people or teams requested to help. Stakeholders are people who should stay informed about incident lifecycle changes.

## Recommended reading order

1. Read [Alerts and alert groups](../usage/alerts.md) to understand grouping, lifecycle and API compatibility.
2. Read [Incident priorities](priorities.md) to understand the P1-P5 scale and automatic priority behavior.
3. Read [Incident responders](responders.md) for request, accept and decline flows.
4. Read [Notification Center](notification-center.md) for pending responder requests and user actions.
5. Read [Incident stakeholders](stakeholders.md) for lifecycle notifications and service defaults.
6. Read [Alert comments](../usage/alert-comments.md) for responder notes and handover context.
