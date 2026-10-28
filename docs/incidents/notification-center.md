---
title: Notification Center
description: Pending operational Incident responder requests.
---

# Notification Center

`GET /api/notification-center?limit=20` returns `items` and `unread_count` for the
current user. `limit` is 1–100. Items are pending Incident responder requests on
which the user is eligible to act; `unread_count` is the number returned, not a
separate read/unread receipt or a count of the notification delivery queue.

Each item includes its ID (`responder-request-<id>`), type `responder_request`,
title, body, timestamps, `incident_id`, the serialized `responder`, and action
descriptors. There is no embedded `incident` summary in the 2.5 response.
`url` opens `/incidents/<incident_id>`. Accept and decline actions use:

```http
PUT /api/incidents/17/responders/8
Content-Type: application/json

{"status":"accepted"}
```

Use `declined` to decline. Once the request leaves `requested` it disappears from
the list. Eligibility and state are checked again when the action is submitted;
another response or expiry can result in `409`. Reload the list after acting.

The item's top-level timestamps are currently UTC values without a guaranteed
timezone suffix; the nested responder timestamps use explicit UTC. Consumers
must not assume the top-level values are browser-local time.

See [responders](responders.md) for request and assignment rules.
