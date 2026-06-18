---
title: Incident Responders
description: Request and manage additional responders for active incidents.
---

# Incident Responders

Incident responders are people, teams, rotations, or escalation policies explicitly requested to help with an active incident.

Responders are different from the incident assignee:

- **Assignee** is the main owner of the incident.
- **Responder** is an additional participant asked to help.
- Accepting a responder request does **not** automatically assign the incident to that user.

## Target types

A responder request can target one of these objects:

| Target type | Required field |
|---|---|
| `user` | `target_user_id` |
| `team` | `target_team_id` |
| `rotation` | `target_rotation_id` |
| `escalation_policy` | `target_escalation_policy_id` |

Only one target id must be provided for the selected `target_type`.

## Request a responder

```http
POST /api/incidents/{incident_id}/responders
```

Request body:

```json
{
  "target_type": "user",
  "target_user_id": 42,
  "message": "Please help with database checks",
  "expires_after_minutes": 30
}
```

Response:

```json
{
  "id": 15,
  "incident_id": 14784,
  "group_id": 14784,
  "target_type": "user",
  "target_user_id": 42,
  "target_team_id": null,
  "target_rotation_id": null,
  "target_escalation_policy_id": null,
  "target": {
    "type": "user",
    "id": 42,
    "label": "Alice Smith",
    "user": {
      "id": 42,
      "username": "alice",
      "display_name": "Alice Smith",
      "email": "alice@example.com"
    }
  },
  "requested_by_id": 1,
  "requested_by": {
    "id": 1,
    "username": "admin",
    "display_name": "Admin",
    "email": "admin@example.com"
  },
  "accepted_by_id": null,
  "accepted_by": null,
  "declined_by_id": null,
  "declined_by": null,
  "status": "requested",
  "message": "Please help with database checks",
  "response_message": null,
  "notification_status": "sent",
  "notification_error": null,
  "requested_at": "2026-06-17T10:00:00Z",
  "responded_at": null,
  "expires_at": "2026-06-17T10:30:00Z",
  "created_at": "2026-06-17T10:00:00Z",
  "updated_at": "2026-06-17T10:00:00Z"
}
```

## List incident responders

```http
GET /api/incidents/{incident_id}/responders
```

Returns all responder requests for the incident.

Example response:

```json
[
  {
    "id": 15,
    "incident_id": 14784,
    "group_id": 14784,
    "target_type": "user",
    "target_user_id": 42,
    "target": {
      "type": "user",
      "id": 42,
      "label": "Alice Smith",
      "user": {
        "id": 42,
        "username": "alice",
        "display_name": "Alice Smith",
        "email": "alice@example.com"
      }
    },
    "status": "requested",
    "message": "Please help with database checks",
    "response_message": null,
    "requested_at": "2026-06-17T10:00:00Z",
    "responded_at": null,
    "expires_at": "2026-06-17T10:30:00Z"
  }
]
```

## Update responder status

```http
PUT /api/incidents/{incident_id}/responders/{responder_id}
```

Request body:

```json
{
  "status": "accepted",
  "response_message": "I am joining"
}
```

Allowed statuses:

| Status | Description |
|---|---|
| `accepted` | The responder accepted the request. |
| `declined` | The responder declined the request. |
| `resolved` | The responder request was manually resolved. |
| `expired` | The responder request expired. Usually set by the scheduler. |

Example response:

```json
{
  "id": 15,
  "incident_id": 14784,
  "group_id": 14784,
  "target_type": "user",
  "target_user_id": 42,
  "target": {
    "type": "user",
    "id": 42,
    "label": "Alice Smith"
  },
  "requested_by_id": 1,
  "accepted_by_id": 42,
  "accepted_by": {
    "id": 42,
    "username": "alice",
    "display_name": "Alice Smith",
    "email": "alice@example.com"
  },
  "declined_by_id": null,
  "declined_by": null,
  "status": "accepted",
  "message": "Please help with database checks",
  "response_message": "I am joining",
  "requested_at": "2026-06-17T10:00:00Z",
  "responded_at": "2026-06-17T10:05:00Z",
  "expires_at": "2026-06-17T10:30:00Z"
}
```

## Notification center

Pending responder requests are shown in the notification center.

Read more: [Notification Center](notification-center.md).

## Permissions

Responder requests can be created by users who can respond to the incident team.

Responder status can be updated by users who can act as the target responder:

- the targeted user;
- a user allowed to respond for the targeted team;
- a user allowed to respond for the targeted rotation team;
- a user allowed to respond for the targeted escalation policy team.

A random viewer who is not the target cannot accept or decline another user's responder request.

## Timeline events

Responder actions are written to the incident timeline.

| Event type | Example message |
|---|---|
| `responder_requested` | `Responder requested: Alice Smith. Please help with this incident.` |
| `responder_accepted` | `Alice Smith accepted responder request. I am joining` |
| `responder_declined` | `Alice Smith declined responder request. Busy now` |
| `responder_expired` | `Responder request expired for Alice Smith` |

## Browser push notification

When browser push is configured for the target responder, IncidentRelay sends a push notification for the responder request.

The notification should include enough context to act without opening the incident first:

- incident title;
- priority;
- requester;
- team;
- service, when available;
- request message;
- link to the incident.

Push delivery failure does not prevent the responder request from being created. In that case `notification_status` and `notification_error` describe the delivery result.
