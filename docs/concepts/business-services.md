# Business Services

Business Services describe customer-facing or business-facing capabilities that depend on one or more technical services.

Examples:

- Checkout
- Login
- Payments
- Customer API
- Openstack Cloud
- Partner Integrations

A technical `Service` answers the question: **which system or component is affected?**

A `BusinessService` answers the question: **which user-facing capability is affected, and how severe is the business impact?**

Business Services are intentionally separate from technical Services. A single Business Service can depend on many technical Services, and a single technical Service can be part of multiple Business Services.

## Business Service vs Service

| Concept | Purpose |
| --- | --- |
| `Service` | Technical service, component, system, application, database, queue, infrastructure unit. |
| `BusinessService` | Business-facing capability built from technical services. |
| `BusinessServiceComponent` | Mapping between a Business Service and a technical Service. |
| `BusinessServiceIncidentImpact` | Persisted snapshot that links an alert group to business impact. |
| `BusinessServiceStatusHistory` | Historical status changes for a Business Service. |

Example:

```text
Business Service: Checkout
Components:
- checkout-api
- billing-api
- postgres-payments
- redis-checkout
```

If `billing-api` is degraded, the `Checkout` Business Service can become degraded or partially unavailable depending on the component criticality and impact weight.

## Components

A Business Service is calculated from enabled components.

Each component has:

| Field | Meaning |
| --- | --- |
| Technical service | Technical Service that participates in the calculation. |
| Criticality | How important this component is for the Business Service. |
| Impact weight | 0-100 multiplier for the component impact score. |
| Position | Sort order in UI. |
| Enabled | Disabled components are saved but ignored by status calculation and business impact detection. |
| Description | Optional internal explanation. |

Supported component criticality values:

```text
required
critical
important
optional
informational
```

`required` and `critical` components have the strongest effect on Business Service status. `optional` and `informational` components have reduced or no visible impact depending on status and weight.

## Raw service status vs effective status

Business Services use **effective component status**, not only raw `Service.status`.

Raw service status is the persisted technical Service status:

```text
service.status = operational
```

Effective status is calculated by the Service Impact engine from:

```text
raw service status
+ open alert groups
+ upstream/downstream dependency impact
= effective service status
```

This means a component can show:

```text
raw service_status: operational
effective_status: degraded
effective_status_reason: upstream_dependency
```

This is expected. The technical Service itself may still be marked operational, while the runtime impact calculation says the service is currently degraded because of an active alert or dependency issue.

Business Services use `effective_status` so that business impact matches the same logic used by Service Impact v2.

## Status calculation

Business Service status is calculated from enabled components.

Each component gets an impact score based on:

```text
effective component status
x component criticality multiplier
x impact weight
```

The highest component score becomes the Business Service impact score.

The impact score is then converted to Business Service status.

Typical statuses:

```text
unknown
operational
degraded
partial_outage
major_outage
maintenance
```

The exact scoring thresholds are implemented in `app/services/business_services/status.py`.

## Dependency-aware impact

Business Services can be affected by direct components and by upstream dependencies.

Example:

```text
Business Service: Openstack Cloud
Component: Openstack

Openstack depends on Cloud computes
Alert fires on Cloud computes
```

Even if `Cloud computes` is not a direct Business Service component, the Business Service can still be affected because `Openstack` has effective degradation caused by an upstream dependency.

In that case the incident impact relation can be stored as:

```text
dependency_upstream_alert
```

Direct component alerts are stored as:

```text
component_alert
```

## Manual status override

Business Services support manual status override.

Manual override is an operational action used when the calculated status does not fully describe customer impact.

Examples:

```text
Technical services recovered, but customers still see degraded checkout.
Set Checkout to degraded for 30 minutes.
```

```text
A technical warning exists, but customers are not affected.
Set Business Service to operational until the alert is fixed.
```

Manual override has priority over calculated status while it is active.

Manual override fields:

| Field | Meaning |
| --- | --- |
| manual_status | Override status. |
| manual_status_message | Optional operator message. |
| manual_status_until | Optional expiration time. If empty, override stays active until cleared. |
| manual_status_set_by_id | User that set the override. |
| manual_status_set_at | Time when override was set. |
| manual_status_active | Whether override is currently active. |

When manual override expires, it is ignored and can be cleared during recalculation.

Clearing manual override recalculates the Business Service status from effective component status.

## Business impact records

When an alert group affects a Business Service, IncidentRelay persists a `BusinessServiceIncidentImpact` record.

This record stores:

```text
business_service
group
service
impact_status
impact_score
relation
reason
component_snapshot
active
first_seen_at
last_seen_at
```

The snapshot is useful because it preserves the business impact context at the time of the incident.

When an alert is resolved or no longer affects the Business Service, the impact record is deactivated.

## Status history

Business Service status changes are recorded in `BusinessServiceStatusHistory`.

History is written when one of these changes:

```text
status
status_source
status_message
```

Status source can be:

```text
calculated
manual
```

Repeated recalculations with the same status/source/message do not create duplicate history entries.

## UI behavior

The Business Services page shows:

- summary cards
- business service list
- status badge
- owner team
- component count
- public/private flag
- action menu
- details modal
- components table
- manual status override controls
- status history

The details modal uses the full details API response. Components and status history should be rendered from the same response as the Business Service details.

## Status badges

Business Service UI uses the shared status badge helper and styles:

```text
uiStatusBadge(...)
uiStatusBadgeVariantForStatus(...)
.ui-status-badge
.ui-status-badge-success
.ui-status-badge-warning
.ui-status-badge-danger
.ui-status-badge-info
.ui-status-badge-muted
```

Page-specific status color classes should not be used for Business Services.

## Current limitations

The current implementation intentionally does not include:

- public status page rendering
- notification templates for Business Services
- analytics dashboards
- automatic stakeholder assignment
- fine-grained alert impact policy for warning/info alerts

Warning alerts can still influence effective status according to the current Service Impact v2 logic. A more precise impact policy should be added later in the shared Service Impact layer, so Business Services automatically inherit it.

## Recommended workflow

1. Create technical Services and dependencies.
2. Create a Business Service.
3. Add technical Services as components.
4. Set component criticality and impact weight.
5. Trigger or ingest alerts.
6. Check Business Service list and details.
7. Use manual override only when calculated status does not match real customer impact.

## Troubleshooting

### Component is degraded but Business Service is still operational

Check that the Business Service was recalculated and that the component is enabled.

Business Service status should be recalculated by:

- details endpoint
- recalculate endpoint
- component create/update/delete
- alert lifecycle refresh
- downstream dependency refresh

### Manual status does not change after recalculation

Manual override has priority while active. Clear the manual override or wait until `manual_status_until` expires.

### Components disappear after setting manual status

Manual status endpoints should return the same full details payload as `GET /api/business-services/{id}`, including `components` and `status_history`.

### List status differs from details status

The list endpoint should recalculate Business Services before serialization, or lifecycle refresh must keep persisted status fresh. The preferred implementation is to recalculate list items before returning the list response.
