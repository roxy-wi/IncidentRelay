---
title: Maintenance Windows
description: Planned maintenance schedules, scopes and alert behavior control.
---

# Maintenance Windows

Maintenance Windows define planned periods when IncidentRelay should change how matching alerts are handled. A window can target a group, team, service, or route and can either suppress notifications, suppress incident creation, create a maintenance incident, or pause escalations.

## Concepts

A maintenance window is matched against incoming alerts after routing and service resolution. This means the route, team, and service are already known before IncidentRelay decides whether a maintenance window applies.

Maintenance windows are stored separately from incidents, but matching information is attached to the created alert group and child alerts through maintenance fields. In the IncidentRelay data model, an `AlertGroup` is the incident storage model.

## Scope

Each maintenance window must have at least one scope.

Supported scope types:

| Scope | Description |
| --- | --- |
| `group` | Applies to all teams, services, routes, and alerts under the group. |
| `team` | Applies to the selected team. |
| `service` | Applies to the selected service. |
| `route` | Applies to the selected alert route. |

If multiple active windows match the same alert, the repository returns the newest matching active window first, ordered by `starts_at` and then by id.

## Behaviors

Maintenance behavior controls what happens when a matching alert arrives during an active window.

| Behavior | Incident created | Incident status | Notifications | Escalation | `maintenance_suppressed` |
| --- | --- | --- | --- | --- | --- |
| `suppress_notifications` | Yes | Incoming alert status | Suppressed | Paused | `true` |
| `suppress_incident` | No | Not applicable | Not applicable | Not applicable | Not applicable |
| `create_maintenance_incident` | Yes | `maintenance` | Not suppressed by the maintenance flag | Normal unless otherwise configured | `false` |
| `pause_escalation_only` | Yes | Incoming alert status | Normal | Paused | `false` |

### `suppress_notifications`

Creates the alert group and child alert, attaches the maintenance window, and pauses the complete notification lifecycle while the window is active. This includes:

- the initial notification;
- queued group updates;
- reminders and repeats;
- user-level delayed deliveries;
- future escalation steps and escalation notifications.

Already delivered notifications remain in history and are not retracted. Missed reminders and escalation steps are not replayed after maintenance.

When the maintenance occurrence ends, a still-firing alert group schedules one normal notification or update. The reminder counter is reset, and policy escalation timing resumes from the end of maintenance using the current escalation rule.

Use this when alerts should still be visible in IncidentRelay, but responders should not be paged during planned work.

### `suppress_incident`

Does not create a new alert group for a new matching alert.

If an existing alert or group already exists, the dedup/update flow can still continue. This avoids breaking existing incident lifecycle behavior while preventing new incidents from being created during planned maintenance.

Use this when matching alerts are expected and should not appear as incidents.

### `create_maintenance_incident`

Creates an incident with status `maintenance` and attaches the maintenance window.

This does not set `maintenance_suppressed=true`. The `maintenance_suppressed` flag only means notification suppression caused by `suppress_notifications`.

Use this when maintenance alerts should be tracked explicitly as incidents.

### `pause_escalation_only`

Creates the alert group and child alert, attaches the maintenance window, and sets the next escalation time to `None`.

Use this when the incident should be visible and notifications can still be sent, but escalation should not advance while the maintenance window is active.

## Timezone behavior

`starts_at` and `ends_at` are wall-clock datetimes in the selected maintenance window timezone. They must not be converted to UTC by the frontend before sending them to the API.

Example payload for a Moscow maintenance window:

```json
{
  "starts_at": "2026-06-07T07:52:00",
  "ends_at": "2026-06-07T11:37:00",
  "timezone": "Europe/Moscow"
}
```

IncidentRelay interprets this as 07:52 to 11:37 in `Europe/Moscow`, not UTC.

The effective status is calculated dynamically from:

- `starts_at`
- `ends_at`
- `timezone`
- `rrule`
- `status`
- `enabled`
- `deleted`

Stored `status` can remain `scheduled`, while the API returns effective `status` as `active` or `finished` depending on the current time.

## Effective status

The API returns both stored and effective status:

```json
{
  "status": "active",
  "stored_status": "scheduled"
}
```

`status` is the effective status and should be used by the UI.

`stored_status` is the database value and is useful for debugging or auditing.

Status calculation rules:

| Condition | Effective status |
| --- | --- |
| `status = cancelled` | `cancelled` |
| `enabled = false` | Not considered active for matching |
| Current local time is before `starts_at` | `scheduled` |
| Current local time is between `starts_at` and `ends_at` | `active` |
| Current local time is after `ends_at` | `finished` |
| RRULE has a current occurrence | `active` |
| RRULE has a future occurrence | `scheduled` |
| RRULE has no future occurrence | `finished` |

## Recurring windows

Maintenance windows support optional RFC5545 RRULE strings in the `rrule` field.

The RRULE is stored without the `RRULE:` prefix. If the API receives the prefix, it normalizes it before storing.

Examples:

| Repeat | RRULE |
| --- | --- |
| Daily, 3 occurrences | `FREQ=DAILY;COUNT=3` |
| Weekly, 5 occurrences | `FREQ=WEEKLY;COUNT=5` |
| Monthly, 2 occurrences | `FREQ=MONTHLY;COUNT=2` |
| Every Monday | `FREQ=WEEKLY;BYDAY=MO` |

The first occurrence starts at `starts_at`. Each occurrence uses the same duration calculated from `ends_at - starts_at`.

For recurring windows, the API can return the current or next occurrence:

```json
{
  "occurrence": {
    "status": "active",
    "starts_at": "2026-06-07T07:00:00",
    "ends_at": "2026-06-07T08:00:00",
    "timezone": "Europe/Moscow",
    "recurring": true
  }
}
```

The UI should display occurrence times for recurring windows instead of only the base `starts_at` and `ends_at`.

## Alert and incident matching

Maintenance matching happens in `upsert_alert()` after route, team, service, and rotation are resolved.

The matching decision is based on:

- group id
- team id
- service id
- route id
- current time in the maintenance window timezone
- enabled/deleted/status fields

For services and routes, `active_maintenance` is dynamic. If a service or route is currently under maintenance, the serializer can return active maintenance even if no alert was created during the window.

For alerts and incidents, `active_maintenance` is attached state. Existing alert groups must not be marked as maintenance retroactively just because a new team/service/route maintenance window became active later.

Correct behavior:

| Object | `active_maintenance` source |
| --- | --- |
| Service | Dynamic lookup by current active maintenance window |
| Route | Dynamic lookup by current active maintenance window |
| Alert group / incident | Attached `maintenance_window_id` on the alert group |
| Child alert | Attached `maintenance_window_id` on the alert |

## API

### List maintenance windows

```http
GET /api/maintenance-windows?include_finished=1
```

Response:

```json
{
  "items": [
    {
      "id": 12,
      "group_id": 1,
      "group_name": "Platform",
      "team_id": 2,
      "team_name": "SRE",
      "name": "Payments deploy",
      "description": "Planned deployment",
      "status": "active",
      "stored_status": "scheduled",
      "behavior": "suppress_notifications",
      "timezone": "Europe/Moscow",
      "rrule": null,
      "starts_at": "2026-06-07T07:52:00",
      "ends_at": "2026-06-07T11:37:00",
      "occurrence": {
        "status": "active",
        "starts_at": "2026-06-07T07:52:00",
        "ends_at": "2026-06-07T11:37:00",
        "timezone": "Europe/Moscow",
        "recurring": false
      },
      "enabled": true,
      "deleted": false,
      "scopes": [
        {
          "id": 33,
          "scope_type": "service",
          "service_id": 10,
          "service_name": "payments-api"
        }
      ]
    }
  ]
}
```

### Create maintenance window

```http
POST /api/maintenance-windows
Content-Type: application/json
```

```json
{
  "name": "Payments deploy",
  "description": "Planned deployment for payments-api",
  "behavior": "suppress_notifications",
  "timezone": "Europe/Moscow",
  "starts_at": "2026-06-07T07:52:00",
  "ends_at": "2026-06-07T11:37:00",
  "enabled": true,
  "rrule": null,
  "scopes": [
    {
      "scope_type": "service",
      "service_id": 10
    }
  ]
}
```

### Update maintenance window

```http
PUT /api/maintenance-windows/{window_id}
Content-Type: application/json
```

Partial updates are supported. If `starts_at`, `ends_at`, `timezone`, `behavior`, or `rrule` are omitted, the current values are preserved.

When `scopes` is omitted, existing scopes are preserved.

```json
{
  "name": "Updated deploy",
  "description": "Deployment postponed"
}
```

To replace scopes, send `scopes` explicitly:

```json
{
  "scopes": [
    {
      "scope_type": "team",
      "team_id": 2
    }
  ]
}
```

### Cancel maintenance window

```http
POST /api/maintenance-windows/{window_id}/cancel
Content-Type: application/json
```

```json
{
  "reason": "Deployment postponed"
}
```

Cancel sets:

```text
status = cancelled
enabled = false
deleted = false
```

### Delete maintenance window

```http
DELETE /api/maintenance-windows/{window_id}
```

Delete is a soft delete and sets:

```text
deleted = true
enabled = false
```

## RBAC

Maintenance windows use write permissions for the selected scope.

| Scope | Required permission |
| --- | --- |
| `group` | Write access to the group |
| `team` | Write access to the team |
| `service` | Write access to the service team |
| `route` | Write access to the route team |

When updating a window:

- If `scopes` is provided, permissions are checked against the new scopes.
- If `scopes` is omitted, permissions are checked against the existing window owner or existing scopes.

## Audit log

Successful write actions create audit records:

| Action | Audit action |
| --- | --- |
| Create | `maintenance_window.create` |
| Update | `maintenance_window.update` |
| Cancel | `maintenance_window.cancel` |
| Delete | `maintenance_window.delete` |

Audit data includes the final maintenance window state and the request payload.

## UI behavior

The Maintenance Windows page should show:

- summary tiles
- list/table view
- status badge
- behavior
- repeat value
- current or next occurrence
- starts/ends in the selected timezone
- details panel
- create/edit modal

Timezone selection should reuse the shared `AppTimezones` helper used by rotation layers.

The frontend must send `datetime-local` values as plain wall-clock strings through `AppTimezones.normalizeDatetimeLocal()`. It must not call `new Date(value).toISOString()` for maintenance windows.

## Maintenance badges

Services and routes can show active maintenance badges dynamically.

Alert groups and incidents should show badges only when maintenance was attached at alert processing time.

Badge text should include:

- maintenance window name
- behavior label
- current or next occurrence time
- timezone

Example tooltip:

```text
Payments deploy · Suppress notifications · 07/06 07:52 — 07/06 11:37 Europe/Moscow
```

## Test coverage

Maintenance window tests should cover:

- create/update/cancel/delete
- audit records
- RBAC for service/team/route/group scopes
- timezone-aware active status
- recurring RRULE windows
- occurrence calculation
- service and route dynamic active maintenance badges
- alert group attached maintenance badges
- no retroactive marking of old alert groups
- all maintenance behaviors

Behavior matrix to keep covered:

```text
suppress_notifications:
  incident is created
  maintenance_suppressed = true
  notification queue is cleared
  reminders and user-level delayed deliveries are suppressed
  escalation is paused
  after maintenance, one normal notification/update is scheduled
  missed reminders and escalation steps are not replayed

suppress_incident:
  new incident is not created
  upsert_alert returns (None, False)

create_maintenance_incident:
  incident is created
  status = maintenance
  maintenance_suppressed = false

pause_escalation_only:
  incident is created
  next_escalation_at = None
  maintenance_suppressed = false
```

