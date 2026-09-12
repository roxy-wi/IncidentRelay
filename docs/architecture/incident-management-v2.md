# Incident Management v2

**Status:** Proposed  
**Target:** Production-ready staged delivery  
**Project:** IncidentRelay  
**Suggested document path:** `docs/architecture/incident-management-v2.md`

## 1. Purpose

Incident Management v2 separates the operational Incident workflow from the existing IncidentRelay alert lifecycle.

The goal is to preserve the current alert ingestion, grouping, escalation, notification, responder, stakeholder, comment, correlation and service-impact behavior while adding a first-class `Incident` record for problems that require coordinated investigation, external ticketing, classification, reporting and closure.

The implementation must not create a second competing alert lifecycle. `AlertGroup` remains the technical aggregate, while `Incident` becomes a separate operational entity.

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

The missing part is a separate operational Incident entity. The current manual incident workflow must remain available as manual Alert Group creation, while manual Incident creation must create an actual Incident.

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

This avoids a high-risk migration of the current technical lifecycle.

### 3.2 Add a separate `Incident`

An `Incident` is a first-class operational record that may exist without Alert Groups or link one or more related Alert Groups.

Creation methods:

- manual Incident creation;
- operator action: **Create Incident** from an Alert Group;
- alert classification: `Incident`;
- later: Event Orchestration action;
- later: duration, escalation or correlation automation.

Not every Alert Group must have an Incident.

### 3.3 Keep both manual creation workflows

The current manual creation behavior remains available under the correct name:

```text
Create Alert Group
  -> AlertGroup
  -> one manual child Alert
```

A separate action creates an Incident:

```text
Create Incident
  -> standalone Incident
  -> optionally linked Alert Groups
```

Creating an Alert Group must not create an Incident. Creating an Incident must not create a hidden Alert Group or Alert.

### 3.4 Keep alert classification separate

Classification describes the operational outcome of an Alert Group and must not replace its lifecycle status.

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

Incident
  A separate operational record that may exist without Alert Groups or link
  one or more related Alert Groups.

Classification
  The reviewed outcome of an Alert Group. It is independent from alert status
  and incident status.
```

## 5. Goals

The staged implementation should provide:

1. Optional alert-group classification.
2. Optional requirement to classify before manual closure.
3. Separate `AlertGroup` and `Incident` entities.
4. Manual Alert Group creation with one child Alert.
5. Manual standalone Incident creation and optional linking from Alert Groups.
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
classification_incident_id     nullable incident
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
- `incident` may create or link an `Incident`;
- `duplicate` should require a canonical Alert Group or Incident;
- automatic source resolution must not fail because classification is missing;
- a team may require classification before manual close, not before automatic resolve.

### 7.2 Incident

Suggested fields:

```text
id
team_id
service_id                     nullable
workflow_status                declared | investigating | identified |
                               monitoring | resolved | closed | cancelled
title
description                    nullable text
priority                       nullable
assignee_id                    nullable user
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

Responders, stakeholders, comments and operational timeline belong to the Incident. Notification and escalation state remain on `AlertGroup`.

Rules:

- an Incident may exist without an Alert Group;
- an Incident may link one or more Alert Groups;
- manual Incident creation creates only an Incident;
- closing an Incident does not delete, archive or resolve linked Alert Groups;
- Alert Group resolution may move the Incident to `resolved`, but never automatically to `closed`;
- an unresolved linked group may reopen an Incident from `resolved` or `monitoring`;
- `closed` is an explicit operational action.

### 7.3 IncidentAlertGroupLink

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

- an Incident may have no linked Alert Groups;
- one Alert Group cannot be actively linked twice to the same incident;
- adding or removing a group creates timeline and audit events;
- linked Alert Groups keep their own source, deduplication and timeline;
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

### 8.2 Incident workflow

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

- creating or linking an Incident does not change Alert Group status;
- creating a manual Alert Group does not create an Incident;
- creating a manual Incident does not create an Alert Group;
- acknowledging an Alert Group does not automatically change Incident status;
- when all actively linked groups resolve, the Incident may move to `resolved`;
- an Incident is never auto-closed;
- if any linked group becomes unresolved again, a resolved Incident reopens to `investigating`;
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
  Offer to create an Incident or link the Alert Group to an existing Incident.

Duplicate
  Require selection of a canonical Alert Group or Incident.

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

A user must have read access to both groups and write/respond access to the incident team. Cross-group links must not expose data from an inaccessible group.

## 11. API strategy

This release changes the API semantics directly without introducing an intermediate API.

The current Alert Group behavior moves from `/api/incidents` to `/api/alert-groups`.

```text
GET    /api/alert-groups
POST   /api/alert-groups
GET    /api/alert-groups/{id}
PATCH  /api/alert-groups/{id}
POST   /api/alert-groups/{id}/acknowledge
POST   /api/alert-groups/{id}/resolve
POST   /api/alert-groups/{id}/reopen
POST   /api/alert-groups/{id}/merge
PUT    /api/alert-groups/{id}/classification
DELETE /api/alert-groups/{id}/classification
POST   /api/alert-groups/{id}/create-incident
```

`POST /api/alert-groups` preserves the current manual creation behavior and creates an `AlertGroup` with one manual child `Alert` in one transaction.

`/api/incidents` becomes the actual Incident API:

```text
GET    /api/incidents
POST   /api/incidents
GET    /api/incidents/{id}
PATCH  /api/incidents/{id}
POST   /api/incidents/{id}/status
POST   /api/incidents/{id}/close
POST   /api/incidents/{id}/reopen
GET    /api/incidents/{id}/alert-groups
POST   /api/incidents/{id}/alert-groups
DELETE /api/incidents/{id}/alert-groups/{group_id}
GET    /api/incidents/{id}/external-references
POST   /api/incidents/{id}/external-references
PATCH  /api/incidents/{id}/external-references/{reference_id}
DELETE /api/incidents/{id}/external-references/{reference_id}
```

`POST /api/incidents` creates only an Incident and may optionally link existing Alert Groups. It must not create a hidden Alert Group or Alert.

This is a documented breaking API change. OpenAPI, frontend calls, tests and integration documentation must be updated in the same release.

## 12. UI architecture

### 12.1 Alerts page

Keep the current Alerts page for all alert groups.

Add:

- **Create Alert Group** action that creates an AlertGroup and one manual child Alert;
- classification badge and filter;
- **Classify** action;
- **Create Incident** action;
- **Link to incident** action;
- review-required filter;
- canonical incident link for duplicates.

### 12.2 Incidents page

Add a dedicated top-level page, not an Administration page.

Add a separate **Create Incident** action. It creates only an Incident and may optionally link existing Alert Groups.

List filters:

- workflow status;
- team and service;
- priority;
- assignee;
- classification;
- external provider/status;
- open/resolved/closed period;
- search.

### 12.3 Incident workspace

Sections:

- summary and current status;
- related Alert Groups;
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
create_alert_group
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

- Incidents created;
- manually created Alert Groups;
- manually created Incidents;
- conversion rate from Alert Group to Incident;
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

## 17. Migration and breaking compatibility policy

Incident Management Core is an intentional breaking change in IncidentRelay 2.3.

Backward API compatibility is not preserved.

The project will not introduce:

```text
/api/managed-incidents
/api/v2/incidents
legacy /api/incidents AlertGroup aliases
runtime compatibility switches
```

Recommended migration strategy:

- add new Incident and Incident-to-AlertGroup relation tables;
- do not rename or rebuild `AlertGroup`;
- preserve every existing Alert Group and child Alert;
- move current Alert Group API behavior to `/api/alert-groups`;
- replace `/api/incidents` with the actual Incident API in 2.3;
- rename the current manual incident action to **Create Alert Group** without changing its behavior;
- keep records created by the old manual action as manual Alert Groups with their child Alerts;
- make **Create Incident** create only an Incident;
- do not backfill Incidents for every historical Alert Group;
- create or link historical Incidents only through an explicit migration rule or administrator action;
- update OpenAPI, frontend calls, tests and documentation atomically with the 2.3 breaking release.

Database migration must preserve supported historical data, but preserving data does not imply preserving old API semantics.

## 18. Versioned delivery roadmap

### IncidentRelay 2.3: Incident Management Core

Goal: ship a minimal but production-usable first-class Incident workflow.

Scope:

- separate `Incident` model;
- `IncidentAlertGroupLink`;
- manual standalone Incident creation;
- **Create Incident** from AlertGroup;
- link/unlink AlertGroups;
- independent Incident workflow status;
- Incident team, service, priority and assignee;
- explicit close/reopen flow;
- move AlertGroup API to `/api/alert-groups`;
- replace `/api/incidents` with the first-class Incident API;
- dedicated Incidents list;
- minimal Incident workspace;
- RBAC, audit, timeline, migration, OpenAPI, UI tests and documentation.

Explicitly deferred from 2.3:

- AlertGroup classification;
- duplicate review workflow;
- full responders/stakeholders/comments workspace;
- role-aware on-call scheduling;
- Incident merge/split;
- Event Orchestration Incident actions;
- Jira/JSM automation;
- Incident analytics;
- full post-incident review.

### IncidentRelay 2.4: Incident Operations

Goal: expand the 2.3 Incident record into the operational collaboration workspace.

Scope:

- AlertGroup classification and review policy;
- review-required queue;
- duplicate canonical targets;
- related AlertGroup relation types;
- Incident merge and split;
- responders and stakeholders;
- Incident comments and richer activity;
- root cause and resolution summary;
- runbook/dashboard/service/impact context;
- lifecycle synchronization for linked AlertGroups;
- On-call Roles and role-aware Incident participant assignment;
- RBAC, audit, migration, OpenAPI, localization and regression coverage for the new scope.

### IncidentRelay 2.5: Incident Automation and ITSM

Goal: automate Incident declaration and integrate Incidents with external ticketing.

Scope:

- Event Orchestration Incident actions;
- automatic declaration and linking;
- draft-and-confirm mode;
- idempotency and duplicate prevention;
- duration and escalation hooks;
- `IncidentExternalReference`;
- provider-neutral ITSM integration;
- outbox, retries and dead-letter visibility;
- Jira/Jira Service Management create/update;
- shared Jira connection/client infrastructure;
- security, secret-redaction and SSRF/private-network controls.

### IncidentRelay 2.6: Analytics and Post-Incident Workflow

Goal: use stable Incident lifecycle data for reporting and post-incident improvement.

Scope:

- Incident metrics dashboard;
- classification and alert-quality reporting;
- export API;
- exact lifecycle timing metrics;
- post-incident review fields;
- follow-up actions and ownership;
- inbound Jira/JSM synchronization;
- loop prevention;
- configurable source-of-truth and conflict handling.

### Cross-release hardening rule

Production hardening is not deferred to a final phase.

Every release must include the RBAC, audit, timeline, tests, migrations, OpenAPI, localization and documentation required by the functionality shipped in that release.

Later releases may additionally expand load, concurrency, reconciliation, sync-loop and rollback-boundary testing.

## 19. IncidentRelay 2.3 release gate

Incident Management Core is ready to ship in 2.3 when:

- Alert, AlertGroup and Incident boundaries are explicit and tested;
- `/api/alert-groups` exposes AlertGroups;
- `/api/incidents` exposes only first-class Incidents;
- no backward-compatible AlertGroup alias remains under `/api/incidents`;
- manual AlertGroup creation creates one AlertGroup and one child Alert atomically;
- manual Incident creation creates only an Incident;
- an Incident can exist with zero linked AlertGroups;
- one Incident can link multiple independent AlertGroups;
- linked AlertGroups retain their technical lifecycle;
- Incident lifecycle does not overwrite linked AlertGroup lifecycle;
- operators can create and operate Incidents from the UI;
- close and reopen flows are explicit;
- RBAC and audit coverage are complete for the 2.3 scope;
- migration preserves supported historical AlertGroup data;
- OpenAPI and bundled UI use only the final 2.3 contracts.

Classification, role-aware scheduling, automation, Jira/JSM and analytics are not release blockers for 2.3.

## 20. Success criteria

The architecture is successful when:

- existing technical Alert Group processing remains stable;
- operators can distinguish a technical Alert Group from an operational Incident;
- manual Alert Group creation produces an AlertGroup and one child Alert;
- manual Incident creation produces only an Incident;
- Alert Groups can exist without Incidents;
- Incidents can exist without Alert Groups;
- classification provides reliable alert-quality data;
- one Incident can link one or more independent Alert Groups;
- related alerts can be attached without destroying their original lifecycle;
- external ticketing can be added without provider-specific fields in the core model;
- the current notification and escalation lifecycle remains stable;
- all access is enforced using existing group/team RBAC.
