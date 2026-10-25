---
title: Action and audit event contract
---

# Canonical action recording

User commands, technical lifecycle events, and audit actions have distinct
contracts. For example, the HTTP/Slack/Telegram/Mattermost command `acknowledge`
produces one technical `AlertEvent(event_type="acknowledged")` on a successful
state transition and one `AuditLog(action="alert_group.ack")`. Repeated ACK
is a no-op and generates neither record. Similarly, `resolve` maps to
`resolved` and `alert_group.resolve`.

## Rules

- Every transport authenticates and authorizes an actor, then invokes the
  common service with `user_id` and a source identifier (`api`, `telegram`,
  `slack`, `mattermost`, `browser_push`, `voice`, `integration`, or `system`).
- The service records audit, not the HTTP controller. Actions performed by
  external callbacks therefore have the same audit coverage as Web UI actions.
- When the request is authenticated using a personal API token, the controller
  passes the token's database id to the domain service, including nested
  operations (Incident create/link, resolve/unshelve). The resulting audit
  record contains both `user_id` and `api_token_id`; JWT- and callback-based
  actions have `api_token_id = null`. A service never infers a token from a
  membership id or a request body.
- Persist lifecycle state, its technical event and audit record atomically
  before outgoing notifications or external provider message updates.
- Technical `AlertEvent.event_type` values describe state (`acknowledged`,
  `resolved`, `reopened`), not provider names. Provider-only duplicates
  (`telegram_acknowledged`, `telegram_resolved`) are not emitted.
- Audit action IDs use `domain.verb`, with `source` stored in audit `data`.
- Synthetic group membership `UserGroup.id` is not a resource Group ID.
  Frontend code must use `membership.group_id` for resource operations.
- Prior audit action spellings are rewritten by migration
  `20261024000001_normalize_audit_actions`; historical technical events retain
  their event names because they are a separate contract.

## Canonical audit names

| Operation | Audit action | Technical event |
|---|---|---|
| Acknowledge AlertGroup | `alert_group.ack` | `acknowledged` |
| Resolve AlertGroup | `alert_group.resolve` | `resolved` |
| Reopen AlertGroup | `alert_group.reopen` | `reopened` |
| Change AlertGroup assignee | `alert_group.assignee_change` | `assignee_changed` |
| Set/reset manual AlertGroup priority | `alert_group.priority.set` / `alert_group.priority.reset` | `priority_changed` / `priority_auto_restored` |
| Declare Incident | `incident.declare` | `incident_declared` |
| Update Incident | `incident.update` | `incident_updated` |
| Change Incident assignee | `incident.assignee_change` | `incident_assignee_changed` |
| Change Incident status | `incident.status_change` | `incident_status_changed` |
| Link/unlink AlertGroup | `incident.group_link` / `incident.group_unlink` | `incident_group_linked` / `incident_group_unlinked` |
| Reopen Incident via AlertGroup | `incident.reopen_by_alert_group` | `incident_reopened_by_alert_group` |

Internal integrations that call ACK/Resolve without an explicit source are
recorded as `system`; upstream event handlers should identify their source.

## Notification-channel callbacks

Browser Push ACK/Resolve uses the common lifecycle service and never writes
a separate provider-suffixed AuditLog row. Voice callback actions are
AlertGroup-scoped, use `UserNotificationDelivery.group_id`, and attribute
actions to `UserNotificationDelivery.user_id` only after checking responder
authorization for the owning team.

## Configuration operations (HTTP-only)

The shared lifecycle services own audit for commands available through more
than one transport. Request-only configuration CRUD uses the common
`write_audit()` helper, which derives the authenticated actor and personal
`api_token_id` from the Flask request. The trusted request origin is
`data.transport=api` (or `sso` for SSO callbacks). `data.source` may be a
domain property such as a monitoring source and must not be overwritten.
Untrusted request bodies must not supply or override `data.transport`.

Configuration action names also use `domain.verb` or
`domain.resource.verb`. Newly standardized audit actions:

- `business_service.create/update/delete/recalculate`,
  `business_service.component.create/update/delete`,
  `business_service.manual_status.set/clear`;
- `heartbeat.create/update/delete/pause/resume`,
  `heartbeat.instance.disable`, `heartbeat.token.rotate`;
- `calendar_feed.create/delete`, `calendar_feed.token.rotate`;
- `profile.notification_rule.create/update/delete`;
- `profile.push_subscription.upsert/disable`;
- `profile.password.change`, `route.channel.remove`,
  `service_impact.snapshot.create`.

Never include password values, raw calendar/heartbeat tokens, browser push
endpoints, push encryption keys, or secrets in audit metadata. Token rotation,
password changes and route-channel unlink persist mutation and audit inside
one database transaction.

Receiving a heartbeat ping, reading a calendar feed, and receiving an alert
webhook are ingestion/read paths, **not** user configuration changes. They
must not create one administrative AuditLog entry per incoming event.

## Reconciliation provenance and no-op commands (2.4 follow-up)

A direct operator request that triggers a retroactive Silence or Maintenance
reconciliation carries the *authenticated* `user_id` and personal `api_token_id`
through the reconciliation service into each affected AlertGroup/Alert audit
entry. Timeline entries also carry `user_id` where the event model supports it.
The origin is retained as `trigger_source=api`. Never derive identity from a
client-supplied payload, the configured silence/maintenance owner, or a route
intake token.

Reconciliation triggered later by the scheduler or by alert intake is
**system-owned** (`user_id` and `api_token_id` are null), even when the policy
was created by a specific user. The policy ID and `trigger_source` identify
why the change occurred without impersonating an operator.

Silence configuration mutation and its command AuditLog entry share a single
database transaction; retroactive reconciliation happens afterward in its
own lifecycle transaction so large rule applications do not hold a single
unbounded request transaction. Worker-driven repair and idempotent state checks
remain necessary when a process fails between these two phases.

Repeated Silence enable/disable commands and Heartbeat pause/resume commands
without an actual state transition do not create another command AuditLog
or heartbeat transition event. An already-reconciled Silence retained after
expiry likewise does not append duplicate retention audits on re-evaluation.
Heartbeat state checks use row locking on databases that support it.

An explicit orchestration draft validation records
`event_orchestration.draft.validate` with the valid flag and issue counts, not
rule definitions or validation messages. `POST /draft` creates an
`event_orchestration.draft.create` audit record only when a new draft version
is actually allocated; repeat requests for the existing draft are a no-op.

## Atomic command and audit boundary

Business Service configuration writes (including component mutations,
manual overrides and recalculation) commit together with their command
AuditLog entry. Mutating existing Business Services locks the parent service
row on PostgreSQL so concurrent component changes cannot interleave with
status-history recalculation. The shared status calculation also takes a row
lock and persists its history in the same transaction; SQLite uses its normal
transaction serialization instead of unsupported ``FOR UPDATE``.

Maintenance window creation, update, cancellation and deletion commit
window metadata, scopes, and the command AuditLog atomically inside their
shared service, with the authenticated `user_id` and `api_token_id` explicitly
forwarded. Retroactive reconciliation runs **after** that short transaction
commits. Reconciliation is idempotent and periodically retried by the scheduler
if immediate application fails; holding a database transaction across every
matching AlertGroup could lock arbitrarily many rows. The reconciliation
AuditLog/Timeline records the same actor on immediate operator-triggered runs,
while periodic scheduler retries remain system-owned. An audit insertion error
rolls back the configuration command, but an external-notification failure
cannot be rolled back by a database transaction.

The request-independent `record_audit()` helper is the shared implementation
of redaction, AuditLog insertion and structured logging. HTTP controllers use
`write_audit()` to resolve the authenticated request actor/token before calling
that helper. Domain services (including Maintenance) pass authenticated IDs
explicitly to `record_audit()` and must never import a Flask request proxy.

Maintenance mutations clear the previous `reconciled_at` marker inside the
command transaction. A successful immediate reconciliation or scheduler retry
sets a new timestamp, allowing operators to distinguish a changed-but-not-yet
reconciled window from one that has been fully processed.
