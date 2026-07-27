# Event Orchestration v1

**Status:** Proposed  
**Target:** Production-ready first release  
**Project:** IncidentRelay  
**Document path:** `docs/architecture/event-orchestration-v1.md`

## 1. Purpose

Event Orchestration v1 introduces a unified, versioned rule engine that processes normalized events before they enter the existing IncidentRelay alert lifecycle.

The goal is to combine routing, event mutation, service selection, priority selection, escalation decisions, notification decisions, grouping, suppression, delayed activation, and safe automation into one explainable execution pipeline.

This is not a minimal proof of concept. The first version must be safe enough for production use and structured so that stateful AIOps features can be added later without replacing the core model.

## 2. Current problem

IncidentRelay already has many orchestration building blocks:

- integration normalizers;
- route matchers;
- service match rules;
- matcher presets;
- priority policies;
- notification policies;
- escalation policies;
- silences;
- maintenance windows;
- configurable grouping and deduplication;
- dependency correlation;
- Explain traces.

These mechanisms are configured separately and execute in a mostly fixed order. A user cannot currently describe one complete decision flow such as:

> If the event comes from production, extract the service name, route it to the owning team, increase severity, select a critical escalation policy, group by service and environment, pause transient failures for two minutes, and run a diagnostics webhook.

Event Orchestration v1 provides this unified flow.

## 3. Goals

The first production release must provide:

1. Global and service-scoped orchestration.
2. Immutable published versions and editable drafts.
3. Nested condition trees with AND, OR, and NOT semantics.
4. Ordered rules with explicit flow control.
5. Variable extraction and safe templates.
6. Event mutation.
7. Dynamic group, team, route, service, policy, and priority selection.
8. Rule-driven grouping and deduplication.
9. Distinct `continue`, `stop`, `suppress`, `drop`, and `pause` outcomes.
10. True delayed activation for paused events.
11. Safe asynchronous webhook actions.
12. Simulation, replay, shadow mode, and detailed execution traces.
13. A visual rule builder.
14. Compatibility with the existing IncidentRelay lifecycle and legacy policies.
15. Public API and OpenAPI documentation.

## 4. Non-goals for v1

The following are intentionally deferred:

- cache variables shared between independent events;
- rate, frequency, distinct-count, sequence, and absence conditions;
- arbitrary graph recombination;
- machine-learning grouping;
- arbitrary Python, shell, SSH, or container execution;
- native AWX, Rundeck, Kubernetes Job, or Terraform actions;
- bidirectional Jira or ServiceNow workflows;
- automatic conversion of every advanced PagerDuty orchestration rule;
- long-term storage of dropped raw payloads;
- replacing integration-specific normalizers.

These features may be introduced after the stateless orchestration model is stable.

## 5. Processing architecture

The target processing pipeline is:

```text
Incoming payload
    ↓
Integration authentication
    ↓
Integration normalizer
    ↓
Global Orchestration
    ├── mutate normalized event
    ├── extract variables
    ├── choose group/team/route/service
    ├── set grouping and policies
    └── continue/suppress/drop/pause
    ↓
Service Orchestration
    ├── mutate event
    ├── set priority/severity
    ├── select escalation/notification policy
    ├── enqueue webhook actions
    └── continue/suppress/drop/pause
    ↓
Existing IncidentRelay lifecycle
    ↓
Alerts, incidents, escalation, notifications, correlation and impact
```

The orchestration engine must not replace the existing alert lifecycle. It produces a final decision and a mutated normalized event that are consumed by the existing lifecycle.

## 6. Execution context

The engine operates on an immutable-style context. Each action returns an updated context rather than mutating unrelated global state.

Suggested result model:

```python
OrchestrationResult(
    normalized_event={},
    variables={},
    provenance={},
    group_id=None,
    team_id=None,
    route_id=None,
    service_id=None,
    priority_id=None,
    escalation_policy_id=None,
    notification_policy_id=None,
    group_by=None,
    dedup_key=None,
    disposition="continue",
    pause_seconds=None,
    suppress_reason=None,
    drop_reason=None,
    action_requests=[],
    trace=[],
)
```

Allowed dispositions:

```text
continue
stop
suppress
drop
pause
```

`stop` stops further orchestration evaluation but still sends the current result into the normal lifecycle.

## 7. Domain model

### 7.1 EventOrchestration

```text
id
group_id
name
description
scope                  global | service
service_id             nullable for global scope
enabled
mode                   active | shadow | disabled
active_version_id
created_by
created_at
updated_at
deleted_at
```

Rules:

- a global orchestration is owned by one IncidentRelay group;
- a service orchestration is attached to one service;
- only one published version is active at a time;
- shadow mode evaluates rules but does not apply the result.

### 7.2 EventOrchestrationVersion

```text
id
orchestration_id
version_number
status                 draft | published | archived
definition_hash
comment
created_by
published_by
created_at
published_at
```

Rules:

- published versions are immutable;
- editing an active orchestration creates or updates a draft;
- publication atomically replaces the active version;
- rollback republishes a previous version as a new version or atomically restores it according to the implementation decision;
- every execution stores the exact version ID.

### 7.3 EventOrchestrationRule

A normalized relational representation may be used, but the complete version must also be exportable as one deterministic JSON definition.

Suggested fields:

```text
id
version_id
parent_rule_id
position
name
description
enabled
condition_tree_json
actions_json
processing_mode
created_at
updated_at
```

Processing modes:

```text
continue
stop
evaluate_children
children_then_continue
```

### 7.4 OrchestrationIntakeToken

```text
id
orchestration_id
name
token_hash
enabled
last_used_at
created_by
created_at
revoked_at
```

Global intake tokens are not tied to one existing route. They authorize the global orchestration, which then chooses the target route/team/service.

### 7.5 PendingOrchestratedEvent

Used by true pause semantics:

```text
id
group_id
orchestration_id
orchestration_version_id
route_id
service_id
dedup_key
normalized_event_json
context_json
activation_at
status                 pending | activated | resolved | cancelled | failed
created_at
updated_at
resolved_at
activated_at
```

### 7.6 OrchestrationExecution

```text
id
group_id
orchestration_id
version_id
source
integration_name
event_fingerprint
disposition
matched_rule_count
duration_ms
trace_json
alert_id
alert_group_id
created_at
expires_at
```

Dropped event traces must have a configurable short retention period and must redact secrets.

### 7.7 OrchestrationWebhookAction

```text
id
group_id
name
description
url
method
headers_encrypted
body_template
timeout_seconds
retry_count
private_network_policy
enabled
created_by
created_at
updated_at
```

### 7.8 AutomationExecution

```text
id
action_id
orchestration_execution_id
alert_group_id
rule_id
status                 pending | running | succeeded | failed | cancelled
attempts
request_metadata_json
response_status
response_excerpt_safe
error_safe
created_at
started_at
finished_at
```

## 8. Condition language

Conditions must support nested trees.

Example:

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
          "field": "severity",
          "operator": "in",
          "value": ["critical", "high"]
        },
        {
          "field": "labels.customer_tier",
          "operator": "equals",
          "value": "enterprise"
        }
      ]
    }
  ]
}
```

Required logical nodes:

```text
all
any
none
```

Required operators:

```text
equals
not_equals
contains
not_contains
starts_with
ends_with
regex
not_regex
in
not_in
exists
not_exists
greater_than
less_than
greater_or_equal
less_or_equal
is_true
is_false
```

Supported data sources:

```text
event.*
labels.*
raw.*
variables.*
route.*
service.*
team.*
integration.*
time.*
result.*
```

The evaluator must:

- have deterministic type coercion;
- never execute arbitrary code;
- limit regex complexity and input size;
- return structured reasons for both matches and mismatches;
- record condition results in Explain trace;
- validate field references before publication where possible.

## 9. Variable extraction

Required extraction actions:

```text
extract_regex
copy_field
json_path
split
set_variable
lowercase
uppercase
trim
```

Example:

```json
{
  "type": "extract_regex",
  "source": "event.title",
  "pattern": "^\\[(?<environment>[^]]+)\\]\\[(?<service>[^]]+)\\]"
}
```

Result:

```json
{
  "variables": {
    "environment": "prod",
    "service": "payments"
  }
}
```

Extraction failures must support configurable behavior:

```text
continue
stop_rule
stop_orchestration
```

## 10. Template language

Templates must use a restricted interpolator rather than unrestricted Jinja or Python evaluation.

Examples:

```text
{{ event.title }}
{{ labels.environment }}
{{ variables.service }}
{{ service.name }}
```

Required filters:

```text
lower
upper
trim
default
replace
truncate
```

Templates may be used for:

- title;
- message;
- dedup key;
- group key;
- labels;
- variable values;
- service lookup;
- route lookup;
- webhook headers;
- webhook body;
- event links.

The implementation must enforce output-length limits and redact secrets in traces.

## 11. Actions

Actions are implemented through a registry so that each action has isolated validation and execution logic.

```python
ACTION_HANDLERS = {
    "set_title": handle_set_title,
    "set_severity": handle_set_severity,
    "set_service": handle_set_service,
    "suppress": handle_suppress,
}
```

### 11.1 Event mutation

```text
set_title
set_message
set_status
set_severity
set_dedup_key
set_group_key
add_label
remove_label
rename_label
copy_field
add_event_link
```

### 11.2 Routing and ownership

```text
set_group
set_team
set_route
set_service
```

Cross-group routing must be explicitly prohibited unless a future permission model supports it.

### 11.3 Policies

```text
set_priority
set_escalation_policy
set_notification_policy
```

Selected entities must belong to the resulting group/team/service context.

### 11.4 Grouping and correlation

```text
set_group_by
disable_grouping
set_correlation_window
```

The final deduplication/grouping decision is applied before the existing alert repository groups the event.

### 11.5 Disposition

```text
continue
stop
suppress
drop
pause
```

### 11.6 Context actions

```text
extract_regex
set_variable
copy_to_variable
attach_runbook
add_stakeholder
```

### 11.7 Automation

```text
enqueue_webhook
```

Webhook execution must be asynchronous and must not delay ingestion.

## 12. Suppress, drop and pause semantics

### 12.1 Suppress

Suppress means:

- the alert and alert group may be created;
- escalation does not start;
- notifications are not sent;
- the reason and source rule are stored;
- analytics can count suppressed alerts;
- the alert remains available for investigation.

This is different from a silence because it is the direct result of event content rather than a separately scheduled suppression object.

### 12.2 Drop

Drop means:

- no alert or incident is created;
- no escalation or notification is started;
- a redacted orchestration execution is stored for a short retention period;
- dropped-event counters are exposed;
- the raw payload is not stored indefinitely.

Safeguards:

- publishing a catch-all drop requires explicit confirmation;
- validation warns when a large percentage of replayed events would be dropped;
- shadow mode is recommended before activation;
- RBAC permission is required to create or publish drop actions.

### 12.3 Pause

Pause must implement delayed activation, not merely delayed notifications.

Behavior:

```text
trigger
  → pending event created
  → activation scheduled

resolve before activation
  → pending event resolved
  → no alert group
  → no notifications

activation time reached
  → pending event enters existing alert lifecycle
```

Repeated trigger behavior:

- update the stored normalized event;
- preserve the original or recompute activation time according to an explicit rule;
- append trace information.

Required worker behavior:

- claim pending rows safely;
- be idempotent;
- tolerate worker restarts;
- avoid double activation;
- expose failed activations for retry.

## 13. Global intake

New endpoint:

```text
POST /api/integrations/orchestration
```

Authentication:

```http
Authorization: Bearer GLOBAL_ORCHESTRATION_TOKEN
```

The endpoint must:

1. authenticate the orchestration token;
2. accept a documented generic event envelope;
3. optionally select a normalizer;
4. run global orchestration;
5. run selected service orchestration;
6. pass the final result into the existing lifecycle;
7. return a trace ID.

If no route/service is selected:

```text
catch-all route
unrouted event
explicit drop
```

must be configurable.

A future UI page should expose Unrouted Events with replay capability.

## 14. Webhook actions and security

Webhook actions are the only executable automation type in v1.

Required protections:

- HTTPS by default;
- TLS certificate verification;
- timeout;
- retry limit;
- response size limit;
- redirect limit;
- DNS rebinding protection;
- loopback and link-local blocking;
- configurable private-network allowlist;
- encrypted headers and secret values;
- redaction in logs and traces;
- idempotency key;
- execution audit;
- permission checks;
- per-group concurrency and rate limits.

Actions must be queued after the orchestration decision is persisted.

## 15. Version lifecycle

Required workflow:

```text
Published version
    ↓ clone/edit
Draft
    ↓ validate
Simulate / Replay / Shadow
    ↓ publish
New published version
```

Operations:

- create draft;
- duplicate rule;
- validate draft;
- compare draft with active;
- simulate payload;
- replay stored events;
- publish;
- rollback;
- archive version;
- export/import definition.

Publication must be atomic.

Validation must detect:

- invalid condition trees;
- unsupported operators;
- invalid templates;
- missing referenced services or policies;
- cross-group references;
- unreachable rules where detectable;
- unsafe catch-all drop;
- invalid pause durations;
- invalid webhook actions;
- circular or excessive nesting;
- duplicate rule positions.

## 16. Shadow mode

Shadow mode evaluates an orchestration against real events but does not apply the result.

Trace must show:

```text
Current behavior
Draft/shadow behavior
Field-by-field difference
Routing difference
Disposition difference
```

Shadow mode must collect:

- match counts;
- routing changes;
- severity changes;
- potential drops;
- potential suppressions;
- potential pauses;
- execution errors.

No webhook actions are executed in shadow mode.

## 17. Simulator and replay

Required simulator modes:

```text
Paste payload
Use stored alert event
Replay one execution
Replay a selected event set
Compare active versus draft
```

Simulator output:

- selected normalizer;
- initial normalized event;
- each evaluated rule;
- condition results;
- extracted variables;
- field mutations;
- routing and policy decisions;
- final disposition;
- validation errors;
- active/draft diff.

Replay must not modify production state unless an explicit future apply mode is introduced.

## 18. Explain integration

Existing Explain trace should gain an Orchestration section.

Each rule trace must contain:

```text
rule ID and name
matched/not matched
condition results
actions attempted
before/after field values
variables created
processing mode
duration
error-safe message
```

Final trace must contain:

```text
orchestration ID
version ID
initial context
final context
selected entities
disposition
pause/suppress/drop reason
queued action IDs
total duration
```

## 19. Compatibility modes

IncidentRelay must support:

```text
legacy
hybrid
orchestration
```

### Legacy

Current routes, service rules and policies behave exactly as before.

### Hybrid

Orchestration runs first. Existing policies only fill values not explicitly set by orchestration.

Example:

```text
priority set by orchestration
→ Priority Policy does not override it

notification policy not set by orchestration
→ current Notification Policy evaluation continues
```

### Orchestration

Routing and policy decisions are primarily controlled by orchestration. Existing lifecycle components still perform alert persistence, escalation, notification delivery, correlation and impact.

Every final field should optionally store provenance:

```json
{
  "priority": {
    "value": "P1",
    "source": "orchestration",
    "rule_id": 25
  }
}
```

## 20. API surface

Implemented control-plane endpoints:

```text
GET    /api/event-orchestrations
POST   /api/event-orchestrations
GET    /api/event-orchestrations/catalog
GET    /api/event-orchestrations/{orchestration_id}
PATCH  /api/event-orchestrations/{orchestration_id}
DELETE /api/event-orchestrations/{orchestration_id}

POST   /api/event-orchestrations/{orchestration_id}/draft
PUT    /api/event-orchestrations/{orchestration_id}/draft
POST   /api/event-orchestrations/{orchestration_id}/validate
POST   /api/event-orchestrations/{orchestration_id}/publish
POST   /api/event-orchestrations/{orchestration_id}/rollback
PATCH  /api/event-orchestrations/{orchestration_id}/runtime
POST   /api/event-orchestrations/{orchestration_id}/simulate
POST   /api/event-orchestrations/{orchestration_id}/replay

GET    /api/event-orchestrations/{orchestration_id}/versions
GET    /api/event-orchestrations/{orchestration_id}/versions/{version_id}
GET    /api/event-orchestrations/{orchestration_id}/executions
GET    /api/event-orchestrations/{orchestration_id}/shadow-metrics

GET    /api/orchestration-webhook-actions
POST   /api/orchestration-webhook-actions
PATCH  /api/orchestration-webhook-actions/{action_id}
DELETE /api/orchestration-webhook-actions/{action_id}
GET    /api/orchestration-webhook-actions/{action_id}/executions
```

The generated OpenAPI document includes recursive condition-tree schemas, the
safe built-in action enum, draft/version author metadata and write-only webhook
secret headers. The dedicated public API guide is in
[`docs/api/event-orchestration.md`](../api/event-orchestration.md).

## 21. UI

Navigation entry:

```text
Event Orchestration
```

Suggested sections:

```text
Overview
Rules
Simulator
Versions
Executions
Webhook Actions
Settings
```

Rule builder:

```text
WHEN
  [labels.environment] [equals] [production]
  AND
  [severity] [in] [critical, high]

THEN
  [Set service] [Payments]
  [Set priority] [P1]
  [Set severity] [critical]

AFTER
  [Continue processing]
```

Required UX:

- ordered rules;
- drag-and-drop reordering;
- nested condition groups;
- field autocomplete;
- label autocomplete where possible;
- entity selectors;
- inline validation;
- duplicate rule;
- enable/disable rule;
- test one rule;
- JSON definition view;
- active/draft diff;
- publish dialog;
- warnings for drop and pause actions;
- execution trace viewer.

## 22. RBAC

Suggested permissions:

```text
orchestration.view
orchestration.create
orchestration.edit
orchestration.publish
orchestration.delete
orchestration.simulate
orchestration.replay
orchestration.manage_tokens
orchestration.manage_actions
orchestration.view_executions
```

Publishing, drop actions, token management and webhook secret management require elevated permissions.

## 23. Observability

Required metrics:

```text
orchestration_events_total
orchestration_rule_evaluations_total
orchestration_rule_matches_total
orchestration_duration_seconds
orchestration_errors_total
orchestration_dropped_events_total
orchestration_suppressed_events_total
orchestration_paused_events_total
orchestration_pending_events
orchestration_webhook_executions_total
orchestration_webhook_duration_seconds
```

Required logs:

- publication;
- rollback;
- execution failure;
- pending-event activation failure;
- webhook execution failure;
- token creation/revocation;
- unsafe rule validation warning.

Logs must never contain intake tokens or unredacted secret headers.

## 24. Limits

The first release should enforce configurable limits:

```text
maximum rules per version
maximum nesting depth
maximum actions per rule
maximum template output length
maximum regex length
maximum payload size
maximum pause duration
maximum webhook response size
maximum replay event count
trace retention
dropped-event trace retention
```

Limits protect latency, storage and operator safety.

## 25. Performance expectations

Initial targets:

- orchestration evaluation should add low single-digit milliseconds for normal rule sets;
- no network call may execute synchronously during ingestion;
- published definitions should be cached;
- cache invalidation occurs after publication or rollback;
- rule evaluation must be deterministic;
- execution trace storage should be configurable or sampled for successful high-volume events;
- failure of shadow evaluation must not fail production ingestion.

Load tests must include:

- many simple rules;
- deeply nested conditions;
- large label sets;
- regex conditions;
- concurrent global intake;
- mass pending-event activation;
- webhook action queue bursts.

## 26. Migration and rollout

Recommended rollout:

1. Add models and API behind a feature flag.
2. Implement evaluator and simulator without production application.
3. Add shadow mode.
4. Test against copied production events.
5. Add hybrid mode.
6. Enable for selected groups.
7. Add global intake.
8. Add pause and webhook actions after core evaluation is stable.
9. Keep legacy mode available during the entire v1 rollout.

No existing routes or policies should be automatically converted in the first migration.

A later migration helper may create draft orchestration definitions from simple existing route/service/priority rules.

## 27. PagerDuty migration compatibility

The model should make later PagerDuty conversion possible.

Expected exact or near-exact mappings:

```text
PagerDuty service routing
→ global routing rules

PagerDuty severity and priority actions
→ event mutation and set_priority

PagerDuty escalation policy override
→ set_escalation_policy

PagerDuty dedup key action
→ set_dedup_key

PagerDuty suppress
→ suppress

PagerDuty pause
→ pause

PagerDuty webhook action
→ orchestration webhook action
```

Initially unsupported PagerDuty constructs should be imported only into an analysis report:

- cache variables;
- frequency thresholds;
- event sequences;
- arbitrary recombining graphs;
- native Automation Actions;
- secret-bearing webhooks without explicit approval.

## 28. Delivery workstreams

### Workstream 1 — Data model and version API

- migrations;
- repositories;
- schemas;
- CRUD;
- draft/publish/rollback;
- RBAC;
- deterministic exports.

### Workstream 2 — Condition evaluator

- nested conditions;
- operators;
- field resolver;
- validation;
- structured match reasons;
- unit and property tests.

### Workstream 3 — Action engine

- registry;
- event mutation;
- routing;
- policies;
- grouping;
- variable extraction;
- templates;
- provenance.

### Workstream 4 — Runtime integration

- global and service orchestration;
- legacy/hybrid/orchestration modes;
- lifecycle handoff;
- cache of published definitions;
- execution persistence.

### Workstream 5 — Suppress, drop and pause

- disposition semantics;
- pending event model;
- activation worker;
- resolve-before-activation;
- metrics and trace retention.

### Workstream 6 — Webhook actions

- encrypted configuration;
- queue worker;
- SSRF protections;
- retries and limits;
- audit UI.

### Workstream 7 — Simulator, replay and shadow mode

- simulation API;
- stored-event replay;
- active/draft comparison;
- shadow metrics;
- Explain integration.

### Workstream 8 — UI

- orchestration list;
- rule builder;
- condition tree editor;
- action editor;
- simulator;
- versions and diff;
- executions;
- webhook actions.

### Workstream 9 — Documentation and quality

- OpenAPI;
- user documentation;
- architecture documentation;
- examples;
- load tests;
- security tests;
- upgrade and rollback procedures.

## 29. Acceptance criteria

Event Orchestration v1 is complete when:

1. A group administrator can create a global or service orchestration.
2. Rules support nested AND/OR/NOT conditions.
3. Rules can extract variables and use safe templates.
4. Rules can mutate event fields and labels.
5. Rules can select route, service, team, priority, escalation policy and notification policy.
6. Rules can change grouping and deduplication.
7. Continue, stop, suppress, drop and pause have documented and tested behavior.
8. Resolve-before-pause-activation creates no alert group and sends no notifications.
9. Webhook actions execute asynchronously with SSRF protection and audit.
10. Drafts can be validated, simulated, published and rolled back.
11. Published versions are immutable.
12. Shadow mode reports differences without changing production behavior.
13. Existing events can be replayed safely against a draft.
14. Every production decision is visible in Explain trace.
15. Legacy, hybrid and orchestration modes are supported.
16. Existing installations remain in legacy mode after upgrade.
17. OpenAPI and user documentation are complete.
18. Unit, integration, security and load tests pass.
19. Catalog keys match for every supported UI language.
20. No secret is exposed in logs, traces, API responses or exported definitions.

## 30. Deferred follow-up

After v1 is stable, evaluate:

- cache variables with TTL;
- event count/rate/duration conditions;
- distinct-host and sequence conditions;
- recombining graphs;
- native Automation Actions;
- manual approval steps;
- richer PagerDuty orchestration import;
- orchestration analytics and optimization recommendations.
