---
title: Incident Management
description: First-class operational Incidents and technical AlertGroup boundaries in IncidentRelay 2.3.
---

# Incident Management

IncidentRelay 2.3 separates technical signal processing from operational incident response:

```text
Alert -> AlertGroup -> optional Incident
```

An AlertGroup owns grouping, source state, ACK/resolve, notification, escalation, technical assignment and technical comments. A first-class Incident owns an independent operational workflow, priority, service context and operational assignee.

An AlertGroup can exist without an Incident. An Incident can exist without an AlertGroup, and one Incident can link multiple AlertGroups without merging their technical history.

## APIs

- `/api/alert-groups` — technical AlertGroups.
- `/api/incidents` — first-class operational Incidents.
- [2.3 API migration](api-migration-2.3.md) — breaking endpoint and identifier changes.

The old `/api/incidents == AlertGroup` contract is not preserved.

## 2.3 collaboration boundary

AlertGroup technical comments remain on AlertGroup. Legacy responders and stakeholders also remain AlertGroup-scoped during 2.3 and move to canonical Incident collaboration in the staged 2.5 work.

## Recommended reading

1. [Alerts and AlertGroups](../usage/alerts.md)
2. [2.3 API migration](api-migration-2.3.md)
3. [Incident Management v2 architecture](../architecture/incident-management-v2.md)
4. [Incident priorities](priorities.md)
5. [Alert comments](../usage/alert-comments.md)
