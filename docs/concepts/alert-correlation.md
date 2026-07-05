title: Dependency-aware Alert Correlation
description: How IncidentRelay uses service dependencies to show possible root causes and downstream impact for related alert groups.
# Dependency-aware Alert Correlation

Dependency-aware alert correlation helps responders understand whether an alert may be related to another active alert in the service dependency graph.

It does not suppress notifications and it does not merge alert groups automatically.

Every alert group still follows the normal notification flow. Correlation only adds context:

    possible root cause
    possible downstream impact
    correlation score
    related alert group links
    timeline events

## How it works

Correlation uses existing service dependencies.

Example dependency graph:

    Frontend -> Billing API -> PostgreSQL

If `PostgreSQL` has an active critical alert and `Billing API` starts firing shortly after, IncidentRelay can mark the `Billing API` alert group as a possible symptom.

Example:

    PostgreSQL unavailable -> Billing API 5xx

For the Billing API alert group:

    Role: possible_symptom
    Possible root cause: PostgreSQL unavailable

For the PostgreSQL alert group:

    Role: possible_root_cause
    Possible downstream impact: Billing API 5xx

## What is stored

IncidentRelay stores correlation records between alert groups.

A saved correlation contains:

    root alert group
    related alert group
    root service
    related service
    dependency
    relation type
    direction
    score
    depth
    reason
    active flag
    timestamps

The stored record is used by alert details, notification rendering and timeline events.

## Relation types

`possible_root_cause`

The current alert group may be a symptom of an upstream alert.

Example:

    Auth API depends on PostgreSQL.
    PostgreSQL is firing.
    Auth API starts firing.
    Auth API shows PostgreSQL as a possible root cause.

`possible_downstream_impact`

The current alert group may be the root cause for downstream alerts.

Example:

    PostgreSQL is firing.
    Auth API depends on PostgreSQL and is also firing.
    PostgreSQL shows Auth API as possible downstream impact.

## Active alert groups

Correlation uses active alert groups only.

Active statuses:

    firing
    acknowledged

Resolved alert groups are not considered active. When an alert group is resolved, its active correlations are deactivated and a timeline event is recorded.

## Dependency settings

Each service dependency can control whether it participates in alert correlation.

Fields:

    correlation_enabled
    propagation_delay_seconds

`correlation_enabled` enables or disables alert correlation for one dependency.

`propagation_delay_seconds` defines how far apart related alerts may appear and still be considered likely connected. The default is `300` seconds.

Example:

    Billing API depends on PostgreSQL
    correlation_enabled = true
    propagation_delay_seconds = 300

This means an alert on PostgreSQL and an alert on Billing API are more likely to be correlated when they appear within roughly five minutes.

## Score

The score is a 0..100 confidence value.

The score considers:

    dependency direction
    dependency depth
    dependency type
    criticality
    service environment
    alert timing
    severity

A higher score means the relationship is more likely to be useful to a responder.

The score is not a guarantee. It is investigation context.

## Depth

Correlation can follow dependency chains.

Example:

    Frontend -> Billing API -> PostgreSQL

If PostgreSQL is firing and Frontend starts firing, IncidentRelay can create a two-hop correlation:

    PostgreSQL unavailable -> Frontend 5xx
    depth = 2

Shorter paths are preferred when multiple paths exist.

## Notifications

Correlation can be included in notification messages.

Supported visible surfaces:

    Slack
    Mattermost
    Telegram
    Email
    Generic webhook
    Microsoft Teams
    Discord
    Voice call templates

Browser push notifications do not include a detailed correlation block by default. Push notifications should stay short and link to alert details, where correlation is easier to read.

## Alert details

Alert details can show:

    possible root causes
    possible downstream impacts
    related alert group
    score
    dependency type
    criticality
    depth
    reason

The alert list can also show compact badges such as:

    Symptom
    Root cause
    Correlated 2

## Timeline events

Correlation lifecycle changes are written to the alert group timeline.

Examples:

    Correlation detected: #10 PostgreSQL: PostgreSQL unavailable -> #11 Auth API: Auth API 5xx
    Correlation deactivated: #10 PostgreSQL: PostgreSQL unavailable -> #11 Auth API: Auth API 5xx

Events are written to both related alert groups so responders can see the relationship from either side.

## What correlation does not do

Correlation does not:

    suppress notifications
    merge alert groups automatically
    resolve related alert groups
    change service status directly
    replace service impact calculation
    guarantee root cause correctness

It is intentionally advisory.

## Recommended setup

Use dependency correlation for important production dependencies.

Good candidates:

    API -> database
    API -> queue
    frontend -> backend API
    worker -> queue
    service -> external provider
    service -> shared infrastructure

Avoid enabling correlation for very loose or noisy informational dependencies unless responders actually need that context.

## Troubleshooting

### No correlation appears

Check:

    1. Both alert groups are active: firing or acknowledged.
    2. Both alert groups have services assigned.
    3. The services are connected by an enabled dependency.
    4. The dependency has correlation_enabled enabled.
    5. The related alerts are within the expected propagation delay.
    6. The services belong to the same team scope.
    7. The calculated score is high enough to be stored.

### Correlation appears but looks wrong

Check:

    1. The service match rule assigned the correct service.
    2. The dependency direction is correct.
    3. The dependency type and criticality are accurate.
    4. The propagation delay is not too large.
    5. Alert labels are not assigning unrelated alerts to the same service.

### Too many correlations

Reduce noise by:

    1. Disabling correlation on weak dependencies.
    2. Lowering propagation_delay_seconds.
    3. Using more precise service match rules.
    4. Avoiding broad catch-all services for unrelated alerts.
