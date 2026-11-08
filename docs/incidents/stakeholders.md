---
title: Incident Stakeholders
description: Operational subscriptions, owner snapshots and durable notification delivery in 2.5.
---

# Incident stakeholders

Stakeholders follow an operational Incident; they do not become responders or
gain permission to access it. A stakeholder is an active internal user or an
external email recipient. Creation of an Incident with a primary service copies
the service's active default stakeholders into an independent snapshot.

## API

```http
POST /api/incidents/17/stakeholders
Content-Type: application/json

{"email":"support@example.com","display_name":"Support","role":"observer"}
```

Supply exactly one non-null `user_id` or non-empty `email`. Email is trimmed and
lowercased. Email and display name are at most 255 characters. Manual roles are
`stakeholder` (default), `communications` and `observer`; inherited owner/legacy
roles remain visible in responses. Internal users must belong to the Incident's group.

- `GET /api/incidents/17/stakeholders` lists active stakeholders.
- POST returns `201` for creation or reactivation; an already active recipient
  returns `200` unchanged. Repeating POST is not an update of its role/name/flags.
- `DELETE /api/incidents/17/stakeholders/<id>` deactivates the subscription (`204`)
  and keeps its history. A repeated deletion returns `404`.

Reads require team read access; writes require Incident response access and an
authenticated actor. The public Incident API does not accept notification flags
or offer a stakeholder update endpoint. Service defaults carry their flags into
the snapshot. See [service default stakeholders](../services/default-stakeholders.md).

## Delivery and retries

Events can notify on creation, priority change, workflow status change, resolution
and operational comments, according to the snapshot flags. The actor is excluded
from their own stakeholder notification. Technical ACK/resolve and technical
comments do not stand in for these operational events.

Eligible recipients and payloads are persisted with the Incident event in one
transaction. Email and browser push have independent delivery records. External
email stakeholders receive email only. Browser push requires an active user and
usable subscriptions; stakeholder pushes are informational, without technical
ACK/resolve action buttons.

Immediate delivery is attempted after commit. The existing notification scheduler
also processes pending Incident deliveries. Failed attempts use the shared retry
policy: at most five total attempts, with 30, 60, 120 and 240 seconds before the
remaining attempts (actual execution depends on scheduler polling). A processing
claim expires after 300 seconds so another worker can recover abandoned work.

The unique event/channel/recipient key prevents duplicate queue entries. Completed
channels and successful push subscriptions are retained across retries, so a
failure elsewhere does not normally resend them. Obsolete requests or inactive
subscriptions can be skipped. Exhausted deliveries are recorded as failed.

Delivery is **at least once**, not exactly once: a process crash after provider
acceptance but before saving success can still cause a duplicate. HTTP success
does not guarantee delivery. Keep the scheduler running and inspect failed
`incident_notification_delivery` rows/logs when troubleshooting; do not log
provider credentials or push endpoints.

The current code has removed the old AlertGroup stakeholder routes. See the
[compatibility decision](release-notes-2.5.md#compatibility-decision) and
[migration procedure](collaboration-migration-2.5.md).
