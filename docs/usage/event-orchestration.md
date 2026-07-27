---
title: Event Orchestration User Guide
description: A practical guide to routing, enriching, suppressing, delaying and automating incoming events with IncidentRelay Event Orchestration.
---

# Event Orchestration user guide

Event Orchestration lets IncidentRelay make a sequence of decisions about an incoming monitoring event **before the normal alert lifecycle finishes processing it**.

A monitoring system usually sends facts such as:

- what failed;
- which host or service is affected;
- how serious the event is;
- whether the event is firing or resolved;
- labels and integration-specific payload data.

Event Orchestration can use those facts to decide:

- which team, route and service should own the event;
- what title, severity or priority the event should have;
- how alerts should be grouped and deduplicated;
- which escalation, notification or priority policy should be used;
- whether notifications should be suppressed;
- whether alert creation should be delayed;
- whether an event should be dropped completely;
- whether a safe asynchronous webhook should be queued.

You do not need to be a programmer to build common rules. The **Builder** in the Event Orchestration page provides condition and action controls. A JSON view is also available for advanced definitions and API-managed workflows.

!!! tip "A simple mental model"
    Think of an orchestration as a mail-sorting desk. Each incoming event is inspected from top to bottom. A rule asks a question such as “Is this a critical production database event?” and, when the answer is yes, applies actions such as “send it to the database team, set P1 and add a label.”

## When Event Orchestration is useful

Use Event Orchestration when one or more decisions must be made from the content of the event rather than from one fixed route configuration.

Typical uses include:

| Situation | What orchestration can do |
| --- | --- |
| One integration sends alerts for several teams | Select a team, route or service from labels in each event. |
| Different monitoring systems use different severity names | Convert values such as `fatal`, `high` or `disaster` to your IncidentRelay severity convention. |
| Important alerts need a different policy | Select a priority, escalation or notification policy for matching events. |
| Alerts have unclear titles | Build a consistent title from labels and extracted values. |
| A noisy event should remain visible but not notify anyone | Use `suppress`. |
| A transient event should wait before becoming an alert | Use `pause`. |
| A known health-check event should never create an alert | Use `drop`, with careful testing. |
| Related host alerts should become one incident | Set a common `group_key`. |
| Repeated events must update the same child alert | Set a stable `dedup_key`. |
| A diagnostic or ticketing system must be called | Queue a reusable webhook action. |
| A new rule must be tested safely | Use validation, simulation, replay and shadow mode. |

Event Orchestration does not replace IncidentRelay alert storage, incidents, escalation execution, notifications, correlation or impact calculation. It prepares the event and selects how the existing lifecycle should handle it.

## When not to use it

Do not create orchestration rules merely to duplicate a simple route matcher or a service default that already expresses the requirement clearly.

Keep the existing configuration when:

- every event from one intake route always belongs to the same team and service;
- a service-wide default escalation policy is sufficient;
- a normal silence or maintenance window already represents a temporary operational condition;
- the change is personal notification preference rather than event processing;
- arbitrary shell, Python, SSH or container execution is required. Those actions are intentionally not supported.

A small and understandable rule set is safer than moving every existing setting into orchestration.

## Where to find it

1. Sign in to IncidentRelay.
2. Select the required group using the global group selector.
3. Open **Event Orchestration** from the navigation menu.
4. The list shows orchestrations belonging to the selected group.

The summary cards show:

- total orchestration definitions;
- active orchestrations;
- orchestrations in shadow mode;
- definitions with an unpublished draft.

Use the search field and the mode and scope filters when the group has many definitions.

## Permissions

Access is calculated inside the selected IncidentRelay group.

| Role | Event Orchestration access |
| --- | --- |
| Group `viewer` | View orchestrations, versions and executions. |
| Group `editor` | View, create, edit, validate, simulate, replay, publish and rollback. |
| Group `user_admin` | View orchestrations and executions. |
| Global administrator | All permissions, including deletion and webhook-action management. |

A group editor can publish changes, but only a global administrator can delete an orchestration or manage reusable webhook actions.

Version history records three different authors when applicable:

- **Created by** — who created the version row;
- **Changed by** — who last changed the draft definition;
- **Published by** — who published the immutable version.

This makes it possible to distinguish the person who edited a rule from the person who reviewed and published it.

## Core terms

| Term | Meaning |
| --- | --- |
| Event | The normalized monitoring signal currently being processed. |
| Orchestration | A group-owned, versioned definition containing ordered rules. |
| Rule | A condition plus one or more actions. |
| Condition | A test such as `labels.environment equals production`. |
| Action | A change or decision applied after a rule matches. |
| Draft | The editable working definition. It does not become the active production version until published. |
| Published version | An immutable snapshot that can be used at runtime. |
| Execution | One recorded evaluation of a published orchestration. |
| Scope | Whether the orchestration is global for the group or attached to one service. |
| Runtime mode | Whether the published orchestration is disabled, evaluated in shadow, or actively applied. |
| Compatibility mode | How orchestration and the existing lifecycle share responsibility. |
| Disposition | Final handling decision: process, suppress, pause or drop. |
| Webhook action | A reusable encrypted outbound HTTP request queued by a matching rule. |

## Where orchestration runs in the alert flow

The simplified flow is:

```text
Incoming integration payload
        ↓
Integration authentication and normalization
        ↓
Group global orchestration
        ↓
Selected service orchestration, when a service is known
        ↓
Existing IncidentRelay lifecycle
        ↓
Alert group, child alert, escalation and notifications
```

A global orchestration can select a service. IncidentRelay then evaluates the orchestration attached to that service. A service orchestration can also select another service; service handoffs are protected against loops and excessive chaining.

Rules inside one orchestration run in their displayed order. Earlier actions can change values that later rules inspect.

Example:

```text
Rule 1 sets labels.environment = production
        ↓
Rule 2 checks labels.environment
        ↓
Rule 2 now sees production
```

Order therefore matters.

## Scope: global or service

### Global scope

A global orchestration belongs to one group and can process events before a service has been selected.

Use it for:

- choosing a team, route or service;
- normalizing severity and labels across integrations;
- applying group-wide suppression or drop rules;
- setting common grouping rules;
- dispatching events from one shared integration endpoint.

Example:

```text
IF labels.application equals billing
THEN select Billing API service
```

### Service scope

A service orchestration runs when that service is selected by the incoming route, the legacy lifecycle or an earlier orchestration action.

Use it for:

- service-specific severity or priority rules;
- selecting a service-specific escalation or notification policy;
- adding service-specific context;
- suppressing or delaying one known service signal;
- queueing a diagnostic webhook for one service.

Example:

```text
For the Database service:
IF labels.operation equals backup
AND event.severity equals warning
THEN suppress notifications
```

### Choosing a scope

Use this rule of thumb:

- choose **global** when the rule helps decide ownership or applies to several services;
- choose **service** when ownership is already known and the behavior is specific to one service.

## Runtime mode

Runtime mode controls whether a published definition affects real events.

| Mode | Behavior |
| --- | --- |
| `disabled` | The orchestration does not run. Drafting, validation and simulation are still available. |
| `shadow` | The published version is evaluated and recorded, but its decisions do not change production behavior. |
| `active` | The published version is evaluated and valid decisions are applied to production processing. |

A published version is required before `shadow` or `active` can be selected.

Recommended progression:

```text
disabled → publish → shadow → review executions → active
```

## Compatibility mode

Compatibility mode controls how Event Orchestration works with existing routes, service matching and policies.

### `legacy`

The existing lifecycle remains authoritative. This is the safest upgrade default for installations that already have routes and policies.

An orchestration configured as `active + legacy` is not applied to production events. Use simulation or change to `hybrid` when you are ready to apply decisions.

### `hybrid`

Orchestration runs first and can explicitly set fields and selected entities. Existing lifecycle logic continues to fill values that orchestration did not select.

Examples:

```text
Orchestration explicitly sets priority P1
→ the existing priority policy does not replace that explicit value

Orchestration does not select a notification policy
→ normal notification-policy resolution continues
```

When an orchestration result contains an invalid entity combination, such as a route from another group, hybrid mode rejects that candidate and allows the legacy path to continue instead of blocking alert processing.

This is the recommended mode for most initial production rollouts.

### `orchestration`

Orchestration becomes authoritative for routing decisions. A valid route must be selected before processing can continue. Evaluation or entity-validation failures block processing rather than silently falling back to the legacy path.

Use this only after shadow and hybrid results have been reviewed.

## A safe first rollout

For a first rule, follow this sequence:

1. Create the orchestration with runtime mode `disabled`.
2. Use compatibility mode `hybrid`.
3. Add one narrowly scoped rule.
4. Save the draft.
5. Validate it.
6. Simulate both a matching and a non-matching event.
7. Publish the version.
8. Change runtime mode to `shadow`.
9. Review real execution traces and shadow metrics.
10. Change runtime mode to `active` only when the observed decisions are correct.
11. Keep existing routes and policies during the first rollout.
12. Use rollback if a published change is incorrect.

!!! warning "Start narrow"
    Do not begin with an empty catch-all condition combined with `drop`, `suppress`, `pause` or a routing action. First match a specific source, environment, service or alert name.

## Page and tab overview

Open an orchestration to see its workspace.

### Rules

Build and order conditions and actions. The rule card summarizes:

- **WHEN** — the condition;
- **THEN** — the configured actions;
- **AFTER** — what happens after a match.

Rules can be moved up or down, edited, duplicated or removed.

### Simulator

Test the draft without creating alerts or sending webhook actions. You can test a normalized event directly or pass a raw payload through a supported integration normalizer.

### Versions

Shows draft, published and archived versions, who changed and published them, comments, definition hashes and publication times. A historical published version can be rolled back by publishing a new copy of it.

### Executions

Shows real runtime evaluations, including source, final disposition, matched rule count, duration and trace. Shadow metrics are also displayed here.

### Webhook Actions

Lists reusable outbound HTTP actions for the selected group. Only a global administrator can create, edit or delete them.

### Settings

Edit name, description, scope and service. Runtime settings control mode and compatibility mode.

## Create your first orchestration

This example routes critical production alerts to a selected team and service and marks them as P1.

### 1. Create the definition

Click **New orchestration** and enter:

| Field | Example | Explanation |
| --- | --- | --- |
| Name | `Production critical routing` | Use a name that describes the decision, not the integration. |
| Description | `Routes critical production events to the platform team.` | Explain the operational intent. |
| Scope | `Global` | The rule selects ownership before service processing. |
| Compatibility mode | `hybrid` | Existing lifecycle fills anything the orchestration does not set. |

The new orchestration starts disabled and contains an initial draft.

### 2. Add a rule

Open **Rules** and click **Add rule**.

Use:

| Field | Value |
| --- | --- |
| Name | `Critical production` |
| Description | `Select platform ownership and P1 for critical production events.` |
| Enabled | checked |
| After match | `stop` |

`stop` stops evaluation of later rules in this orchestration. It does **not** drop the event and does **not** stop the normal alert lifecycle.

### 3. Add conditions

Keep the root group as **ALL** and add two conditions:

| Field | Operator | Value |
| --- | --- | --- |
| `labels.environment` | `equals` | `production` |
| `event.severity` | `in` | `["critical", "fatal"]` |

For `in` and `not_in`, enter a JSON array. A comma-separated value may be accepted by the builder, but a JSON array is clearer and avoids ambiguity.

The condition means:

```text
environment must be production
AND
severity must be critical or fatal
```

### 4. Add actions

Add these actions:

1. `set_team` — select the required team.
2. `set_service` — select the required service.
3. `set_priority` — enter `P1`.
4. `set_label` — name `orchestrated`, value `true`.

Save the rule, then click **Save draft**.

### 5. Validate

Click **Validate**.

Validation checks, among other things:

- condition structure and operators;
- field-reference syntax;
- regex safety;
- action parameters;
- selected route, team, service and policy references;
- templates;
- dangerous catch-all drop rules.

Fix every error before publishing. Warnings should also be reviewed even when the draft is technically valid.

### 6. Simulate a matching event

Open **Simulator**, choose **Normalized event**, and use:

```json
{
  "source": "webhook",
  "title": "Checkout API unavailable",
  "message": "Health check failed for checkout-api-2",
  "severity": "critical",
  "status": "firing",
  "dedup_key": "checkout-api-2:unavailable",
  "labels": {
    "environment": "production",
    "service": "checkout-api",
    "instance": "checkout-api-2"
  }
}
```

Click **Run simulation**.

Confirm that:

- the rule matched;
- the selected team and service IDs are correct;
- priority became `P1`;
- label `orchestrated=true` was added;
- the final disposition is process, not suppress, pause or drop;
- no unexpected rule matched.

### 7. Simulate a non-matching event

Change `environment` to `staging` and simulate again. The rule should not match and the event should remain unchanged by this rule.

Testing non-matches is as important as testing matches.

### 8. Publish and shadow

Click **Publish**. Publication creates an immutable version.

Open **Settings** and change runtime mode to `shadow`. Leave compatibility mode as `hybrid`.

After real events arrive, inspect **Executions**. When the decisions match operational expectations, change runtime mode to `active`.

## Conditions

A condition decides whether the actions in one rule should run.

A leaf condition has three parts:

```text
field + operator + expected value
```

Example:

```text
labels.environment equals production
```

### Field references

Fields use safe dotted paths. IncidentRelay reads JSON objects and array indexes only; it cannot execute methods or arbitrary expressions.

| Root | Example | What it contains |
| --- | --- | --- |
| `event` | `event.severity` | Normalized event fields such as title, severity, status and dedup key. |
| `labels` | `labels.environment` | Normalized labels. This is usually the easiest place for routing facts. |
| `raw` | `raw.alerts.0.labels.namespace` | Original integration payload, when available. |
| `variables` | `variables.application` | Values created by advanced extraction actions. |
| `route` | `route.id` | Currently selected route metadata. |
| `service` | `service.id` | Currently selected service metadata. |
| `team` | `team.id` | Currently selected team metadata. |
| `integration` | `integration.source` | Integration source name. |
| `time` | `time.now` | Runtime time context. |
| `result` | `result.disposition` | Decisions already produced by earlier actions. |

A bare simple field such as `severity` is normalized to `event.severity`, but explicit roots are easier to understand and maintain.

Common normalized fields include:

```text
event.source
event.title
event.message
event.description
event.severity
event.status
event.dedup_key
event.group_key
labels.alertname
labels.environment
labels.service
labels.instance
labels.job
```

The exact labels depend on the incoming integration.

### Operators

| Operator | Meaning | Example |
| --- | --- | --- |
| `equals` | Actual value equals the expected value. | `labels.environment equals production` |
| `not_equals` | Actual value differs from the expected value. | `event.severity not_equals info` |
| `contains` | A string contains text, a list contains a value, or an object contains a key. | `event.title contains Database` |
| `not_contains` | Opposite of `contains`. | `event.title not_contains Test` |
| `starts_with` | String starts with the expected text. | `labels.instance starts_with prod-` |
| `ends_with` | String ends with the expected text. | `labels.instance ends_with .example.com` |
| `regex` | Safe regular expression matches the value. | `labels.job regex ^rabbitmq(-.+)?$` |
| `not_regex` | Safe regular expression does not match. | `labels.namespace not_regex ^dev-` |
| `in` | Actual value occurs in a JSON list or object. | `event.severity in ["critical", "fatal"]` |
| `not_in` | Actual value does not occur in the collection. | `labels.environment not_in ["dev", "test"]` |
| `exists` | Field is present, even if its value is empty or null. | `labels.cluster exists` |
| `not_exists` | Field is absent. | `labels.owner not_exists` |
| `greater_than` | Numeric comparison. | `event.value greater_than 90` |
| `less_than` | Numeric comparison. | `event.value less_than 10` |
| `greater_or_equal` | Numeric comparison including equality. | `event.value greater_or_equal 80` |
| `less_or_equal` | Numeric comparison including equality. | `event.value less_or_equal 20` |
| `is_true` | Value is boolean-like true. | `labels.customer_impacting is_true` |
| `is_false` | Value is boolean-like false. | `labels.maintenance is_false` |

Numeric comparisons accept finite numbers and numeric strings. Boolean operators recognize booleans, `0`/`1`, and common strings such as `true`, `false`, `yes`, `no`, `on` and `off`.

### AND, OR and NOT groups

The Builder provides three logical group types:

- **ALL** — every child must match; this is AND logic;
- **ANY** — at least one child must match; this is OR logic;
- **NONE** — no child may match; this is NOT logic.

Example:

```text
ALL
├── labels.environment equals production
└── ANY
    ├── event.severity equals critical
    └── labels.priority equals p1
```

This means:

```text
production AND (critical OR p1)
```

A NONE example:

```text
ALL
├── labels.environment equals production
└── NONE
    ├── labels.namespace starts_with dev-
    └── labels.namespace starts_with test-
```

This matches production events whose namespace is neither development nor test.

### Catch-all rules

A rule with an empty condition matches every event that reaches it.

Catch-all rules are useful at the end of a definition for defaults, for example:

```text
If no earlier rule stopped processing,
add label orchestration_result=default
```

They are dangerous when combined with `drop`, `suppress`, `pause` or mandatory routing. Catch-all drop requires explicit confirmation during publication.

### Regex guidance

Use regex only when equality, prefix, suffix or membership cannot express the requirement.

Good:

```text
^rabbitmq(-[a-z0-9-]+)?$
```

Avoid broad patterns such as:

```text
.*
```

A broad regex often hides a catch-all rule and is harder to review. IncidentRelay validates regex safety and limits evaluated input size, but a precise expression is still easier to operate.

## Actions

Actions run in the order displayed inside a matching rule. An earlier action can provide data for a later action.

### Change event fields

| Action | Purpose | Example value |
| --- | --- | --- |
| `set_title` | Replace the alert title. | `Database unavailable on {{ labels.instance }}` |
| `set_message` | Replace the event message. | `Original alert: {{ event.title }}` |
| `set_description` | Replace the longer description. | `Environment: {{ labels.environment }}` |
| `set_severity` | Set normalized severity. | `critical` |
| `set_priority` | Set incident priority directly. | `P1` |
| `set_dedup_key` | Decide which repeated events update the same child alert. | `{{ labels.alertname }}:{{ labels.instance }}` |
| `set_group_key` | Decide which child alerts belong to the same alert group. | `{{ labels.alertname }}:{{ labels.environment }}` |
| `set_event_action` | Force trigger or resolve semantics. | `trigger` or `resolve` |

Use stable values for deduplication and grouping. Do not include timestamps or other values that change on every request unless you intentionally want a new alert every time.

### Labels and custom fields

| Action | Purpose |
| --- | --- |
| `set_label` | Add or replace one label. |
| `remove_label` | Remove one label. |
| `set_custom_field` | Add or replace one value in `event.custom_details`. |
| `remove_custom_field` | Remove one custom detail. |
| `add_note` | Add an orchestration note to the result trace. |

Example:

```text
set_label
name: owner
value: platform
```

### Select ownership and policies

| Action | Result |
| --- | --- |
| `set_team` | Select a team in the current group. |
| `set_route` | Select a route in the current group. The route source must match the event source. |
| `set_service` | Select an enabled service in the current group. |
| `set_escalation_policy` | Select an enabled escalation policy belonging to the selected team. |
| `set_notification_policy` | Select an enabled notification policy belonging to the selected team. |
| `set_priority_policy` | Select an enabled priority policy belonging to the selected team. |

The Builder loads allowed objects from the current group. Runtime validates that the selected route, team, service and policies form a consistent combination.

Examples of invalid combinations:

- route belongs to another group;
- route source is `sentry` but the event source is `alertmanager`;
- selected service belongs to a different team than the selected route;
- selected policy belongs to another team;
- selected object was disabled or deleted after publication.

In hybrid mode such a candidate is rejected and legacy processing may continue. In orchestration compatibility mode the failure can block processing.

### Set grouping

`set_grouping` can define:

- `group_key`;
- `dedup_key`;
- `window_seconds`.

Example:

```text
group_key: {{ labels.alertname }}:{{ labels.environment }}
dedup_key: {{ labels.alertname }}:{{ labels.instance }}
window_seconds: 900
```

This creates one incident per alert name and environment, while preserving one child alert per instance for a 15-minute grouping window.

Read [Alerts and alert groups](alerts.md) before changing grouping in production.

### Suppress, pause and drop

These three actions have very different consequences.

| Action | Alert created? | Visible in IncidentRelay? | Notifications/escalation? | Typical use |
| --- | --- | --- | --- | --- |
| `suppress` | Yes | Yes | Suppressed | Keep a known event visible for investigation without paging. |
| `pause` | Not immediately | Pending until activation | Not until activation | Wait for a transient issue to persist. |
| `drop` | No | No alert or group | No | Ignore events that have no operational value. |

#### `suppress`

The alert and alert group are created or updated. They are marked as orchestration-suppressed, scheduled notifications are cleared, and escalation is not scheduled while suppression applies.

Use it when operators may still need to search, review or correlate the event.

Example:

```text
IF labels.environment equals development
AND event.severity equals warning
THEN suppress reason "Development warning"
```

#### `pause`

The event is stored as pending and is activated only after the configured number of seconds.

If a matching resolve event arrives before activation, the pending event is resolved without creating an alert.

`retrigger` controls repeated firing events:

- `preserve` keeps the original activation time;
- `reset` starts the delay again after every repeated firing event.

Example:

```text
pause 300 seconds
retrigger preserve
reason "Wait five minutes for transient recovery"
```

Use `preserve` when the alert should appear after five minutes from the first failure. Use `reset` when the alert should appear only after five quiet-free minutes from the most recent failure signal.

#### `drop`

Processing stops and no alert or alert group is created.

Use it only for events that must never be retained as IncidentRelay alerts, such as an integration test heartbeat that has no incident value.

!!! danger "Dropped events are intentionally absent"
    A dropped event cannot be found in the Alerts page because no alert is created. Review execution traces and replay results before enabling drop rules.

### Queue a webhook

`enqueue_webhook` selects one reusable webhook action. It does not perform the HTTP request inside the alert request. IncidentRelay queues an asynchronous execution after the orchestration result is successfully applied.

Simulation and shadow evaluation do not send webhooks.

## After match: processing mode

Processing mode controls what happens to later rules after the current rule matches.

| Mode | Behavior |
| --- | --- |
| `continue` | Apply actions and continue with the next sibling rule. |
| `stop` | Apply actions and stop this orchestration. The normal alert lifecycle still continues. |
| `evaluate_children` | Evaluate child rules, then stop sibling processing. |
| `children_then_continue` | Evaluate child rules, then continue with later sibling rules. |

The visual Builder currently focuses on top-level rules and nested condition groups. Advanced rule trees with child rules can be managed through JSON or API when needed.

Use `stop` for mutually exclusive routing decisions:

```text
Rule 1: production database → Database team → stop
Rule 2: production frontend → Frontend team → stop
Rule 3: catch-all → Platform intake → stop
```

Use `continue` when several independent enrichments should all apply:

```text
Rule 1 adds environment label
Rule 2 normalizes severity
Rule 3 selects priority
```

## Action failure behavior

Every action has an `on_failure` setting:

| Value | Behavior |
| --- | --- |
| `continue` | Record the failure and continue to the next action. |
| `stop_rule` | Stop the current rule's action sequence. |
| `stop_orchestration` | Stop the complete orchestration evaluation. |

Examples of runtime failures include a required template field being absent or an invalid value being produced.

For routing and disposition actions, prefer `stop_rule` or `stop_orchestration` when continuing would create a misleading partial result. For optional enrichment, `continue` is often acceptable.

## Templates

Text actions can use safe templates surrounded by `{{` and `}}`.

Example:

```text
Database alert on {{ labels.instance }} in {{ labels.environment }}
```

Templates can reference the same safe field roots used by conditions.

Supported filters:

| Filter | Example | Result |
| --- | --- | --- |
| `lower` | `{{ labels.service | lower }}` | Lowercase text. |
| `upper` | `{{ labels.environment | upper }}` | Uppercase text. |
| `trim` | `{{ event.title | trim }}` | Remove leading and trailing whitespace. |
| `default` | `{{ labels.owner | default("unknown") }}` | Use a fallback when absent, null or empty. |
| `replace` | `{{ labels.service | replace("_", "-") }}` | Replace text. |
| `truncate` | `{{ event.message | truncate(120) }}` | Limit output length. |

Filters can be chained:

```text
{{ labels.service | default("unknown") | trim | lower }}
```

Templates are intentionally restricted. They cannot execute Python, call methods, access object attributes or run arbitrary code.

### Template missing fields

This template fails when `labels.cluster` is absent:

```text
Cluster {{ labels.cluster }} is unavailable
```

This version is safer:

```text
Cluster {{ labels.cluster | default("unknown") }} is unavailable
```

Use the simulator to test events with optional labels removed.

## Practical examples

The following examples show complete operational intentions. IDs for teams, services and policies are selected from the Builder and therefore are not hard-coded in the descriptions.

### Example 1: route RabbitMQ alerts by labels

Goal: one shared Alertmanager integration receives many alerts, but RabbitMQ events should go to the messaging team and service.

Conditions:

```text
ALL
├── labels.job equals RabbitMQ
└── labels.rabbitmq regex ^rabbitmq(-[a-z0-9-]+)?$
```

Actions:

```text
set_team       → Messaging team
set_service    → RabbitMQ service
set_label      → name=component, value=rabbitmq
set_grouping   → group_key={{ labels.alertname }}:{{ labels.rabbitmq }}
stop
```

Why use regex here: the `rabbitmq` label can contain names such as `rabbitmq-cloud`, `rabbitmq-production` or `rabbitmq-eu1`, while the prefix remains stable.

### Example 2: normalize severity names

Goal: one source sends `disaster`, while IncidentRelay rules expect `critical`.

Rule:

```text
IF event.severity equals disaster
THEN set_severity critical
AFTER continue
```

A later rule can now consistently check `event.severity equals critical`.

### Example 3: build a useful title

Goal: replace a generic alert title with service and instance information.

Condition:

```text
labels.service exists
```

Action:

```text
set_title
{{ labels.service | upper }}: {{ event.title | trim }} on {{ labels.instance | default("unknown instance") }}
```

Result:

```text
PAYMENTS: High error rate on payments-api-3
```

### Example 4: suppress development warnings

Goal: keep development warnings visible without notifying on-call users.

Conditions:

```text
ALL
├── labels.environment equals development
└── event.severity in ["info", "warning"]
```

Actions:

```text
set_label name=suppression_source value=orchestration
suppress reason="Non-production informational event"
stop
```

Use `suppress`, not `drop`, because developers may still need to search the event later.

### Example 5: delay transient failures

Goal: create an alert only when an endpoint stays unhealthy for five minutes.

Conditions:

```text
ALL
├── labels.alertname equals EndpointUnavailable
└── labels.environment equals production
```

Action:

```text
pause
seconds: 300
retrigger: preserve
reason: "Wait for transient endpoint recovery"
```

A resolve event with the same source and dedup key before activation prevents alert creation.

### Example 6: drop an integration test event

Goal: a monitoring system sends a known test signal that should not become an alert.

Conditions:

```text
ALL
├── labels.alertname equals IncidentRelayIntegrationTest
├── labels.environment equals test
└── labels.intent equals connectivity-check
```

Action:

```text
drop reason="Expected integration connectivity test"
```

Use several exact conditions. Do not use only `event.title contains test`, because real incidents may also contain that word.

### Example 7: select policies for customer-impacting incidents

Goal: customer-impacting critical events should use the fastest escalation and a dedicated notification policy.

Conditions:

```text
ALL
├── labels.customer_impacting is_true
└── event.severity equals critical
```

Actions:

```text
set_priority              P1
set_escalation_policy     Customer Critical escalation
set_notification_policy   Customer Incident notifications
set_label                  name=customer_impacting, value=true
stop
```

The selected policies must belong to the selected team.

### Example 8: group many hosts into one incident

Goal: twenty hosts report the same cluster partition, and operators should receive one incident containing twenty child alerts.

Actions:

```text
set_grouping
group_key: {{ labels.alertname }}:{{ labels.cluster }}
dedup_key: {{ labels.alertname }}:{{ labels.instance }}
window_seconds: 1800
```

The shared group key combines the host alerts. The per-instance dedup key ensures repeated signals update the correct child alert.

### Example 9: queue a diagnostic webhook

Goal: when a critical database event arrives, asynchronously request diagnostics from an internal automation service.

1. A global administrator creates a webhook action named `Collect database diagnostics`.
2. The orchestration rule matches the database service and critical severity.
3. The rule selects `enqueue_webhook → Collect database diagnostics`.
4. IncidentRelay applies the orchestration and creates the alert.
5. The scheduler delivers the webhook asynchronously with retries.

A body template can include:

```json
{
  "service": "{{ labels.service }}",
  "instance": "{{ labels.instance }}",
  "alert": "{{ event.title }}",
  "severity": "{{ event.severity }}"
}
```

The webhook is not sent during simulation or shadow mode.

## Simulator

The Simulator evaluates the current draft in isolation. It does not:

- create or update alerts;
- change runtime mode;
- publish a version;
- send notifications;
- execute outbound webhooks;
- modify production data.

### Normalized event input

Choose **Normalized event** when you already know the fields used by your rules.

Minimum useful example:

```json
{
  "source": "webhook",
  "title": "Example alert",
  "severity": "warning",
  "status": "firing",
  "dedup_key": "example-1",
  "labels": {
    "environment": "staging"
  }
}
```

### Raw integration payload

Choose an integration source to pass the payload through the same registered normalizer used by production ingestion.

Supported sources in this release are:

```text
alertmanager
aws_sns
datadog
grafana
librenms
rmon
sentry
webhook
zabbix
```

This is useful when you do not know exactly how a raw payload becomes normalized labels and event fields.

### Compare with active version

Enable **Compare with active version** when an orchestration already has a published version.

The result includes a draft-versus-active difference showing fields and decisions that would change after publication.

Review changes to:

- route, team and service;
- title, severity and priority;
- grouping and deduplication;
- policies;
- disposition;
- queued webhooks.

### Reading a simulation result

Important result areas include:

| Area | What to check |
| --- | --- |
| Initial normalized event | Did the integration normalize the payload as expected? |
| Matched rules | Did only the intended rules match? |
| Condition trace | Which field and value caused a match or mismatch? |
| Action trace | What changed before and after each action? |
| Final context | What event, labels, routing and policies remain after all rules? |
| Disposition | Will the event process, suppress, pause or drop? |
| Active/draft diff | What changes compared with production? |

A simulation that returns successfully can still represent an incorrect business decision. Verify the selected entities and final values, not only the absence of errors.

## Replay

Replay evaluates stored alerts or previous orchestration executions against a selected version. It does not apply changes to production.

Replay is useful when:

- changing a broad rule;
- introducing a drop or suppress condition;
- changing grouping;
- replacing route selection;
- checking how a draft behaves against real historical data.

Replay reports counts, failures, dispositions and changes from the active version. It also warns when the draft would drop a high percentage of replayed events.

The current web page focuses on single-event simulation. Replay is available through the orchestration API and can be added to operational review workflows.

## Validation, publication and versions

### Save draft

**Save draft** stores the editable definition and records the current user as the last editor.

Saving does not change the published production version.

### Validate

**Validate** saves the current builder state and performs static and entity checks.

Validation does not prove that the business logic is correct. Simulation, shadow mode and review are still required.

### Publish

**Publish** creates an immutable version and makes it the active version for the orchestration definition.

Publication does not automatically change runtime mode. A disabled orchestration remains disabled after publication.

Every meaningful publication should include a comment through API-managed workflows. The UI version history exposes stored comments where present.

### Immutable history

Published versions are not edited in place. This provides:

- an exact definition hash;
- reliable execution-to-version linkage;
- clear authorship;
- safe comparison;
- reproducible rollback.

### Rollback

Rollback does not rewrite history. IncidentRelay copies the selected historical definition into a new version and publishes that copy.

After rollback:

- old versions remain unchanged;
- the new version has its own number and publication author;
- future executions reference the new version.

## Shadow mode and executions

Shadow mode is the safest way to observe a published definition against real traffic.

In shadow mode:

- the published rules are evaluated;
- execution records and traces are stored;
- candidate decisions can be compared with actual lifecycle results;
- production event behavior is unchanged;
- webhook actions are not delivered.

### Execution list

The **Executions** tab shows:

- integration source;
- final disposition;
- number of matched rules;
- evaluation duration;
- creation time;
- a trace button.

The trace contains redacted initial context, condition results, actions, before/after values, final context, selected entities and errors.

### What to review before activation

Review a representative sample from each important source and event type.

Look for:

- unexpected catch-all matches;
- events routed to the wrong team or service;
- route/source mismatches;
- missing optional template fields;
- too many suppressed, paused or dropped events;
- unstable dedup or group keys;
- large evaluation durations;
- rules that never match;
- later rules undoing earlier actions.

### Shadow metrics

Shadow metrics summarize candidate differences such as routing, disposition and event mutations. Use them to find systematic changes, then open individual execution traces to understand why they occurred.

Metrics are a signal, not an approval mechanism. A small difference count may still contain one critical misroute.

## Webhook actions

Webhook actions are reusable group-owned outbound HTTP definitions. They are separate from rule definitions so secrets and delivery settings are managed centrally.

Only a global administrator can create, edit or delete them.

### Create a webhook action

Open **Webhook Actions** and click **Add webhook**.

Configure:

| Field | Meaning |
| --- | --- |
| Name | Human-readable action name shown in rule selectors. |
| Description | What the remote system does and when the action should be used. |
| URL | Destination URL. HTTPS is required unless HTTP is explicitly enabled by the administrator. |
| Method | GET, POST, PUT, PATCH or DELETE. |
| Secret headers JSON | Authentication and other headers. Values are encrypted and never returned by the API. |
| Body template | Optional safe template. When empty, IncidentRelay sends event and result JSON. |
| Timeout | Maximum request duration. |
| Retries | Number of delivery retries. |
| Private network policy | Whether private-address targets are denied or must be in the configured allowlist. |
| Enabled | Disabled actions are not queued. |

Example secret headers:

```json
{
  "Authorization": "Bearer secret-token",
  "X-Source": "IncidentRelay"
}
```

When editing an existing action, the UI intentionally displays `{}` instead of decrypting stored headers. Leaving headers empty preserves the existing encrypted headers. Supplying a new non-empty object replaces them.

### Security behavior

Webhook delivery includes protections against server-side request forgery and secret exposure:

- URLs must use HTTP or HTTPS and cannot contain embedded credentials;
- HTTPS is required by default;
- private and special network addresses are denied unless explicitly allowlisted;
- redirects are limited and revalidated;
- dangerous hop-by-hop headers are rejected;
- secret headers are encrypted;
- API responses never return header values;
- logged errors and response excerpts are redacted and size-limited;
- requests receive an idempotency key;
- per-group concurrency and rate limits apply.

### Scheduler requirement

Outbound webhook requests are asynchronous. The IncidentRelay scheduler process must be running for pending automation executions and retries to be delivered.

## Advanced JSON view

The Builder covers common condition and action types. **JSON view** exposes the complete deterministic definition and is useful for:

- copying a definition for review;
- applying bulk changes;
- advanced variable extraction;
- child rule trees;
- API-generated configurations.

Always click **Apply JSON**, then **Save draft**, and validate after editing JSON.

A complete example:

```json
{
  "schema_version": 1,
  "rules": [
    {
      "name": "Critical production database",
      "description": "Route and enrich critical database events.",
      "enabled": true,
      "condition_tree": {
        "all": [
          {
            "field": "labels.environment",
            "operator": "equals",
            "value": "production"
          },
          {
            "field": "labels.component",
            "operator": "equals",
            "value": "database"
          },
          {
            "field": "event.severity",
            "operator": "in",
            "value": ["critical", "fatal"]
          }
        ]
      },
      "actions": [
        {
          "type": "set_title",
          "template": "DB: {{ event.title | trim }} on {{ labels.instance | default(\"unknown\") }}"
        },
        {
          "type": "set_priority",
          "value": "P1"
        },
        {
          "type": "set_label",
          "name": "orchestrated",
          "value": "true"
        },
        {
          "type": "set_grouping",
          "group_key": "{{ labels.alertname }}:{{ labels.cluster | default(\"default\") }}",
          "dedup_key": "{{ labels.alertname }}:{{ labels.instance }}",
          "window_seconds": 1800
        }
      ],
      "processing_mode": "stop",
      "children": []
    }
  ]
}
```

Team, route, service and policy actions require numeric IDs. Prefer selecting them in the Builder so the catalog supplies group-valid objects.

### Advanced variable actions

The engine also supports deterministic variable extraction actions through JSON and API:

```text
extract_regex
copy_field
copy_to_variable
json_path
split
set_variable
static
lowercase
uppercase
trim
```

Variables are stored under `variables.<name>` for later conditions and templates.

Example:

```json
{
  "type": "extract_regex",
  "source": "labels.instance",
  "pattern": "^(?P<service>[a-z0-9-]+)-[0-9]+$"
}
```

After a successful extraction, a later action can use:

```text
{{ variables.service }}
```

Use advanced extraction only when the normalized integration fields cannot already supply the required value.

## Troubleshooting

### The orchestration never runs

Check:

1. A version is published.
2. Runtime mode is `shadow` or `active`.
3. The event belongs to the same group.
4. A global orchestration has the expected group context.
5. A service orchestration is attached to the service actually selected for the event.
6. `active + legacy` is not being used when production application is expected.
7. The orchestration and selected service are enabled.

### A rule never matches

Use Simulator and inspect the condition trace.

Common causes:

- using `event.environment` when the value is in `labels.environment`;
- wrong capitalization;
- comparing a string to a JSON array incorrectly;
- raw payload path differs from the normalized event;
- optional label is absent;
- regex anchors or escaping are incorrect;
- an earlier rule changed the field;
- the rule is disabled.

### `in` or `not_in` does not validate

Enter a JSON collection:

```json
["critical", "fatal"]
```

Do not enter only:

```text
critical
```

### A template fails

A referenced field is probably absent or contains a non-scalar object.

Use `default` for optional fields:

```text
{{ labels.cluster | default("unknown") }}
```

Test with the optional label removed.

### A selected route is rejected

Confirm that:

- the route is enabled;
- the route belongs to the orchestration group;
- the route source equals the event source;
- the route team is active;
- selected service and policies belong to the same team where required.

### The event is visible but nobody was notified

Check whether the execution disposition is `suppress`, whether a silence or maintenance window matched, and whether a notification policy found a target.

An orchestration-suppressed event is intentionally stored while notification and escalation are disabled.

### The event is missing from Alerts

Check the execution disposition:

- `drop` means no alert was created;
- `pause` means the event is pending and may activate later;
- a resolve may have arrived before a paused event activated.

### A paused event never activates

Check:

- the scheduler process is running;
- the pending event has not already resolved;
- activation time has passed;
- repeated events with `retrigger=reset` are not continually extending the delay;
- scheduler and pending-event logs for safe error types.

### A webhook is not sent

Check:

- runtime mode is `active`, not shadow;
- the orchestration execution was applied successfully;
- the webhook action is enabled;
- the scheduler is running;
- the URL uses HTTPS unless HTTP is explicitly enabled;
- private-address targets are allowed by configuration;
- rate or concurrency limits are not delaying delivery;
- the webhook execution status and safe error message.

### Publish is unavailable

The user must be a group editor or global administrator for the selected group. Confirm active group membership and the group role.

### Changes appear under another author

The version list distinguishes:

- creator of the version;
- last user who changed its draft;
- user who published it.

When one user edits and another publishes, **Changed by** and **Published by** are expected to differ.

## Operational design recommendations

### Give rules business names

Good:

```text
Critical production database routing
Suppress development backup warnings
Delay transient endpoint failures
```

Less useful:

```text
Rule 1
New rule
Test
```

### Explain why, not only what

Use descriptions and publication comments to record the operational reason.

Example:

```text
Suppress warning-level backup events in development because they are reviewed in the daily report and must not page on-call.
```

### Prefer explicit conditions

Prefer:

```text
labels.environment equals production
AND labels.component equals database
AND event.severity equals critical
```

instead of:

```text
event.title contains DB
```

Structured labels are more stable than human-readable text.

### Keep mutually exclusive routing rules ordered

Put the most specific rules first and stop after a routing match.

```text
1. Payments production critical
2. Payments other
3. Other production
4. Catch-all
```

### Separate normalization from final decisions

A clear definition often follows this order:

```text
1. Normalize labels and severity
2. Select ownership
3. Select priority and policies
4. Set grouping
5. Apply suppress/pause/drop decisions
6. Queue automation
```

### Avoid hidden coupling

When a later rule depends on a field changed earlier, document it in both rule descriptions.

### Test both directions

For each important rule, test:

- a matching event;
- a near match that must not match;
- missing optional fields;
- resolved status;
- another environment;
- another source;
- existing active version comparison.

### Review destructive decisions separately

Treat these as high risk:

- `drop`;
- broad `suppress`;
- long `pause`;
- route replacement;
- `set_event_action resolve`;
- grouping-key changes;
- orchestration compatibility mode.

Use replay and shadow observation before activation.

## Frequently asked questions

### Does saving a draft affect production?

No. Production uses the published active version, subject to runtime mode.

### Does publishing immediately apply rules?

Publishing updates the active version, but a runtime mode of `disabled` still prevents execution. In shadow mode the version is evaluated without changing production behavior.

### Can a group editor publish?

Yes. A group editor can edit, validate, simulate, replay, publish and rollback orchestrations in that group.

### Can a group editor create webhook actions?

No. Reusable webhook-action management remains restricted to global administrators.

### Does `stop` mean the alert is discarded?

No. It stops later orchestration rules. The event continues into the normal lifecycle with the decisions already made.

### What is the difference between `suppress` and a silence?

Both can prevent notifications. Orchestration suppression is a rule-engine decision recorded on the alert and can depend on mutated fields or ordered rule logic. A silence is a dedicated alert-suppression configuration and is usually clearer for temporary or independently managed suppression windows.

### What is the difference between `pause` and an Alertmanager `for` duration?

An upstream `for` duration prevents Alertmanager from sending the alert until the expression remains true. Orchestration pause acts after IncidentRelay receives the event, stores a pending event and can cancel it when a matching resolve arrives before activation.

### Can orchestration call scripts?

No. Arbitrary Python, shell, SSH and container execution are not supported. Use a secured asynchronous webhook to a purpose-built automation service.

### Can I use raw payload fields?

Yes, through `raw.<path>`, but normalized `event` and `labels` fields are usually more portable across integrations and easier to test.

### Can I undo a publication?

Yes. Use Versions and rollback. IncidentRelay publishes a new copy of the selected historical definition instead of changing old history.

### Where can I see why an event was handled a certain way?

Open the orchestration's **Executions** tab and view the trace. The alert Explain trace also includes orchestration runtime information when available.

## Related documentation

- [Event Orchestration API](../api/event-orchestration.md)
- [Event Orchestration architecture](../architecture/event-orchestration-v1.md)
- [Alerts and alert groups](alerts.md)
- [Groups and RBAC](../concepts/groups-and-rbac.md)
- [Services](../concepts/services.md)
- [Escalation Policies](../concepts/escalation-policies.md)
- [Notification channels](../integrations/channels.md)
- [Administration logging](../administration/logging.md)
