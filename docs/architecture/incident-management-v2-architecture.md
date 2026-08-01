# Incident Management v2

**Status:** Proposed  
**Target:** Production-ready staged delivery  
**Project:** IncidentRelay  
**Suggested document path:** `docs/architecture/incident-management-v2.md`

## 1. Purpose

Incident Management v2 introduces an optional operational incident workflow on top of the existing IncidentRelay alert lifecycle.

The goal is to preserve the current alert ingestion, grouping, escalation, notification, responder, stakeholder, comment, correlation and service-impact behavior while adding a first-class record for problems that require coordinated investigation, external ticketing, classification, reporting and closure.

The implementation must not create a second competing alert lifecycle.

## 2. Current state

IncidentRelay already provides most of the technical foundation:

- `Alert` stores a normalized technical signal;
- `AlertGroup` groups related alerts and currently acts as the day-to-day incident aggregate;
- manual incidents are created as an `AlertGroup` with one manual child `Alert`;
- multiple groups can be merged;
- P1-P5 incident priorities are supported;
- assignees, responders and stakeholders are supported;
- comments and timeline events are supported;
- acknowledgement, resolution, escalation and notification delivery are supported;
- service and business impact are calculated from alert groups;
- audit events are already written for many incident actions;
- `/api/incidents` currently exposes alert groups as incidents.

The missing part is an optional managed workflow that distinguishes a technical alert group from an operational incident record.

## 3. Architectural decision

### 3.1 Keep `AlertGroup` as the technical aggregate

`AlertGroup` remains responsible for:

- alert deduplication and grouping;
- firing, acknowledged, silenced, maintenance and resolved state;
- notification and escalation state;
- assignee and priority;
- service impact;
- child alerts;
- existing responders, stakeholders, comments and timeline.

This avoids a high-risk migration of the current lifecycle.

### 3.2 Add an optional `ManagedIncident`

A `ManagedIncident` is created only when an alert group is promoted into a coordinated operational incident.

Creation methods:

- manual incident creation;
- operator action: **Declare incident**;
- alert classification: `Incident`;
- later: Event Orchestration action;
- later: duration, escalation or correlation automation.

Not every alert group must have a `ManagedIncident`.

### 3.3 Keep alert classification separate

Classification describes the operational outcome of an alert group and must not replace its lifecycle status.

Examples:

- Incident;
- False Positive;
- Duplicate;
- Known Issue;
- No Action Required;
- Planned Activity;
- Test Alert;
- Other.

A group may be `resolved` and classified as `False Positive`. A group may be `firing` and already classified as `Incident`.

## 4. Terminology

```text
Alert
  One normalized technical signal stored by IncidentRelay.

Alert Group
  A technical aggregation of one or more Alerts. It owns the current alert,
  notification and escalation lifecycle.

Managed Incident
  An optional operational record attached to a primary Alert Group and, later,
  to additional related Alert Groups.

Classification
  The reviewed outcome of an Alert Group. It is independent from alert status
  and managed-incident status.
```

## 5. Goals

The staged implementation should provide:

1. Optional alert-group classification.
2. Optional requirement to classify before manual closure.
3. Manual promotion of an alert group to a managed incident.
4. Automatic creation of a managed incident for manual incidents.
5. A dedicated managed-incident list and workspace.
6. Operational workflow status separate from alert status.
7. Related alert-group linking without requiring destructive merge.
8. Duplicate classification linked to a canonical incident.
9. Root-cause and resolution summaries.
10. External ticket references.
11. A provider-neutral ITSM integration framework.
12. Event Orchestration integration.
13. Incident metrics and reports.
14. Complete audit, timeline, RBAC, OpenAPI and user documentation.

## 6. Non-goals for the first release

The first release should not include:

- full bidirectional synchronization with every ITSM provider;
- ML-based incident creation or grouping;
- automatic root-cause analysis;
- arbitrary cross-group ownership across unrelated security groups;
- replacement of `AlertGroup` notification or escalation logic;
- automatic destructive merging of alert groups;
- mandatory classification for every team;
- blocking source-driven automatic resolution when classification is missing;
- a complete post-incident review editor.

## 7. Domain model

### 7.1 Alert-group classification

Add nullable classification fields to `AlertGroup` or a one-to-one review model.

Suggested fields:

```text
classification                 nullable slug
classification_note            nullable text
classified_by_id               nullable user
classified_at                  nullable datetime
classification_incident_id     nullable managed incident
```

Recommended built-in slugs:

```text
incident
false_positive
duplicate
known_issue
no_action_required
planned_activity
test_alert
other
```

Rules:

- classification is optional by default;
- changing classification creates timeline and audit events;
- `incident` may create or link a `ManagedIncident`;
- `duplicate` should require a canonical alert group or managed incident;
- automatic source resolution must not fail because classification is missing;
- a team may require classification before manual close, not before automatic resolve.

### 7.2 ManagedIncident

Suggested fields:

```text
id
primary_group_id               unique alert group
team_id
service_id                     nullable
workflow_status                declared | investigating | identified |
                               monitoring | resolved | closed | cancelled
summary                        nullable text
root_cause                     nullable text
resolution_summary             nullable text
declared_by_id                 nullable user
declared_at
investigation_started_at       nullable datetime
identified_at                  nullable datetime
monitoring_at                  nullable datetime
resolved_at                    nullable datetime
closed_by_id                   nullable user
closed_at                      nullable datetime
created_at
updated_at
```

Priority, assignee, responders, stakeholders and notification state remain on the primary `AlertGroup` in the first version.

Rules:

- one alert group may be the primary group of at most one managed incident;
- manual incidents create a managed incident automatically;
- closing a managed incident does not delete or archive its alerts;
- alert-group resolution may move the managed incident to `resolved`, but never automatically to `closed`;
- an unresolved linked group may reopen an incident from `resolved` or `monitoring`;
- `closed` is an explicit operational action.

### 7.3 ManagedIncidentGroupLink

Use a relation rather than destructive merge when groups must remain independently traceable.

Suggested fields:

```text
id
incident_id
group_id
relation_type                  primary | related | symptom | duplicate
linked_by_id
linked_at
removed_by_id                  nullable
removed_at                     nullable
```

Rules:

- the primary group has relation type `primary`;
- one group cannot be actively linked twice to the same incident;
- adding or removing a group creates timeline and audit events;
- linked groups keep their own source, deduplication and timeline;
- existing manual merge remains available for cases where groups truly should become one technical aggregate.

### 7.4 IncidentExternalReference

Suggested fields:

```text
id
incident_id
provider                       jira_service_management | servicenow | glpi |
                               generic | other
external_id
external_key                   nullable
url
external_status                nullable
source_of_truth                incidentrelay | external | link_only
sync_status                    idle | pending | synced | failed | disabled
last_synced_at                 nullable
last_error                     nullable
metadata_json                  nullable
created_by_id
created_at
updated_at
```

Secrets and provider configuration must not be stored in this table.

### 7.5 Incident integration configuration

Provider credentials and field mappings should live in a group-owned integration configuration.

Suggested capabilities:

- provider type;
- base URL;
- encrypted or protected credentials;
- project or queue identifier;
- priority mapping;
- status mapping;
- service/team mapping;
- source-of-truth mode;
- inbound webhook secret;
- enabled actions;
- retry policy.

## 8. Lifecycle model

### 8.1 Alert lifecycle remains unchanged

```text
firing
acknowledged
silenced
maintenance
resolved
```

This state controls notifications, escalation and technical impact.

### 8.2 Managed-incident workflow

```text
declared
  -> investigating
  -> identified
  -> monitoring
  -> resolved
  -> closed
```

Optional transitions:

```text
declared -> cancelled
resolved -> investigating     when a linked alert reopens
closed -> investigating       explicit reopen action
```

### 8.3 Synchronization rules

Recommended first-version defaults:

- declaring an incident does not change the alert-group status;
- acknowledging the primary group may optionally move `declared` to `investigating`;
- when all actively linked groups resolve, the incident may move to `resolved`;
- a managed incident is never auto-closed;
- if any linked group becomes unresolved again, a resolved incident reopens to `investigating`;
- classification remains unchanged when status changes;
- closing may require classification according to group settings.

## 9. Classification policy

Suggested group-level mode:

```text
off
optional
required_before_manual_close
```

Important behavior:

- automatic resolution from an integration is always accepted;
- when classification is required, an automatically resolved group is marked as needing review;
- the UI shows a review queue instead of keeping the technical alert firing;
- manual resolve/close prompts for classification when configured;
- teams that do not use classification retain the current workflow.

Suggested classification actions:

```text
Incident
  Offer to create or open the managed incident.

Duplicate
  Require selection of a canonical group or managed incident.

Known Issue
  Allow an optional problem/ticket reference.

False Positive / Test Alert / Planned Activity / No Action Required
  Store the outcome without creating an incident.
```

## 10. Permissions

Use existing team/group RBAC.

### Read

Allowed for users who may read the primary incident team.

### Classify and operate

Allowed for:

- global admin;
- group editor for the team group;
- team manager;
- team responder.

### Configure classification and ITSM integrations

Allowed for:

- global admin;
- group editor for the owning group.

### Cross-group linking

A user must have read access to both groups and write/respond access to the managed incident team. Cross-group links must not expose data from an inaccessible group.

## 11. API strategy

The existing `/api/incidents` path currently represents `AlertGroup` and must remain backward compatible.

Recommended additive API:

```text
GET    /api/managed-incidents
POST   /api/managed-incidents
GET    /api/managed-incidents/{id}
PATCH  /api/managed-incidents/{id}
POST   /api/managed-incidents/{id}/status
POST   /api/managed-incidents/{id}/close
POST   /api/managed-incidents/{id}/reopen
GET    /api/managed-incidents/{id}/groups
POST   /api/managed-incidents/{id}/groups
DELETE /api/managed-incidents/{id}/groups/{group_id}
GET    /api/managed-incidents/{id}/external-references
POST   /api/managed-incidents/{id}/external-references
PATCH  /api/managed-incidents/{id}/external-references/{reference_id}
DELETE /api/managed-incidents/{id}/external-references/{reference_id}

PUT    /api/incidents/{group_id}/classification
DELETE /api/incidents/{group_id}/classification
POST   /api/incidents/{group_id}/declare
```

A later major API version may rename concepts after a deprecation period.

## 12. UI architecture

### 12.1 Alerts page

Keep the current Alerts page for all alert groups.

Add:

- classification badge and filter;
- **Classify** action;
- **Declare incident** action;
- **Link to incident** action;
- review-required filter;
- canonical incident link for duplicates.

### 12.2 Managed Incidents page

Add a dedicated top-level page, not an Administration page.

List filters:

- workflow status;
- team and service;
- priority;
- assignee;
- classification;
- external provider/status;
- open/resolved/closed period;
- search.

### 12.3 Managed Incident workspace

Sections:

- summary and current status;
- primary and related alert groups;
- active alerts and source state;
- priority, assignee and service;
- responders and stakeholders;
- comments and activity timeline;
- root cause and resolution summary;
- external tickets;
- runbooks, dashboards and service links;
- impact and dependencies;
- audit metadata.

## 13. Event Orchestration integration

Add actions only after manual workflows are stable.

Suggested actions:

```text
declare_incident
set_alert_classification
attach_to_open_incident
create_incident_draft
set_incident_priority
```

Suggested triggers:

- severity or priority;
- service or route;
- labels and source;
- no similar open incident;
- alert duration threshold;
- escalation step reached;
- correlation confidence.

Duration and escalation triggers require asynchronous hooks and must not be implemented as purely intake-time rules.

## 14. ITSM integration architecture

Use a provider-neutral service interface and an outbox/retry model.

Suggested provider interface:

```text
create_external_incident()
update_external_incident()
add_external_comment()
resolve_external_incident()
fetch_external_incident()
handle_inbound_webhook()
validate_configuration()
```

First delivery should support **link-only** external references. The first active provider can then be Jira Service Management.

Recommended rollout:

1. Store external ID and URL manually.
2. Create JSM ticket from IncidentRelay.
3. Push selected updates from IncidentRelay.
4. Receive JSM webhook updates.
5. Add configurable source-of-truth and conflict handling.

## 15. Reporting

Initial metrics:

- managed incidents created;
- conversion rate from alert group to managed incident;
- incidents by service, team and priority;
- classification distribution;
- false-positive rate;
- duplicate rate;
- time to acknowledge;
- time to declare;
- time to investigation;
- time to resolve;
- time to close;
- reopen count;
- linked alert-group count;
- incidents with external tickets;
- external synchronization failures.

Do not overload MTTR terminology. Reports should expose the exact measured timestamps.

## 16. Audit and timeline

Suggested event names:

```text
alert_classification_set
alert_classification_changed
alert_classification_cleared
incident_declared
incident_status_changed
incident_closed
incident_reopened
incident_group_linked
incident_group_unlinked
incident_external_reference_added
incident_external_reference_updated
incident_external_reference_removed
incident_external_sync_failed
incident_root_cause_updated
incident_resolution_updated
```

Every mutation must write both:

- a user-visible timeline event where operationally useful;
- an `AuditLog` entry with group/team scope and redacted data.

## 17. Migration and compatibility

Recommended migration strategy:

- add nullable classification fields;
- add new managed-incident tables;
- do not rename or rebuild `AlertGroup`;
- do not backfill managed incidents for every historical group;
- create a managed incident automatically for new manual incidents;
- optionally backfill existing unresolved manual incidents;
- keep all new API fields nullable and additive;
- keep existing `/api/incidents` behavior;
- use feature flags for the managed-incident page and automatic synchronization.

## 18. Delivery phases

### Phase 1: Classification foundation

- classification fields and validation;
- timeline and audit;
- UI action and filters;
- optional classification policy;
- duplicate target selection;
- reporting counts;
- OpenAPI and documentation.

### Phase 2: Managed incident core

- `ManagedIncident` model;
- manual declaration from an alert group;
- automatic record for manual incidents;
- workflow statuses;
- root cause and resolution fields;
- dedicated API;
- lifecycle synchronization hooks.

### Phase 3: Incident workspace

- managed-incident list;
- details workspace;
- responders, stakeholders and comments reuse;
- service/runbook/dashboard context;
- close and reopen flows;
- review queue.

### Phase 4: Related alert groups

- non-destructive group links;
- duplicate links;
- add/remove related group;
- overlap and permission checks;
- improved merge flow;
- safe split design and implementation.

### Phase 5: Automation

- Event Orchestration actions;
- automatic declaration rules;
- draft-and-confirm mode;
- duration and escalation hooks;
- idempotency and duplicate prevention.

### Phase 6: External ITSM foundation

- external reference model;
- connector configuration;
- outbox and retries;
- link-only generic integration;
- Jira Service Management create/update;
- webhook authentication and mapping.

### Phase 7: Reporting and post-incident workflow

- incident metrics dashboard;
- classification and quality reports;
- export API;
- post-incident review fields;
- follow-up actions and ownership.

### Phase 8: Production hardening

- load and permission tests;
- audit coverage;
- structured logs and metrics;
- sync-loop prevention;
- OpenAPI completeness;
- user and administrator documentation;
- migration and rollback testing.

## 19. Recommended first production scope

The first production release should include Phases 1-3 and the non-destructive part of Phase 4:

- optional classification;
- managed incident declaration;
- dedicated incident page;
- workflow status;
- root cause and resolution summary;
- manual related-group links;
- manual external ticket URL;
- complete RBAC, audit and documentation.

It should not wait for full automatic correlation or bidirectional ITSM synchronization.

## 20. Success criteria

The architecture is successful when:

- teams can continue using IncidentRelay exactly as before without enabling the feature;
- operators can distinguish a technical alert group from a managed operational incident;
- classification provides reliable alert-quality data;
- manual incidents and promoted alert groups use one consistent workspace;
- related alerts can be attached without destroying their original lifecycle;
- external ticketing can be added without provider-specific fields in the core model;
- the current notification and escalation lifecycle remains stable;
- all access is enforced using existing group/team RBAC.
