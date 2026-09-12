# Jira Integration Architecture Plan

## Goal

Add a first-class Jira integration to IncidentRelay that supports both simple alert-lifecycle driven issue creation and conditional Jira actions inside Event Orchestration.

The integration must be reusable: Jira authentication, API access, issue linking, idempotency, secret handling, and audit behavior should be implemented once and shared by Channels, Orchestration, and future UI actions.

---

## Architectural Principles

1. Jira credentials and connection settings are stored independently from Channels and Orchestration.
2. A single Jira connection can be reused by multiple Channels and orchestration actions.
3. Jira Channels handle alert lifecycle integration.
4. Event Orchestration handles conditional Jira actions.
5. Orchestration evaluation must never perform network I/O directly.
6. Jira calls triggered by orchestration must execute asynchronously through an execution queue.
7. The relationship between an IncidentRelay alert/incident and a Jira issue must be stored explicitly.
8. Repeated execution must not create duplicate Jira issues.
9. Secrets must never be exposed through API responses, audit logs, execution traces, or UI payloads.
10. Jira Cloud and Jira Data Center should use the same abstraction layer where practical.

---

# 1. Jira Connection

Introduce a reusable Jira connection entity.

Example:

```text
JiraConnection

id
uid
group_id

name
provider_type
base_url

auth_type

username_or_email
secret_encrypted

enabled

created_by
created_at
updated_at
deleted
deleted_at
```

Suggested provider types:

```text
jira_cloud
jira_data_center
```

Suggested authentication types:

```text
oauth2
api_token
pat
```

The initial implementation may support only a subset, for example:

```text
Jira Cloud:
email + API token

Jira Data Center:
PAT
```

The model should still be designed so OAuth 2.0 can be added without a schema redesign.

## Connection Responsibilities

The Jira connection layer should provide:

- authentication;
- base URL validation;
- connection testing;
- project discovery;
- issue type discovery;
- field metadata discovery;
- transition discovery;
- secure credential storage;
- secret masking;
- common Jira REST client construction.

The connection itself must not contain alert-specific behavior.

---

# 2. Jira Client Abstraction

Create a common Jira client/service used by every IncidentRelay feature.

Suggested interface:

```python
class JiraClient:
    def test_connection(self):
        ...

    def list_projects(self):
        ...

    def list_issue_types(self, project_key):
        ...

    def get_create_metadata(self, project_key, issue_type):
        ...

    def create_issue(self, payload):
        ...

    def get_issue(self, issue_key):
        ...

    def add_comment(self, issue_key, body):
        ...

    def update_issue(self, issue_key, fields):
        ...

    def list_transitions(self, issue_key):
        ...

    def transition_issue(self, issue_key, transition):
        ...
```

Provider-specific differences should be hidden behind this abstraction.

For example:

```text
app/services/integrations/jira/
    client.py
    auth.py
    cloud.py
    data_center.py
    serializers.py
    errors.py
```

The rest of IncidentRelay should not construct Jira REST URLs directly.

---

# 3. External Issue Link

Introduce an explicit link between IncidentRelay objects and external Jira issues.

Example:

```text
ExternalIssueLink

id
uid

provider
connection_id

alert_group_id
incident_id

external_id
external_key
external_url

status
metadata_json

created_by
created_at
updated_at
```

For Jira:

```text
provider = jira
external_id = Jira internal issue id
external_key = OPS-123
external_url = https://jira.example.com/browse/OPS-123
```

This link becomes the shared source of truth for:

- Jira Channels;
- orchestration actions;
- manual "Create Jira issue" actions;
- inbound Jira webhooks;
- alert/incident details UI;
- timeline enrichment.

A uniqueness constraint or equivalent idempotency rule should prevent duplicate links for the same logical action.

---

# 4. Jira as a Notification Channel

Add Jira as a first-class Channel type.

Conceptually:

```text
Alert lifecycle event
        ↓
Jira Channel
        ↓
Jira issue lifecycle
```

The Jira notifier should be stateful.

Example behavior:

```text
Alert fires
    ↓
Create Jira issue
    ↓
OPS-123
    ↓
Store ExternalIssueLink

Alert acknowledged
    ↓
Add Jira comment or update fields

Alert resolved
    ↓
Add comment and optionally transition Jira issue
```

## Suggested Channel Configuration

```text
Connection:
  Corporate Jira

Project:
  OPS

Issue type:
  Incident

Create on:
  trigger

On acknowledge:
  add comment

On resolve:
  add comment
  transition to Done

Summary template:
  [{{ priority }}] {{ title }}

Description template:
  ...

Labels:
  incidentrelay
  {{ service.slug }}

Priority mapping:
  P1 -> Highest
  P2 -> High
  P3 -> Medium
```

Support custom field mapping:

```text
IncidentRelay service -> customfield_10104
Severity              -> customfield_10500
Alert URL              -> customfield_11001
```

## Notifier Interface

The Jira notifier should use the existing notifier lifecycle:

```python
send(...)
update(...)
```

Expected mapping:

```text
send()   -> create Jira issue
update() -> comment / field update / transition
```

The created Jira issue key should be stored in the delivery and in `ExternalIssueLink`.

---

# 5. Event Orchestration Jira Actions

Add first-class Jira actions to Event Orchestration.

Initial action types:

```text
create_jira_issue
add_jira_comment
update_jira_issue
transition_jira_issue
```

Example rule:

```text
IF
  priority = P1
  AND labels.environment = production

THEN
  create_jira_issue
    connection = Corporate Jira
    project = INCIDENT
    issue_type = Incident
```

Another example:

```text
IF
  labels.customer_impacting = true

THEN
  create_jira_issue
    project = CUSTOPS
    issue_type = Major Incident
```

## Important Execution Rule

Jira network calls must not happen inside the deterministic orchestration action evaluator.

The action evaluator should only record intended side effects.

Example:

```text
create_jira_issue
        ↓
deterministic action evaluation
        ↓
result.jira_actions[]
        ↓
AutomationExecution
        ↓
Jira execution worker
        ↓
Jira REST API
```

This mirrors the existing asynchronous webhook architecture.

The action evaluation layer should remain:

- deterministic;
- simulation-safe;
- side-effect free;
- replay-safe.

## Idempotency

Every Jira orchestration execution must have a stable idempotency key.

A possible key source:

```text
orchestration_execution_uid
+ action definition uid
+ rule path
+ action ordinal
```

The worker must check for an existing successful execution or existing `ExternalIssueLink` before creating a new Jira issue.

Simulation and shadow mode must never create Jira issues.

---

# 6. Manual Jira Action from Alert or Incident UI

Add a manual action to Alert Details and/or Incident Details.

Example:

```text
Actions
 ├─ Acknowledge
 ├─ Resolve
 ├─ Add responder
 └─ Create Jira issue
```

After creation:

```text
Jira

OPS-123
P1 API outage
Open in Jira
```

If the issue already exists, replace:

```text
Create Jira issue
```

with:

```text
Open OPS-123
```

Optionally expose:

```text
Add comment
Sync now
Transition
Unlink
```

according to user permissions.

This supports organizations where only some incidents should become Jira tickets.

---

# 7. Jira to IncidentRelay Webhooks

Add inbound Jira webhook support as a later phase.

Potential events:

```text
issue_created
issue_updated
issue_deleted
comment_created
comment_updated
issue_transitioned
```

Primary goal:

```text
Jira event
    ↓
ExternalIssueLink lookup
    ↓
IncidentRelay timeline event
```

Example:

```text
Jira issue OPS-123 moved from "In Progress" to "Done"
by john@example.com
```

Possible sync options:

```text
Jira -> IncidentRelay sync

Comments              enabled
Status changes         enabled
Assignee changes       optional
Resolve alert on Done  disabled by default
```

Automatic IncidentRelay resolution from Jira must be opt-in.

A Jira issue being closed does not necessarily mean the production incident has recovered.

---

# 8. Timeline and UI Enrichment

Jira activity should appear in the existing alert/incident timeline.

Example events:

```text
jira.issue.created
jira.issue.updated
jira.comment.created
jira.issue.transitioned
jira.issue.linked
jira.issue.unlinked
```

Example timeline entry:

```text
OPS-123 created in Jira by automation
```

or:

```text
OPS-123 transitioned to Done by jane@example.com
```

The alert/incident details view should display external issue links in a dedicated section.

---

# 9. Permissions

Jira configuration should follow IncidentRelay group/team ownership rules.

Recommended model:

```text
JiraConnection -> group-owned
JiraChannel    -> team-owned
```

Permissions:

```text
View Jira connection
    group viewer+

Create/update Jira connection
    group editor / user admin

Use Jira connection in a team channel
    require access to both connection group and target team

Create Jira issue manually
    responder/manager or equivalent write permission

Configure orchestration Jira actions
    same permission as orchestration editing
```

Global admins retain full access.

---

# 10. Security Requirements

Jira integration must reuse existing IncidentRelay security patterns.

Required controls:

- encrypted credentials;
- masked API responses;
- no credentials in URLs;
- no secrets in audit logs;
- no secrets in orchestration traces;
- HTTPS by default;
- SSRF protection;
- private-network allowlist for Jira Data Center;
- DNS pinning where applicable;
- redirect validation;
- bounded response sizes;
- request timeouts;
- retry limits;
- safe error messages.

For on-premise Jira:

```text
jira.internal -> private IP
```

must require an explicit private-network allowlist.

---

# 11. Audit Events

Suggested audit events:

```text
jira.connection.create
jira.connection.update
jira.connection.delete
jira.connection.test

jira.issue.create
jira.issue.update
jira.issue.comment
jira.issue.transition
jira.issue.link
jira.issue.unlink

jira.webhook.received
jira.webhook.rejected
```

Audit payloads should contain safe metadata only.

Example:

```json
{
  "connection_id": 4,
  "project": "OPS",
  "issue_key": "OPS-123",
  "action": "transition"
}
```

Credentials and raw Authorization headers must never be stored.

---

# 12. Failure Handling

Jira failures should not break alert ingestion.

For Channel operations:

```text
alert processing
    ↓
notification delivery
    ↓
jira delivery succeeds/fails independently
```

For Orchestration:

```text
orchestration evaluation
    ↓
Jira action queued
    ↓
background execution
```

Suggested execution states:

```text
pending
running
succeeded
failed
cancelled
```

Retryable conditions may include:

```text
429
5xx
network timeout
temporary DNS failure
```

Non-retryable examples:

```text
400 invalid payload
401 invalid credentials
403 permission denied
404 project/issue not found
```

---

# 13. Jira Metadata Discovery

The UI should not require administrators to manually type every Jira identifier.

When a connection is selected:

```text
Connection
    ↓
Projects
    ↓
Issue types
    ↓
Available fields
    ↓
Transitions
```

This allows the UI to provide selects instead of free-text configuration where possible.

Custom fields should retain both:

```text
field id
field display name
```

Example:

```text
customfield_10104
Service
```

Stored configuration should reference the stable field ID.

---

# 14. Templates

Reuse IncidentRelay's existing safe template engine where possible.

Example summary:

```text
[{{ event.priority }}] {{ event.title }}
```

Example description:

```text
IncidentRelay alert: {{ event.title }}

Severity: {{ event.severity }}
Service: {{ service.name }}
Team: {{ team.name }}

{{ event.message }}
```

Templates must remain deterministic and simulation-safe.

---

# 15. Suggested Implementation Phases

## Phase 1 — Jira Connection and Jira Channel

Deliver:

```text
JiraConnection
JiraClient
JiraNotifier
ExternalIssueLink

create issue
comment on ACK
comment/transition on resolve

templates
priority mapping
custom field mapping

test connection
metadata discovery
test issue creation
```

This phase provides immediate production value without changing Event Orchestration internals significantly.

## Phase 2 — First-Class Jira Orchestration Actions

Add:

```text
create_jira_issue
add_jira_comment
update_jira_issue
transition_jira_issue
```

Reuse:

```text
JiraConnection
JiraClient
ExternalIssueLink
```

Execution must be asynchronous and idempotent.

## Phase 3 — Manual Jira UI Actions

Add:

```text
Create Jira issue
Open Jira issue
Add comment
Transition issue
```

to alert/incident details.

Reuse the same connection and linking infrastructure.

## Phase 4 — Jira Inbound Webhooks

Add:

```text
Jira webhook endpoint
signature/auth validation
ExternalIssueLink lookup
timeline events
optional status synchronization
```

Automatic resolve synchronization remains disabled by default.

---

# 16. Generic Webhook Compatibility

IncidentRelay's existing Event Orchestration webhook actions can already call the Jira REST API.

This may be documented as an advanced workaround, but it should not replace the first-class Jira integration.

Generic webhooks do not provide:

- Jira connection management;
- project discovery;
- issue type discovery;
- custom field discovery;
- transition discovery;
- stable issue linking;
- lifecycle updates;
- Jira-specific UI;
- bidirectional synchronization.

Therefore Jira should remain a dedicated integration.

---

# 17. Proposed Target Architecture

```text
                         ┌──────────────────┐
                         │  JiraConnection  │
                         └────────┬─────────┘
                                  │
                           shared JiraClient
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
              ▼                   ▼                   ▼
       ┌─────────────┐   ┌──────────────────┐  ┌──────────────┐
       │ Jira Channel│   │ Orchestration    │  │ Manual UI    │
       │             │   │ Jira Actions     │  │ Jira Action  │
       └──────┬──────┘   └─────────┬────────┘  └──────┬───────┘
              │                    │                  │
              │                    ▼                  │
              │          ┌──────────────────┐         │
              │          │AutomationExecution│        │
              │          └─────────┬────────┘         │
              │                    │                  │
              └────────────────────┼──────────────────┘
                                   ▼
                          ┌──────────────────┐
                          │   Jira REST API  │
                          └────────┬─────────┘
                                   │
                                   ▼
                          ┌──────────────────┐
                          │ExternalIssueLink │
                          └────────┬─────────┘
                                   │
                        ┌──────────┴──────────┐
                        ▼                     ▼
                Alert / Incident        Timeline / UI
```

Future inbound flow:

```text
Jira Webhook
     ↓
ExternalIssueLink
     ↓
Alert / Incident Timeline
     ↓
Optional lifecycle synchronization
```

---

# 18. Recommended Starting Point

The first implementation should be:

```text
Jira Connection
      +
Jira Channel
      +
ExternalIssueLink
```

This establishes the reusable foundation.

The next implementation should add first-class Jira actions to Event Orchestration using the same connection, client, and link infrastructure.

This avoids building two separate Jira integrations and keeps the architecture extensible for manual actions and bidirectional Jira synchronization later.
