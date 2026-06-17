---
title: Main Concepts
description: Core IncidentRelay concepts and recommended reading order.
---

# Main Concepts

IncidentRelay resources are organized around groups, teams, services, rotations, routes and channels.

| Concept           | Description                                                                    |
|-------------------|--------------------------------------------------------------------------------|
| Group             | Access boundary and group-level administration scope                           |
| User              | Person who can log in, be on-call, receive notifications or use personal API tokens |
| Team              | Operational unit inside a group                                                |
| Rotation          | On-call schedule for a team                                                    |
| Route             | Incoming alert routing rule with its own intake token                          |
| Service | Logical affected system such as API, database, queue, website or infrastructure component |
| Escalation policy | Escalation policy                                                               |
| Channel           | Outgoing notification destination                                              |
| Alert             | Alert created or updated by an incoming integration                            |
| Silence           | Temporary rule that suppresses notifications for matching new alerts           |
| Override          | Temporary replacement in a rotation                                            |

Recommended reading order:

1. [Groups and RBAC](groups-and-rbac.md)
2. [Route Intake Tokens](route-intake-tokens.md)
3. [Channels](channels.md)
4. [Reminders and Escalations](reminders-and-escalations.md)
5. [Escalation Policies](escalation-policies.md)

For domain-specific workflows, continue with:

- [Incident Management](../incidents/index.md)
- [Services](../services/index.md)
- [Scheduling](../scheduling/index.md)
