---
title: Incident Responders
description: Responder requests, concrete participants and conflict handling in 2.5.
---

# Responders and participants

In 2.5 both responder requests and concrete operational assignments belong to
Incident. The operational assignee is separate from the participant list.

## Request help

```http
POST /api/incidents/17/responders
Content-Type: application/json

{"target_type":"user","target_user_id":42,"message":"Check database health","expires_after_minutes":30}
```

The other target types are `team`, `rotation` and `escalation_policy`. Supply
exactly one matching `target_*_id`. `message` is at most 2,000 characters;
`expires_after_minutes`, when supplied, is 1–10,080. A successful request returns
`201` and a responder record with its target, status, actors and timestamps.
Repeated POSTs create separate requests; this endpoint has no idempotency key.

`GET /api/incidents/17/responders` lists requests. To act on one:

```http
PUT /api/incidents/17/responders/8
Content-Type: application/json

{"status":"accepted","response_message":"Investigating now"}
```

The request progresses from `requested` to `accepted`, `declined` or `expired`;
an accepted request can become `resolved`. The API checks target eligibility and
Incident access. Accepting a team/rotation/policy request records a concrete user.
Concurrent accept/expire/role operations are serialized. Repeating the same
permitted transition is idempotent; a different actor cannot take over an accepted
request. Expiration or assignment conflicts return `409`; invalid transitions
return `400`. `response_message` is limited to 2,000 characters.

[Notification Center](notification-center.md) exposes actionable pending requests.
Delivery is queued durably; email and browser push retry independently. A `201`
confirms a saved request, not that a recipient has received it. See
[delivery guarantees](stakeholders.md#delivery-and-retries).

## Assign a participant directly

```http
POST /api/incidents/17/participants
Content-Type: application/json

{"user_id":42,"role":"commander"}
```

Roles are `commander`, `responder` and `communications`. The user must be active
and belong to the Incident's group. There can be one active commander and one
active assignment per user/role pair. A user may hold different roles.
Creation returns `201`; a conflicting or
duplicate assignment returns `409`. This does not send a responder invitation.

`GET /api/incidents/17/participants` lists accepted assignments. Remove one with
`DELETE /api/incidents/17/participants/<participant_id>` (`204`). This resolves the
assignment and retains its history; repeating removal returns `404`.

Reads require Incident team read access. Writes require response access and an
authenticated actor. Participant, timeline and audit changes commit together.
Assignment does not grant the target new team access or alter technical ACK state.

## Upgrading integrations

Use Incident IDs and `/api/incidents/...` paths. The current 2.5 code does not
register the former AlertGroup responder routes. See the
[breaking API change](release-notes-2.5.md#compatibility-decision).
