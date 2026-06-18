---
title: Services
description: Service inventory, ownership, dependencies, default stakeholders, impact and analytics.
---

# Services

Services describe the affected systems inside IncidentRelay: APIs, databases, queues, websites, infrastructure components or business services.

Use this section for service ownership and impact modeling:

- [Service model](../concepts/services.md)
- [Service default stakeholders](default-stakeholders.md)
- [Services API](../api/services.md)

## Why services matter

Routes answer how an alert entered IncidentRelay.

Services answer what system is affected.

Service context can improve:

- routing and triage;
- runbook discovery;
- owner and stakeholder visibility;
- dependency impact analysis;
- operational analytics.

## Recommended setup

1. Create services for the systems your teams operate.
2. Add ownership, links and runbooks.
3. Configure service match rules or route default services.
4. Add service default stakeholders when lifecycle notifications are useful.
5. Review service impact and analytics during incident response.
