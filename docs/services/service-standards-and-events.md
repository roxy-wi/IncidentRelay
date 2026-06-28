# Service Standards, Readiness and Catalog Events

This document describes the Service Catalog readiness model in IncidentRelay: service standards, readiness checks, the in-process catalog event adapter, and the service timeline API.

## Goals

Service Standards define what a service must have before it is considered operationally ready. A standard is applied to services by `applies_to` selectors. Readiness evaluates all standards that match a service and stores an aggregated service readiness state.

Catalog Events provide one internal entry point for service catalog changes. A view or service layer emits a domain event, and the adapter writes timeline events and runs readiness reconciliation when needed.

```text
Service/standard action
└── emit_service_catalog_event(...) or emit_group_service_catalog_event(...)
    ├── writes ServiceEvent when the event is service-scoped
    └── runs readiness reconciliation
```

`ServiceEvent` is intentionally service-scoped. Group-level changes such as standards/checks do not create a direct timeline row for every service. Instead, they trigger readiness reconciliation for the group. If a service readiness batch is created or changed, the readiness evaluator writes service timeline events.

## Main concepts

### Service Standard

A standard is a named set of readiness checks for a group.

Important fields:

| Field | Description |
| --- | --- |
| `group_id` | Group that owns the standard. |
| `slug` | Stable unique identifier inside the group. |
| `name` | Human-readable name. |
| `description` | Optional explanation. |
| `applies_to` | Selector object that decides which services the standard applies to. |
| `enabled` | Disabled standards are ignored by readiness evaluation unless explicitly listed with `include_disabled=1`. |

### `applies_to`

`applies_to` is an object. Empty object means the standard applies to all services in the group.

Supported selector keys:

| Key | Values |
| --- | --- |
| `kinds` | `technical`, `business` |
| `lifecycles` | `experimental`, `development`, `production`, `deprecated`, `retired` |
| `tiers` | `tier_1`, `tier_2`, `tier_3`, `tier_4` |
| `criticalities` | `low`, `medium`, `high`, `critical` |
| `environments` | `production`, `staging`, `development`, `testing`, `shared` |
| `service_types` | `api`, `web`, `database`, `queue`, `cache`, `worker`, `cron`, `network`, `storage`, `infrastructure`, `external`, `other` |

Example:

```json
{
  "kinds": ["technical"],
  "lifecycles": ["production"],
  "tiers": ["tier_1", "tier_2"],
  "criticalities": ["critical", "high"]
}
```

### Standard Check

A check is one requirement inside a standard.

Important fields:

| Field | Description |
| --- | --- |
| `standard_id` | Parent standard. |
| `slug` | Stable identifier inside the standard. |
| `check_type` | Built-in evaluator type. |
| `configuration` | Type-specific settings. |
| `weight` | Points contributed to the standard score, from 1 to 100. |
| `severity` | `info`, `warning`, `critical`. |
| `required` | Required failures are tracked separately. |
| `position` | Sort order in UI/evaluation output. |
| `enabled` | Disabled checks are ignored. |

Supported check types:

| Type | Purpose | Common configuration |
| --- | --- | --- |
| `field_present` | Service field must be non-empty. | `{ "field": "metadata.owner" }` |
| `field_equals` | Service field must match an expected value. | `{ "field": "environment", "value": "production" }` |
| `owner_exists` | Service must have at least one active default stakeholder. | `{}` |
| `active_rotation_exists` | Service must have a default rotation with active members. | `{}` |
| `escalation_policy_exists` | Service must have a default escalation policy. | `{ "require_rules": true }` |
| `notification_policy_exists` | Service must have a notification policy. | `{ "require_rules": true, "require_channels": true }` |
| `service_channel_exists` | Service/team must have at least one usable notification channel. | `{}` |
| `route_exists` | Service must be targeted by at least one route or service match rule. | `{}` |
| `match_rule_exists` | Service must have at least one enabled service match rule. | `{}` |
| `runbook_exists` | Service must have runbooks. | `{ "minimum": 1 }` |
| `link_type_exists` | Service must have a link of a type. | `{ "link_type": "dashboard" }` |
| `dependency_exists` | Service must have at least one dependency. | `{ "direction": "upstream" }` |
| `dependency_cycle_absent` | Service dependency graph must not contain a cycle. | `{}` |
| `metadata_value` | Service metadata key must equal a value. | `{ "key": "pci", "value": true }` |

### Readiness State

Readiness state is the current aggregate for one service.

Statuses:

| Status | Meaning |
| --- | --- |
| `ready` | Applicable checks passed. |
| `warning` | Some non-critical/non-required checks failed. |
| `not_ready` | Required or critical checks failed. |
| `not_applicable` | No enabled standards apply to this service. |
| `unknown` | Readiness was not evaluated yet or evaluation failed unexpectedly. |

The state contains score and failure counters:

```json
{
  "status": "not_ready",
  "score": 72,
  "standards_count": 1,
  "checks_count": 6,
  "failed_count": 2,
  "failed_required_count": 1,
  "failed_critical_count": 1,
  "batch_uid": "...",
  "evaluated_at": "2026-06-28T09:32:10Z"
}
```

## Built-in preset

Endpoint:

```text
POST /api/services/standards/presets/basic-operational
```

The preset creates/restores `basic-operational-readiness` for a group. It applies to production technical services and checks core operational requirements:

- active owner/default stakeholder;
- escalation policy with rules;
- notification policy with rules and channels;
- route or matching coverage;
- at least one runbook;
- dependency graph without cycles.

The preset emits a group catalog event and reconciles readiness for the group.

## Catalog event adapter

The adapter lives in:

```text
app/services/service_catalog/events.py
```

Use it instead of calling timeline and readiness functions directly from views.

### Service-scoped events

```python
emit_service_catalog_event(
    service,
    category="configuration",
    event_type="service_runbook.created",
    title="Service runbook created",
    summary=runbook.title,
    source_ref=f"service_runbook:{runbook.id}",
    external_url=runbook.url,
    actor_user=current_user(),
    payload={"runbook": service_runbook_snapshot(runbook)},
    readiness_trigger="service_runbook_created",
)
```

This writes a `ServiceEvent` row and reconciles readiness by default.

### Group-scoped events

```python
emit_group_service_catalog_event(
    group_id,
    category="readiness",
    event_type="service_standard.updated",
    title="Service standard updated",
    actor_user=current_user(),
    before=before_snapshot,
    after=after_snapshot,
    readiness_trigger="standard_updated",
)
```

This does not write a direct timeline row because `ServiceEvent` is service-scoped. It reconciles group readiness.

### Manual readiness reconciliation

```python
reconcile_service_catalog_readiness(
    service,
    trigger="manual_evaluate",
    actor_user=current_user(),
)
```

Use this for explicit `Evaluate readiness` API/UI actions when no extra domain event should be created.

### Readiness scopes

| Scope | Use case |
| --- | --- |
| `none` | Timeline event only, no readiness update. |
| `service` | Reconcile the changed service. |
| `services` | Reconcile the changed service plus explicit affected service IDs. |
| `group` | Reconcile every readable/active service in a group. |
| `dependency_component` | Reconcile services in a dependency component. |

## Event naming conventions

Use stable dotted names:

```text
service.created
service.updated
service.deleted
service_owner.created
service_owner.updated
service_owner.deleted
service_link.created
service_link.updated
service_link.deleted
service_runbook.created
service_runbook.updated
service_runbook.deleted
service_dependency.created
service_dependency.updated
service_dependency.deleted
service_dependency.downstream_created
service_dependency.downstream_updated
service_dependency.downstream_deleted
service_match_rule.created
service_match_rule.updated
service_match_rule.deleted
service_standard.created
service_standard.updated
service_standard.deleted
service_standard_check.created
service_standard_check.updated
service_standard_check.deleted
service_standard_preset.applied
readiness.evaluated
readiness.score_changed
```

Recommended categories:

| Category | Events |
| --- | --- |
| `configuration` | service, owner, link, runbook, dependency changes |
| `routing` | service match rule changes |
| `readiness` | standards, checks, readiness evaluation |
| `status` | service status updates |
| `alerting` | alert-driven future service catalog events |

## Timeline API

Endpoint:

```text
GET /api/services/{service_id}/timeline
```

Query parameters:

| Parameter | Description |
| --- | --- |
| `limit` | Number of events to return, 1..200, default 50. |
| `category` | Optional category filter. |
| `event_type` | Optional event type filter. |
| `before` | Cursor timestamp from `next_cursor.before`. |
| `before_id` | Cursor ID from `next_cursor.before_id`. |

Example response:

```json
{
  "items": [
    {
      "id": 123,
      "uid": "...",
      "service_id": 10,
      "group_id": 1,
      "team_id": 2,
      "category": "configuration",
      "event_type": "service_runbook.created",
      "title": "Service runbook created",
      "summary": "RabbitMQ cluster partition",
      "source": "incidentrelay",
      "source_ref": "service_runbook:42",
      "external_url": "https://docs.example.com/runbooks/rabbitmq",
      "actor": {
        "type": "user",
        "user_id": 7,
        "display_name": "Alice",
        "email": "alice@example.com",
        "label": null
      },
      "severity": null,
      "status": null,
      "occurred_at": "2026-06-28T09:32:10Z",
      "recorded_at": "2026-06-28T09:32:10Z",
      "schema_version": 1,
      "payload": {
        "runbook": {
          "id": 42,
          "title": "RabbitMQ cluster partition"
        }
      }
    }
  ],
  "next_cursor": {
    "before": "2026-06-28T09:32:10Z",
    "before_id": 123
  }
}
```

## API summary

### Standards

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/services/standards` | List standards visible to the user. |
| `POST` | `/api/services/standards` | Create a standard. |
| `GET` | `/api/services/standards/{standard_id}` | Get one standard with checks. |
| `PUT` | `/api/services/standards/{standard_id}` | Update a standard. |
| `DELETE` | `/api/services/standards/{standard_id}` | Soft-delete a standard. |
| `POST` | `/api/services/standards/presets/basic-operational` | Create/restore the built-in preset. |

### Checks

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/services/standards/{standard_id}/checks` | List checks. |
| `POST` | `/api/services/standards/{standard_id}/checks` | Create a check. |
| `GET` | `/api/services/standards/{standard_id}/checks/{check_id}` | Get one check. |
| `PUT` | `/api/services/standards/{standard_id}/checks/{check_id}` | Update a check. |
| `DELETE` | `/api/services/standards/{standard_id}/checks/{check_id}` | Soft-delete a check. |

### Readiness

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/services/{service_id}/readiness` | Get current readiness batch. |
| `POST` | `/api/services/{service_id}/readiness/evaluate` | Force readiness evaluation. |

### Events

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/services/{service_id}/timeline` | List service timeline events. |

## Access control

- Standards are group-scoped.
- Listing standards requires group read access.
- Creating/updating/deleting standards and checks requires group write access.
- Service readiness and timeline require read access to the service team.
- Manual readiness evaluation requires write access to the service team.

## Error responses

Common error codes:

| Error | HTTP | Meaning |
| --- | --- | --- |
| `validation_error` | 400 | Request body did not pass schema validation. |
| `service_standard_invalid` | 400 | Standard domain validation failed. |
| `service_standard_check_invalid` | 400 | Check domain validation failed. |
| `service_standard_not_found` | 404 | Standard was not found. |
| `service_standard_check_not_found` | 404 | Check was not found. |
| `service_not_found` | 404 | Service was not found. |
| `group_not_found` | 404 | Group was not found. |
| `timeline_before_invalid` | 400 | Timeline cursor timestamp is not valid ISO 8601. |

## Implementation checklist

- Use `emit_service_catalog_event()` for service-scoped changes.
- Use `emit_group_service_catalog_event()` for standard/check/preset changes.
- Use `reconcile_service_catalog_readiness()` for manual evaluation without a separate domain event.
- Keep `write_audit(...)` in views as the security/API audit log.
- Do not write group-level standard events directly into every service timeline.
- Add snapshots to `app/services/service_catalog/snapshots.py` when introducing a new catalog object type.
