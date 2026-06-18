---
title: Notification Center
description: Pending responder requests and user-facing incident notifications.
---

# Notification Center

The notification center shows pending user actions related to incidents.

The current notification center includes pending incident responder requests. A responder request appears for users who are allowed to act as the target responder.

## Endpoint

```http
GET /api/notification-center
```

Example response:

```json
{
  "unread_count": 1,
  "items": [
    {
      "id": "responder-request-15",
      "type": "responder_request",
      "title": "Responder requested",
      "body": "Admin: Please help with database checks",
      "created_at": "2026-06-17T10:00:00Z",
      "expires_at": "2026-06-17T10:30:00Z",
      "url": "/alerts/14784",
      "incident_id": 14784,
      "incident": {
        "id": 14784,
        "incident_id": 14784,
        "title": "DiskFull",
        "status": "firing",
        "priority": {
          "slug": "p1"
        },
        "team_name": "Platform Team",
        "service_name": "PostgreSQL"
      },
      "responder": {
        "id": 15,
        "target": {
          "type": "user",
          "id": 42,
          "label": "Alice Smith"
        },
        "status": "requested"
      },
      "actions": [
        {
          "id": "accept",
          "label": "Accept",
          "status": "accepted",
          "method": "PUT",
          "url": "/api/incidents/14784/responders/15"
        },
        {
          "id": "decline",
          "label": "Decline",
          "status": "declined",
          "method": "PUT",
          "url": "/api/incidents/14784/responders/15"
        }
      ]
    }
  ]
}
```

## Responder request lifecycle

When a responder request is accepted, declined, resolved, or expired, it disappears from the notification center.

Read more: [Incident Responders](responders.md).

