---
title: Event Orchestration API
description: Create, version, validate, simulate, publish and observe Event Orchestration rules through the IncidentRelay API.
---

# Event Orchestration API

Event Orchestration is the versioned event-processing layer between integration normalizers and the existing alert lifecycle.

The generated OpenAPI document is available at `/api/openapi.json`, and Swagger UI is available at `/docs`.

For a UI-first explanation, safe rollout procedure and practical examples, read the [Event Orchestration user guide](../usage/event-orchestration.md).

## Authentication and permissions

All control-plane endpoints require a JWT or personal API token:

```http
Authorization: Bearer <token>
```

Effective access is scoped to the orchestration group:

| Group role | Access |
| --- | --- |
| `viewer` | Read orchestrations, versions and executions |
| `editor` | Read, create, edit, validate, simulate, replay, publish and rollback |
| `user_admin` | Read orchestrations and executions |
| Global administrator | All permissions, including delete and webhook-action management |

Every orchestration response includes a `permissions` object so clients can hide actions the current principal cannot execute.

## Lifecycle

A new orchestration starts disabled and has one editable draft.

```text
Create -> edit draft -> validate -> simulate -> publish
                                      |
                                      +-> immutable version
```

Published versions are immutable. A rollback copies a historical definition into a new version and publishes that new version; it never edits the historical row.

Main endpoints:

```text
GET    /api/event-orchestrations
POST   /api/event-orchestrations
GET    /api/event-orchestrations/{orchestration_id}
PATCH  /api/event-orchestrations/{orchestration_id}
DELETE /api/event-orchestrations/{orchestration_id}

POST   /api/event-orchestrations/{orchestration_id}/draft
PUT    /api/event-orchestrations/{orchestration_id}/draft
POST   /api/event-orchestrations/{orchestration_id}/validate
POST   /api/event-orchestrations/{orchestration_id}/publish
POST   /api/event-orchestrations/{orchestration_id}/rollback
PATCH  /api/event-orchestrations/{orchestration_id}/runtime

GET    /api/event-orchestrations/{orchestration_id}/versions
GET    /api/event-orchestrations/{orchestration_id}/versions/{version_id}
POST   /api/event-orchestrations/{orchestration_id}/simulate
POST   /api/event-orchestrations/{orchestration_id}/replay
GET    /api/event-orchestrations/{orchestration_id}/executions
GET    /api/event-orchestrations/{orchestration_id}/shadow-metrics
```

The editor catalog endpoint returns group-scoped services, teams, routes, policies, normalizer sources, webhook actions and effective permissions:

```text
GET /api/event-orchestrations/catalog?group_id=1
```

## Create an orchestration

A service-scoped orchestration requires `service_id`. A global orchestration must not specify one.

```json
{
  "group_id": 1,
  "name": "Production routing",
  "description": "Normalize production alerts before lifecycle processing",
  "scope": "global",
  "compatibility_mode": "hybrid"
}
```

## Conditions

A condition tree is either one leaf condition or one logical group:

```json
{
  "all": [
    {
      "field": "labels.environment",
      "operator": "equals",
      "value": "production"
    },
    {
      "any": [
        {
          "field": "event.severity",
          "operator": "equals",
          "value": "critical"
        },
        {
          "field": "labels.priority",
          "operator": "in",
          "value": ["p1", "p2"]
        }
      ]
    }
  ]
}
```

Logical keys are:

- `all` — AND;
- `any` — OR;
- `none` — NOT: none of its children may match.

The OpenAPI `OrchestrationCondition` schema contains the exact operator enum supported by the running release.

## Actions

Rules execute deterministic built-in actions. They can mutate event fields and labels, extract variables, select routing and policies, change grouping, suppress/drop/pause processing, add notes or enqueue a configured webhook.

Example draft:

```json
{
  "rules": [
    {
      "name": "Route critical production alerts",
      "enabled": true,
      "condition_tree": {
        "all": [
          {
            "field": "labels.environment",
            "operator": "equals",
            "value": "production"
          },
          {
            "field": "event.severity",
            "operator": "equals",
            "value": "critical"
          }
        ]
      },
      "actions": [
        {"type": "set_team", "team_id": 4},
        {"type": "set_priority", "value": "P1"},
        {"type": "set_label", "name": "orchestrated", "value": "true"}
      ],
      "processing_mode": "continue",
      "children": []
    }
  ],
  "comment": "Route critical production alerts"
}
```

Arbitrary shell, Python, SSH and container execution are not supported.

## Validate, simulate and publish

Validation checks the current draft:

```text
POST /api/event-orchestrations/{orchestration_id}/validate
```

Simulation accepts either one normalized event or one raw integration payload. It does not create alerts, change production state or execute webhooks.

```json
{
  "normalized_event": {
    "source": "webhook",
    "title": "Database unavailable",
    "severity": "critical",
    "labels": {"environment": "production"}
  },
  "compare_with_active": true
}
```

Publishing creates an immutable version:

```json
{
  "comment": "Reviewed and ready for production",
  "confirm_catch_all_drop": false
}
```

Catch-all drop rules require explicit confirmation.

## Author metadata

Version responses distinguish the people involved:

- `created_by` — created the version row;
- `updated_by` — last changed the draft definition;
- `published_by` — published the immutable version.

Each field has a matching `*_id` value. User objects contain `id`, `username`, optional `display_name` and a display-ready `label`.

## Runtime modes

```json
{
  "mode": "shadow",
  "compatibility_mode": "hybrid"
}
```

Runtime modes:

- `disabled` — orchestration does not run;
- `shadow` — decisions are recorded but cannot change production behavior;
- `active` — published decisions are applied.

A published version is required before `shadow` or `active` can be enabled.

## Webhook actions

Reusable webhook actions use a separate API:

```text
GET    /api/orchestration-webhook-actions?group_id=1
POST   /api/orchestration-webhook-actions
PATCH  /api/orchestration-webhook-actions/{action_id}
DELETE /api/orchestration-webhook-actions/{action_id}
GET    /api/orchestration-webhook-actions/{action_id}/executions
```

Secret `headers` are write-only. IncidentRelay encrypts them and never returns them in API responses. Execution records expose only redacted response excerpts and safe error text.
