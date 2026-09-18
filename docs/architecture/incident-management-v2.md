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
- technical comments and technical timeline;
- legacy responder/stakeholder data only during staged migration.

This avoids a high-risk migration of the current technical lifecycle.

#### Alert occurrence and reopen semantics

A resolved child `Alert` remains a terminal technical occurrence and is never
changed back to `firing`.

A resolved `AlertGroup`, however, may be reused when a new matching firing
occurrence arrives within a configurable reopen grace period.

In that case:

- the existing resolved child Alert remains resolved;
- a new child Alert is created for the new occurrence;
- the existing AlertGroup is reopened instead of creating another group;
- notification and escalation state is restarted according to the current
  lifecycle and acknowledgement rules;
- the reopen creates timeline and audit events;
- service and business impact are recalculated from the current child-alert
  state.

After the reopen grace period expires, a matching firing occurrence creates a
new AlertGroup.

`closed` is not added to the AlertGroup technical lifecycle. Terminal
operational closure belongs to the first-class Incident workflow.

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

### 3.5 Separate technical assignment from operational ownership

AlertGroup and Incident assignment intentionally answer different questions.

```text
AlertGroup.assignee
  Who is the current technical notification/escalation target?

Incident.assignee
  Who currently owns the operational investigation?
```

Rules:

- `AlertGroup` remains a first-class technical signal episode after first-class Incidents are introduced;
- `AlertGroup.assignee` continues to be selected and changed by route, schedule and escalation behavior;
- `Incident.assignee` is a concrete user assignment and may be manually assigned, reassigned or cleared;
- changing `Incident.assignee` must not mutate linked AlertGroup assignees, rotations, notification state or escalation progress;
- changing an AlertGroup assignee must not silently replace the Incident assignee;
- Incident assignment remains stable when the source on-call schedule rotates;
- in 2.4, On-call Roles may resolve current users and copy concrete users into Incident ownership/participant records;
- future automation may explicitly reassign an Incident, but schedule rotation alone is never a live ownership link.

This is the architectural direction for proposal #83.

### 3.6 Flapping-safe AlertGroup reuse

A resolved child `Alert` remains a terminal technical occurrence and is never changed back to `firing`.

A resolved `AlertGroup` may, however, be reused when a new matching firing occurrence arrives and Event Orchestration explicitly enables a reopen window.

Rules:

- Event Orchestration controls the policy through `set_grouping.reopen_window_seconds`;
- missing or `0` means disabled and preserves current behavior;
- `set_grouping.window_seconds` and `reopen_window_seconds` are separate concepts;
- reopening creates a new child Alert occurrence;
- older resolved child Alerts remain resolved and keep their timestamps;
- after the reopen window expires, a matching firing occurrence creates a new AlertGroup;
- `closed` is not added to the AlertGroup technical state machine;
- `closed` remains a terminal operational state of first-class Incident;
- inactivity or absence of webhook traffic is not recovery by default.

This is the architectural direction for proposal #84 and workstream #85.

### AlertGroup and Incident responsibility boundary

The target model intentionally keeps both objects useful:

```text
Alert -> AlertGroup        technical signal episode
             -> Incident   optional operational investigation
```

`AlertGroup` remains responsible for technical signal processing:

- child Alert occurrences, grouping and deduplication;
- technical lifecycle and source state;
- routing, notification and escalation;
- technical assignee and manual AlertGroup reassignment;
- technical priority/context, Silence, maintenance and shelving;
- impact, correlation and source context;
- technical timeline;
- **technical comments**.

`Incident` owns operational response:

- independent operational workflow;
- operational assignee and manual Incident reassignment;
- Incident Commander and responders;
- stakeholders;
- affected-service context;
- **operational comments**;
- root cause and resolution summary;
- external ITSM references;
- postmortem and corrective actions.

Assignment rules:

```text
AlertGroup.assignee = current technical responsibility / paging target
Incident.assignee   = owner of the operational investigation
```

Both assignments may be changed manually, but they are independent. Changing
one must not silently mutate the other. AlertGroup reassignment does not imply
ACK and does not reset escalation policy, escalation level, rotation or the
next scheduled escalation.

Proposal #83 is interpreted primarily as manual reassignment of the current
AlertGroup assignee because the current product exposes AlertGroups as
"incidents". First-class Incident reassignment remains a separate required
Incident Core capability.

Comment rules:

- AlertGroup comments remain supported as technical investigation notes;
- Incident comments are operational collaboration;
- a combined Incident activity view may surface comments from linked
  AlertGroups, but must identify the original target/source;
- comments are not automatically copied between AlertGroup and Incident;
- original author, timestamp and target remain canonical.

Responder/stakeholder rules:

- responders and stakeholders become canonical Incident collaboration data;
- service default stakeholders are copied as Incident snapshots;
- legacy AlertGroup responder/stakeholder records are preserved during staged
  migration;
- final removal of legacy operational AlertGroup storage belongs to 2.9;
- AlertGroup technical comments are explicitly not removed by that cleanup.

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
15. Flapping-safe AlertGroup reuse with Event Orchestration controlled resolved-group reopen semantics, disabled by default.

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
- automatic resolution or closure of firing alerts solely because no new webhook/update has been received;

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

Responders, stakeholders and operational timeline belong to the Incident. Incident comments are operational collaboration; AlertGroup technical comments remain on AlertGroup. Notification and escalation state remain on `AlertGroup`.

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

### 8.1 Alert and AlertGroup lifecycle

Child Alert technical states remain:

```text
firing
acknowledged
silenced
maintenance
resolved
```

A resolved child Alert is a terminal occurrence.

AlertGroup uses the same technical state model, but resolved is not
necessarily the end of the group identity.

firing / acknowledged / silenced
              |
              v
           resolved
              |
              +---- new matching occurrence inside reopen grace ----+
              |                                                     |
              +------------------------------------------------> firing

A reopened AlertGroup receives a new child Alert. Existing resolved child
Alerts remain unchanged.

Once the configured reopen grace period has elapsed, the resolved AlertGroup
is no longer eligible for automatic reuse and a new matching occurrence
creates a new AlertGroup.

This behavior reduces AlertGroup/Incident churn caused by flapping while
preserving individual occurrence history and lifecycle metrics.

There is intentionally no closed AlertGroup state. closed belongs to the
Incident workflow.

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
- a new firing occurrence may reopen a recently resolved AlertGroup within the configured reopen grace period;
- reopening an AlertGroup creates a new child Alert and never mutates an older resolved Alert back to firing;
- an AlertGroup reopened after resolution causes a linked `resolved` or`monitoring` Incident to return to `investigating`;
- expiration of the AlertGroup reopen grace period does not automatically
  close a linked Incident;
- Incident `closed` remains an explicit operational transition;
- inactivity alone never implies technical recovery unless an explicit stale-alert policy is configured.

### 8.4 Flapping and recovery policy

IncidentRelay must distinguish three separate concepts:

1. **Technical occurrence resolution**
   - one child Alert reached `resolved`;
   - the occurrence remains immutable afterwards.

2. **AlertGroup reopen eligibility**
   - a resolved AlertGroup may accept a new matching occurrence for a limited configurable period;
   - this prevents flapping sources from producing excessive AlertGroups.

3. **Incident closure**
   - an operational Incident may move from `resolved` to `closed`;
   - `closed` is not inferred from AlertGroup inactivity;
   - automatic Incident closure, if introduced later, must be an explicit configurable policy.

A future notification-recovery grace period may suppress short
`resolved -> firing` notification pairs without changing the persisted Alert
or AlertGroup history.

A future stale-alert policy may act on a firing signal that has not been
updated for a configured duration. Such behavior must be opt-in because
absence of webhook traffic does not generally prove recovery.

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

### IncidentRelay 2.3: Incident Core and ownership

- first-class `Incident` and `IncidentAlertGroupLink`;
- manual Incident creation, Create Incident from AlertGroup, basic link/unlink;
- independent Incident lifecycle, team/service/priority;
- manual Incident assign/reassign/unassign and **Assign to me**;
- manual AlertGroup assign/reassign and **Assign to me** for #83;
- AlertGroup reassignment does not ACK or reset escalation state;
- breaking `/api/alert-groups` vs `/api/incidents` split;
- separate Alerts/Incidents navigation and minimal Incident workspace;
- preserve AlertGroup technical comments;
- RBAC, audit, timeline, migrations, concurrency, OpenAPI and docs.

### IncidentRelay 2.4: Lifecycle resilience and flapping

- #84/#85 `set_grouping.reopen_window_seconds` controlled by Event Orchestration;
- disabled by default;
- reopen creates a new child Alert; older resolved child Alerts remain terminal;
- resolve/reopen and duplicate-delivery concurrency protection;
- linked resolved/monitoring Incident may return to `investigating`;
- recovery notification hysteresis / delayed resolved notification;
- cancel pending recovery notification on quick reopen;
- Explain, audit, timeline and UI context.

### IncidentRelay 2.5: Incident collaboration

- Incident Commander and responders;
- Incident stakeholders and service-default stakeholder snapshots;
- Incident operational comments and richer activity;
- root cause and resolution summary;
- affected services and runbook/dashboard/dependency/impact context;
- preserve AlertGroup technical comments as a separate target;
- combined Incident activity may show linked AlertGroup comments with explicit
  source attribution;
- staged migration of legacy AlertGroup responder/stakeholder data when an
  unambiguous Incident mapping exists;
- never backfill an Incident solely to move legacy collaboration data.

### IncidentRelay 2.6: Classification, relations and merge/split

- AlertGroup classification and review policy;
- review-required queue;
- duplicate canonical AlertGroup/Incident targets;
- `primary`, `related`, `symptom`, `duplicate` relations;
- Incident merge and split;
- technical AlertGroup merge/link reconciliation;
- RBAC, audit, history and concurrency coverage.

### IncidentRelay 2.7: On-call Roles and Incident automation

- #59 On-call Roles and concurrent role-aware coverage;
- role-aware Incident assignee/commander/responder suggestions;
- persist concrete users rather than live schedule ownership links;
- #51 Event Orchestration Incident declaration/linking/assignment actions;
- draft-and-confirm, similar-open-Incident checks and idempotency;
- asynchronous duration/escalation hooks;
- optional stale-signal policy, disabled by default;
- inactivity alone never means technical recovery.

### IncidentRelay 2.8: ITSM and Jira

- #52 `IncidentExternalReference` and provider-neutral ITSM framework;
- manual external references, protected connector configuration;
- outbox, retries, idempotency and dead-letter visibility;
- #53 Jira/Jira Service Management create/update;
- authenticated inbound events, source-of-truth/conflict handling;
- sync-loop prevention, secret redaction and SSRF/private-network controls.

### IncidentRelay 2.9: Analytics, Postmortems and final cleanup

- #54 Incident and AlertGroup analytics with exact lifecycle definitions;
- separate Incident reopen and AlertGroup reopen/flapping metrics;
- classification, alert-quality and external-ticket metrics;
- #60 configurable Postmortems / Incident Reviews;
- corrective actions with owner/due date and export/reporting;
- final Incident v2 cleanup;
- remove deprecated AlertGroup responder/stakeholder write flows only after
  reconciliation;
- preserve AlertGroup technical comments and Incident operational comments;
- remove legacy Incident-as-AlertGroup terminology/helpers/adapters;
- remove obsolete compatibility DB structures only through explicit,
  idempotent migrations with reconciliation and documented rollback boundary;
- never create historical Incidents solely to simplify cleanup.

### Cross-release hardening rule

Every release includes the RBAC, audit, timeline, migrations, concurrency,
OpenAPI, localization, tests and documentation required by its own scope.

## 19. IncidentRelay 2.3 release gate

Incident Core is ready to ship in 2.3 when:

- Alert, AlertGroup and Incident boundaries are explicit and tested;
- AlertGroup remains a first-class technical signal episode;
- `/api/alert-groups` exposes AlertGroups and `/api/incidents` exposes only
  first-class Incidents;
- manual AlertGroup creation creates one group and one child Alert atomically;
- manual Incident creation creates only an Incident;
- Incidents can exist with zero or multiple linked AlertGroups;
- linked AlertGroups retain their technical lifecycle;
- authorized operators can manually reassign AlertGroup assignee;
- AlertGroup reassignment does not ACK or reset escalation policy/state;
- authorized operators can assign/reassign/unassign Incident ownership;
- AlertGroup and Incident assignments are independent;
- AlertGroup technical comments remain supported;
- minimal Incident UI, RBAC, audit, migration, concurrency and OpenAPI are
  production-ready;
- 2.4 flapping/reopen behavior is not required to ship 2.3.

Later collaboration, classification, role-aware scheduling, automation, ITSM,
analytics, postmortems and cleanup are not blockers for 2.3.

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

### 2.3 implementation note: Incident Core persistence and concurrency

The 2.3 Incident Core implementation uses a dedicated first-class `Incident`
row and historical `IncidentAlertGroupLink` rows. Operational mutations are
serialized with optimistic concurrency using `Incident.row_version`: clients
must submit the version they read, and stale writes are rejected instead of
silently overwriting a newer Incident state.

The core service centrally validates Incident workflow transitions. Incident
assignment changes only `Incident.assignee`; it does not acknowledge a linked
AlertGroup and does not change AlertGroup rotation, escalation state, or
technical assignee. Basic 2.3 linking supports `primary` and `related`
relations. Unlinking marks a link historical (`removed_at`) rather than deleting
it, so a later re-link creates a new auditable relation row.

Every core mutation writes an `IncidentEvent` operational timeline record and
an `AuditLog` entry. AlertGroup technical comments and technical timeline remain
separate and unchanged.
