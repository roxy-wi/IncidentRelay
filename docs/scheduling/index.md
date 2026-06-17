---
title: Scheduling
description: On-call calendar, layered rotations, overrides and effective schedule behavior.
---

# Scheduling

Scheduling covers the on-call model used to assign incidents to the right responders.

Use this section for on-call schedule behavior:

- [Teams, Rotations, Layers and Routes](../concepts/teams-rotations-routes.md)
- [Calendar](../usage/calendar.md)
- [Rotation Layers](../usage/rotation-layers.md)
- [Rotation Overrides](../usage/rotation-overrides.md)

## Schedule calculation

IncidentRelay calculates the effective on-call user from rotation layers and overrides.

```text
rotation override
  -> highest-priority active layer
  -> no assignment
```

Use rotation layers for recurring schedule structure and overrides for temporary replacements.

## Calendar sync

On-call schedules can be viewed in IncidentRelay and exported to external calendar clients.

Read more:

- [CalDAV Calendar Sync](../integrations/caldav.md)
- [ICS Calendar Feeds](../integrations/ics-calendar-feed.md)

