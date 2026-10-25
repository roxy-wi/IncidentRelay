# IncidentRelay — Change Intelligence

**Architecture RFC v1.0 (implementation proposal)**  
**Source baseline:** `release/2.3.1` (verified 2026-10-11)  
**Status:** proposed architecture; implementation has not started  

## 1. Purpose and scope

Change Intelligence is an independent subsystem that ingests normalized infrastructure and application change events, records operation history, exposes an **Operations → Changes** inbox, and identifies explainable potential relationships to technical AlertGroups and operational Incidents.

GitLab, Jenkins, Terraform, Kubernetes, Ansible, CMDB systems, and custom scripts all submit **the same standardized JSON** to one HTTP endpoint. The core does not require product-specific adapters: the sender or an optional external adapter converts a vendor payload into the common contract.

A CI/CD pipeline may **not know any internal IncidentRelay IDs**. It can use stable Team and Service slugs instead; the backend resolves them to the canonical numeric IDs of the running installation. Services and dependencies can be provisioned independently by a CMDB.

**Out of scope for v1:** ITIL Change Requests, approval workflows, automatic rollback, automatically creating AlertGroups/Incidents from changes, AI Root Cause Analysis, implementing a CMDB synchronization service, and mandatory Plugin Platform support. A Change is neither an AlertGroup nor an Incident. A successful deployment may still contribute to an outage; change status and causal relevance are independent dimensions.

## 2. Architectural invariants

1. Every Change has one **responsible Team** (`owner_team_id` in storage). Directly changed and affected services may belong to **any Teams**, including Teams in other Groups.
2. The public API identifies the responsible Team with **exactly one** of `owner_team_id` or `owner_team_slug`. A slug resolves to an existing Team before authorization.
3. A technical Service reference uses **either `service_id` or `service_slug`**. A slug is resolved within a Team namespace identified by `team_id` or `team_slug`. If no namespace is given, **owner Team** is used; there is no global Service slug search.
4. In the current schema, `Team.slug` is globally unique, while `Service.slug` is only unique within a Team (`UNIQUE(team, slug)`). Therefore an unqualified Service slug is valid **only as shorthand for a service owned by the Change's owner Team**.
5. Once a reference has been resolved, canonical relationships, correlation, and Service Timeline use the **numeric `service_id`**. The submitted slug reference is retained for history and diagnostics; renaming or reusing a slug must not silently rebind a historical Change to a different service.
6. An unknown Service slug in an **existing Team** may be stored as `pending_resolution` until CMDB synchronization. Until resolution and authorization, that reference must not drive correlation or cross-team publication. Unknown numeric Service IDs are not deferred.
7. `group_id` is not part of the public payload and is not required on Change. Existing Group RBAC remains enforced internally through Team and Service ownership.
8. One operation has one `Change` and many immutable `ChangeEvent` records. Identical retries are idempotent, and events may arrive out of order.
9. Keep `changed` (directly modified), `reported_affected` (sender-reported), and `inferred_affected` (dependency-derived) separate. An inference is not proof of actual impact.
10. A sender must not access another Team's resources or manufacture trusted impact by supplying arbitrary foreign IDs or slugs.
11. Correlation is asynchronous; failures must not roll back accepted ChangeEvents. Automatic recomputation never erases a human confirmation or rejection.
12. Change Events do not modify Service/AlertGroup/Incident statuses, send pages, change escalations, create Incidents, or initiate rollbacks.
13. Reuse existing `ServiceEvent`, `ServiceDependency`, `Incident`, `AlertGroup`, token, and RBAC infrastructure without breaking its public contracts.

## 3. Component architecture

```text
GitLab / Jenkins / Terraform / Kubernetes / Ansible / Custom
                         |
                         v
             POST /api/change-events
      Auth -> scopes -> source/team grants -> Pydantic
                         |
                         v
              Service Identity Resolver
       service_id OR (team namespace + service_slug)
                         |
                         v
                atomic DB transaction
        Change + ChangeEvent + ChangeServiceReference
           + ChangeService (if already resolved)
           + durable outbox/job record
                         |
                    HTTP 201/200
                         |
                         v
                   Scheduler worker
                /                   \
               v                     v
    Pending reference resolver    Impact / correlation
           |                        |
           |                        v
           |            ChangeImpact / ChangeAlertGroupCorrelation
           |                        |
           +-------> resolved ------+
           ^                        |
           |                        v
    CMDB creates/updates      Changes Inbox / Timeline /
      Service/Dependency      AlertGroup / Incident UI
```

HTTP `201` means **the event has been durably stored**, not that every slug has already resolved or correlation has finished. Pending-reference resolution and correlation run as durable, retryable background work.

## 4. Data model

### 4.1. `Change` — canonical operation

- `id`, `uid` (UUID);
- `owner_team_id` (Team FK, resolved from request `owner_team_id` or `owner_team_slug`, immutable for ordinary events);
- `source` (logical sender namespace, e.g. `terraform-prod`);
- `external_change_id` (public API `change_id`);
- `kind` (`deployment`, `configuration`, `infrastructure`, `database`, `feature_flag`, `other`);
- `title`, `description`, `environment`, `external_url` (length-limited);
- `status` (`unknown`, `running`, `succeeded`, `failed`, `rolled_back`, `cancelled`);
- `mapping_status` (`mapped`, `partially_mapped`, `unmapped`, `mapping_failed`);
- `started_at`, `completed_at`, `first_occurred_at`, `last_occurred_at`, `created_at`, `updated_at`;
- `revision`, a monotonically increasing aggregate revision for concurrency control and background jobs.

**Unique key:** `(owner_team_id, source, external_change_id)`.

`Change` is a projection of immutable events, not the source of immutable truth. Successful execution does not imply absence of harmful impact.

### 4.2. `ChangeEvent` — immutable history

- `id`, `uid`, `change_id` (FK to Change);
- `external_event_id` (API `event_id`), `event_type`;
- `occurred_at` (at the sender), `received_at` (in IncidentRelay), optional `source_sequence`;
- `actor_type`, `actor_label`, `external_url`, size-limited `details`;
- a normalized snapshot of the **submitted service references** and a bounded original request representation for diagnostics;
- `request_digest`, `ingest_token_id` or a safe principal identifier for auditing;
- `schema_version`.

**Unique key:** `(owner_team_id, source, external_event_id)`, via materialized columns or an equivalent unique constraint. An exact retry returns the existing event; a reused event ID with different content yields `409 Conflict`.

Canonical event types: `change.started`, `change.updated`, `change.succeeded`, `change.failed`, `change.rolled_back`, `change.cancelled`. Operation `kind` is stored separately; vendor-specific metadata belongs in `details`.

### 4.3. `ChangeServiceReference` — submitted identities and deferred resolution

Keeps every distinct incoming Service reference, including references for which the Service has not yet been provisioned by the CMDB.

- `change_id`, `first_event_id`, `relation_type` (`changed` / `reported_affected`);
- `ref_type` (`id` / `slug`), `requested_service_id`, `requested_service_slug`;
- `requested_team_id`, `requested_team_slug` or the inferred `owner_team_id`;
- `normalized_ref_key`, e.g. `id:12` or `slug:infrastructure/postgresql-prod`;
- `resolved_service_id` (nullable FK), `resolution_status` (`resolved`, `pending_resolution`, `denied`, `invalid`);
- `verification_state` (`trusted`, `unverified`, `rejected`), `resolved_at`, `last_attempt_at`, `last_error_code`.

**Unique key:** `(change_id, relation_type, normalized_ref_key)`. Deduplicate repeated references across events. Different ID/slug references that resolve to the same Service are also deduplicated in the canonical `ChangeService` relation.

Original slugs and Team namespaces are retained after resolution. A pending reference does not claim an imaginary Service and cannot create an inferred impact. Reference resolution must never auto-create a Team, Service, or ServiceDependency.

### 4.4. `ChangeService` — canonical relationship

- `change_id`, `service_id` (FK to a technical Service);
- `relation_type`: `changed` or `reported_affected`;
- `first_reference_id`, `verification_state`, `created_at`;
- optional original identity snapshot to troubleshoot slug renames.

**Unique key:** `(change_id, service_id, relation_type)`. Service ownership does not need to match Change ownership. Impact and correlation consume this table, **not unverified text from the incoming payload**.

### 4.5. `ChangeImpact` — derived projection

Potential indirect impact: `change_id`, `service_id`, `origin_service_id`, `dependency_path_snapshot`, `depth`, `reason`, `computed_at`, `engine_version`, `active`. Derived by **reverse traversal** of `ServiceDependency` starting at directly changed services. Never combine this inference with sender-reported facts. Recomputations retain the graph version/time and evidence needed to explain a relationship.

### 4.6. `ChangeAlertGroupCorrelation`

- `change_id`, `alert_group_id`, identity of the firing/reopen episode;
- `score` (relevance, **not** root-cause probability);
- `reason`, bounded structured `evidence`, `engine_version`, `computed_at`;
- `review_status`: `suggested`, `confirmed`, `rejected`;
- `relation_type`: `potential_cause`, `cause`, `mitigation`, `context`;
- `reviewed_by`, `reviewed_at`, `updated_at`.

The unique identity includes a Change, AlertGroup, and firing episode. Recalculation cannot overwrite manual decisions or carry them to a later unrelated episode.

### 4.7. `ChangeIncidentLink`

- `change_id`, `incident_id`;
- `relation_type`: `context`, `potential_cause`, `confirmed_cause`, `mitigation`;
- `linked_by`, `linked_at`, `removed_by`, `removed_at`.

An operational Incident can be linked without any AlertGroups. Manual link changes are audited.

### 4.8. `ChangeJob` — durable outbox / work queue

- `job_type`, `entity_id`, `target_revision`, `state`, `attempts`, `next_attempt_at`;
- `lease_owner`, `lease_expires_at`, `last_error_class`, `created_at`.

Persist the event, references, and outbox **in one transaction**. Use atomic claims, leases, retries, logical job uniqueness, and protection against obsolete revisions. Suggested job types: `resolve_references`, `refresh_impacts`, `refresh_correlations`, `sync_service_timeline`.

## 5. Universal API contract

```http
POST /api/change-events
Authorization: Bearer <changes:ingest token>
Content-Type: application/json
```

### 5.1. Recommended payload — slugs only, no IncidentRelay internal IDs

```json
{
  "schema_version": 1,
  "event_id": "postgres-config-1842-applied",
  "change_id": "postgres-config-1842",
  "source": "terraform-production",
  "owner_team_slug": "infrastructure",
  "kind": "configuration",
  "event_type": "change.succeeded",
  "occurred_at": "2026-10-10T14:00:00Z",
  "title": "PostgreSQL connection settings updated",
  "environment": "production",
  "changed_services": [
    {"service_slug": "postgresql-prod"}
  ],
  "affected_services": [
    {"team_slug": "devops", "service_slug": "payments-api"},
    {"team_slug": "payments", "service_slug": "checkout-api"}
  ],
  "actor": {"type": "automation", "name": "terraform-ci"},
  "external_url": "https://ci.example/jobs/1842",
  "details": {"parameter": "max_connections", "commit": "abc123"}
}
```

The unqualified `changed_services[0].service_slug` resolves **only within `owner_team_slug=infrastructure`**. Cross-team affected services have an explicit `team_slug`. The pipeline needs no numeric IncidentRelay IDs.

### 5.2. Alternative — numeric IDs and mixed references

```json
{
  "schema_version": 1,
  "event_id": "postgres-config-1843-applied",
  "change_id": "postgres-config-1843",
  "source": "terraform-production",
  "owner_team_id": 2,
  "kind": "configuration",
  "event_type": "change.succeeded",
  "occurred_at": "2026-10-10T15:00:00Z",
  "title": "PostgreSQL settings updated",
  "changed_services": [
    {"service_id": 12}
  ],
  "affected_services": [
    {"service_id": 34},
    {"team_id": 9, "service_slug": "checkout-api"}
  ]
}
```

`changed_services` and `affected_services` are the preferred lists of typed Service references. For simple numeric-ID clients, `changed_service_ids: [12]` and `affected_service_ids: [34,56]` are accepted as shortcuts. A shortcut and the structured field for the **same relation type** must not appear together in one request (`422`).

### 5.3. Identity resolution rules

| Input | Resolution |
|---|---|
| `owner_team_id` | Team by numeric ID |
| `owner_team_slug` | Team by globally unique `Team.slug` |
| `{ "service_id": 12 }` | Service by ID; an optional Team namespace must match the Service's actual owner |
| `{ "service_slug": "postgresql-prod" }` | Service by `(owner_team_id, Service.slug)` |
| `{ "team_slug": "devops", "service_slug": "payments-api" }` | First Team by slug; then Service by `(team_id, slug)` |
| `{ "team_id": 9, "service_slug": "checkout-api" }` | Service by `(9, "checkout-api")` |

- Each request provides **exactly one** of `owner_team_id` / `owner_team_slug`. A Service reference provides exactly one of `service_id` / `service_slug`. A Team namespace provides at most one of `team_id` / `team_slug`.
- Service slugs are validated according to the existing Service API (`lowercase letters`, digits, hyphens); Team slugs follow the current Team model. **No global, unscoped Service slug lookup.**
- If an ID exists but the asserted Team namespace does not match its owner, reject the request. Soft-deleted or inaccessible services remain subject to the same authorization rules in either reference format.
- `owner_team_*` must resolve during ingestion: without a known owner, token and ownership checks cannot be completed. Unknown owner Teams are rejected and never created automatically.
- An unknown numeric `service_id` is an invalid reference. An unknown `service_slug` **within a known Team** may be saved as `pending_resolution` if namespace authorization passes. An unknown `team_slug` in a Service reference is an error, not permission to guess a Team by globally searching services.
- A `changed` reference requires appropriate change-claim permissions; a cross-team `reported_affected` remains unverified until supported by the dependency graph or explicit grants. Accepting a pending reference grants **no new authority** over the named Service.
- After resolution, persist `service_id` for `ChangeService`, `ChangeImpact`, and correlation. Keep the submitted slug on `ChangeServiceReference`.
- Deleting, moving, or renaming a Service must not rebind an already-resolved Change to a new Service that later reuses the slug. The CMDB must manage slug stability; renames need explicit source changes or alias mapping, not silent history changes.
- Reuse an `event_id` **only with the same normalized request content**. Sending an ID representation and a slug representation under the same `event_id` may result in `409`, even if they resolve to the same Service. Use a new event ID for new information.

A `201` response includes safe `resolved_refs`, `pending_refs`, and `correlation_status=queued` counts. It does not reveal foreign-Service metadata. `200` means exact retry; `400/422` invalid schema/identity; `401` unauthenticated; `403` forbidden scope; `409` external-identity conflict; `429` rate limit.

### 5.4. Read and review API

```text
GET    /api/changes
GET    /api/changes/{id}
GET    /api/changes/{id}/events
GET    /api/changes/{id}/services
GET    /api/changes/{id}/correlations
POST   /api/changes/{id}/correlations/{correlation_id}/review
GET    /api/services/{service_id}/changes
GET    /api/alert-groups/{alert_group_id}/related-changes
GET    /api/incidents/{incident_id}/changes
POST   /api/incidents/{incident_id}/changes
DELETE /api/incidents/{incident_id}/changes/{link_id}
```

The Changes listing accepts a `service_id` filter **or** a `service_slug` filter with Team namespace, using the same resolver. Every endpoint applies RBAC; authorization predicates are added to SQL **before** pagination.

## 6. CMDB integration and late Service resolution

The CMDB is responsible for creating/updating `Team`, `Service`, and `ServiceDependency` via its own synchronization process. Change Intelligence **does not** create services or dependencies and **does not** require a product-specific CMDB protocol. CMDB synchronization may run before or after Change ingestion.

### 6.1. Service already exists when the Change arrives

1. CMDB provisions Team `infrastructure`, Service `postgresql-prod`, and dependency `payments-api → postgresql-prod`.
2. Terraform submits `owner_team_slug=infrastructure` and `changed_services=[{"service_slug":"postgresql-prod"}]`.
3. The resolver finds the canonical `service_id` using Team + Service slug. Change retains that ID along with its originally supplied slug.
4. The correlation engine traverses the dependency graph and may suggest a relationship to an AlertGroup on `payments-api`, regardless of Team ownership.

### 6.2. ChangeEvent arrives before the Service exists

1. The owner Team and target Team namespace exist, but the referenced `Service.slug` is not yet provisioned.
2. Accept the ChangeEvent and record `ChangeServiceReference.status=pending_resolution`. Show **Unmapped/Pending mapping** in the owner Team's Changes Inbox.
3. Do not materialize a `ChangeService`, correlate the reference, or publish it to a foreign Team while unresolved.
4. CMDB provisions the Service. A Service Catalog creation/change hook (where available), or a periodic fallback job, retries resolution using **the same Team + slug**.
5. Recheck **current** scopes/grants. If permitted, persist the canonical `service_id` and enqueue impact/correlation/Service Timeline work, including correlation against AlertGroups created before CMDB synchronization.
6. If grants do not permit the claim, mark it `denied`, do not publish it, and require administrative remediation. Acceptance of an earlier event cannot bypass present RBAC requirements.

Pending references have bounded retention/attempts, diagnostics, and indexed lookup by Team namespace + slug. Do not repeatedly scan all historical events to find unresolved names.

### 6.3. Dependency graph changes

On adding/removing/changing `ServiceDependency`, canonical Changes remain immutable while **derived** `ChangeImpact` and correlations may be recomputed over a bounded historical window. Evidence records which graph version/time produced an inference.

**Slug stability rule:** pipelines should use CMDB-managed, stable slugs and avoid reusing one slug for a different entity. Organizations with frequent renames can later introduce an explicit `external_service_ref` or use the existing `Service.uid`; neither is required for v1.0.

## 7. Authentication, tokens, and RBAC

**Generate tokens through existing `Profile → API Tokens → Generate Token`** (`POST /api/profile/tokens`). Reuse secure random generation, hash-only persistence, expiry, and revocation. Route intake tokens are not used.

New scopes:

- `changes:ingest` — only `POST /api/change-events`;
- `changes:read` — list and details access;
- `changes:write` — manual correlation reviews and Incident links.

`changes:ingest` is **not implicitly granted** by legacy `resources:write`; integrations must receive it explicitly. Administrator wildcard `*` follows current semantics but does not remove the need for enforced Team/source grants where applicable. Add explicit path-scope mappings in `app/services/api_token_scopes.py`; unmapped API-token routes otherwise fail closed.

`ApiToken` already has a Team FK, but the current Profile UI and creation endpoint do not populate it. Add a Team selector and enforce token Team restriction on Change ingestion. The sender may choose `owner_team_id` **or** `owner_team_slug`; both must resolve to the Team authorized for that token. Centralized CI systems need **explicitly administered** source/Team/Service grants rather than rights declared in their own JSON.

**Cross-team policy:**

1. Resolve and authorize owner Team **before** creating a Change. Never treat self-declared `source`, Team IDs, or slugs as authentication.
2. A `changed` reference requires permission to claim a change on that Service or an explicit administrative grant. A slug-only reference is checked against the target Team namespace and rechecked upon deferred resolution.
3. A cross-team `reported_affected` reference remains **unverified** until the server confirms a legitimate dependency path or an explicit sender grant. It does not appear in the foreign Team's Inbox solely because a sender claimed it. Error responses must not serve as a Service-existence oracle.
4. `inferred_affected` comes from the server-controlled dependency graph; users see only results in their authorized scope.
5. Change owners receive full data only where authorized. A different affected Team receives a **redacted projection**: its own accessible Service, safe time and relation type. Without owner-data permission, no raw details, foreign infrastructure names, actor identities, or external URLs.
6. Reviewing a Change↔AlertGroup correlation requires appropriate permissions on that AlertGroup, not blanket permission to edit the source Change.
7. Groups remain internal IncidentRelay RBAC boundaries. No public `group_id` is introduced.

**Token revocation and permission changes:** revoke access for new requests immediately. Deferred mappings must re-check current authorization and must not gain trusted status based on stale permissions.

## 8. Lifecycle and out-of-order delivery

- `event_id` ensures idempotency; `change_id` groups lifecycle stages.
- The current Change status is deterministically projected using trustworthy `source_sequence`, `occurred_at`, and stable tie-breakers. `received_at` records ingestion time, not when the change happened.
- A late `change.started` after `change.succeeded` must not return the operation to `running`. A later effective `change.rolled_back` may supersede `succeeded`.
- Service references can be added across stages. Omitting a Service list on a later event **does not mean** that previous references should be removed. Do not delete relationships automatically when an incoming payload is empty.
- A slug reference can remain pending regardless of the Change's lifecycle status. `mapping_status` is separate from `Change.status`.
- Inconsistent transitions, implausible sender clock skew, and source-sequence conflicts are diagnosed, not silently rewritten.
- Correlation considers the start of the specific firing/reopen episode, rather than forever using the historical AlertGroup `first_seen_at`.

## 9. Change Intelligence / Correlation

1. Inputs are successfully resolved, authorized `changed`, and trusted `reported_affected` services (**numeric IDs**, even when sent as slugs).
2. Traverse `ServiceDependency` in reverse: `payments-api depends_on postgresql-prod` implies a PostgreSQL change **may affect** `payments-api`.
3. Store `ChangeImpact` with path, depth, environment, graph version, and explanation. Bound traversal depth, candidates, and execution time.
4. Find AlertGroup episodes within a configurable time window after the change (initial proposal: two hours). A change that occurred **after** an alert may represent `mitigation`, not an earlier cause.
5. Produce a deterministic relevance score using timing, Service match, environment, dependency path/direction, and evidence quality.
6. Store `ChangeAlertGroupCorrelation` with human-readable reasons. Never overwrite confirmed/rejected relationships.
7. Trigger recomputation for new ChangeEvents, new/reopened AlertGroups, late slug resolution following CMDB synchronization, and relevant dependency updates.

**Prohibited automatic consequences:** interpreting score as root-cause probability, rolling back deployments, changing Incident state, or invoking paging/escalation merely because of temporal proximity.

## 10. UI

**Operations → Changes** is a separate Inbox, with one row per Change.

- Search by ID, title, source, external ID, accessible services, and `service_slug`.
- Filters: Team (owner **or** accessible affected), Service (ID or slug + Team namespace), kind, status, source, environment, date range, correlation, `unmapped/pending`.
- A Change spanning multiple Teams still appears once; SQL-side authorization, distinct selection, counts, and pagination must be correct.
- Change Details displays lifecycle history; **Changed**, **Reported affected**, **Inferred impact**; slug resolution state; AlertGroups/Incidents; evidence; external links; and safe JSON data.
- For `pending_resolution`, show the original slug/Team namespace, pending reason, and last attempt in the authorized owner context. Do **not** automatically create Services from the UI.
- AlertGroup Details shows Related Changes with score/reasons/review. Incident Details shows Change context and roles (`potential_cause` / `mitigation`).
- Service Timeline reuses existing `ServiceEvent` (`category=change`, stable `dedup_key`, canonical ChangeEvent link), **only after `service_id` is resolved**. Never label inferred impact as a direct Service modification.
- Cross-team redacted views show the user's own Service, safe change type/time/relation, without revealing private topology, raw payload, actor, or URL.

## 11. Operational and technical requirements

- Pydantic v2 validates alternative ID/slug shapes, field mutual exclusivity, slug/string lengths, reference counts, HTTP body, and `details` size. Never globally search `Service.slug`.
- `POST /api/change-events` **always requires a token**, even if global API auth is optionally disabled in configuration.
- DB-enforced uniqueness; atomically persist ChangeEvent, references, and outbox. Use atomic upserts/row locks in PostgreSQL and short transactions plus lock retries in SQLite.
- Durable scheduler jobs with atomic claim/lease, exponential retries, and diagnostic dead letters. No Redis/Celery requirement and no in-memory-only Flask work queue.
- Indexes: `Change(owner_team_id,last_occurred_at)`, external unique identities, `ChangeService(service_id,change_id)`, `ChangeServiceReference(resolution_status,requested_team_id,requested_service_slug)`, `ChangeImpact(service_id,active)`, `ChangeAlertGroupCorrelation(alert_group_id,review_status)`, `ChangeJob(state,next_attempt_at)`.
- On Team/Service slug renames, previously resolved links retain their Service IDs. Pending references resolve only against valid current identity and permission; reusing a slug must not cause uncontrolled rebinding.
- SQL RBAC predicates must be applied **before LIMIT/OFFSET/cursor** for listings, counts, related correlations, and Explain output.
- Avoid high-cardinality `change_id`, `event_id`, `service_id`, raw slug, or uncontrolled `source` Prometheus labels. Measure accepted/duplicate/rejected ingest, unresolved references, resolution latency, queue depth, correlation duration/errors.
- Never log secrets or unrestricted `details`. Validate external URL schemes, escape user content, enforce timeouts/rate limits, and apply retention without destroying evidence linked to Incidents.
- Provide EN/RU/DE/FR/ES/ZH UI localization, OpenAPI, and positive/security tests on PostgreSQL and SQLite. Do not convert historical `ServiceEvent(category=change)` rows without a reliable external Change ID mapping.

## 12. Delivery plan

**Phase 1 — Change Registry:** schema/migrations; `owner_team_id`/`owner_team_slug`; ID/slug Service resolver and pending references; scopes and Team/source grants; universal POST; deduplication; read API; Changes Inbox/Details; security/idempotency tests. It is useful as a change history even before correlation is enabled.

**Phase 2 — Change Intelligence:** dependency traversal, redacted cross-team impact, correlation and explanation, late events and CMDB reconciliation, human review, metrics, and durable background jobs.

**Phase 3 — UI integrations:** Service Timeline, AlertGroup Related Changes, Incident links, complete documentation for generic CI/CD senders and CMDB-sync troubleshooting, end-to-end and regression testing. Product-specific plugins remain optional.

## 13. Acceptance criteria

1. An event using only `owner_team_slug` and `service_slug` is saved and attached to the correct Service **without knowing internal IDs**.
2. The same `service_slug` in two Teams resolves only through explicit `team_slug`/`team_id` or the owner Team fallback; no accidental cross-team binding.
3. A single Change can mix `service_id` and `(team_slug,service_slug)` in different references without duplicate canonical `ChangeService` records.
4. Infrastructure Team changes `postgresql-prod`; DevOps sees only a safe related card for dependent `payments-api`, with no Infrastructure-only payload disclosure.
5. An unknown Service slug in an existing Team stays pending, then resolves after CMDB provisioning, and re-evaluates impact against already-existing AlertGroups.
6. Unknown Team namespaces, nonexistent numeric Service IDs, and conflicting Service ID/Team claims produce safe errors without disclosing unauthorized resources.
7. An identical `event_id` retry yields `200`, a conflicting retry yields `409`, and concurrent submissions do not create duplicates.
8. Three lifecycle ChangeEvents produce **one** Change Inbox row with the correct outcome, even when delivery order differs.
9. A foreign `reported_affected` slug never becomes trusted or visible to that Team on sender assertion alone.
10. Renaming a slug cannot redirect a previously resolved Change from its original `service_id` to a new entity reusing that slug.
11. Correlation works for Change → AlertGroup, AlertGroup → late Change, delayed CMDB synchronization, and subsequent firing episodes.
12. Human confirmations/rejections survive recomputation and dependency-graph updates.
13. Restarting a worker does not lose queued work or create duplicates; ingestion succeeds independently of correlation.
14. A token with only `changes:ingest` cannot read Changes or edit Incidents; token revocation and scope changes immediately constrain new requests and deferred mappings.
15. No leakage through Inbox, filters, pagination, Change Details, Service Timeline, Explain, or external URLs.
16. All migrations, scope grants, ID/slug resolution, concurrent processing, and background workers are tested with PostgreSQL and SQLite.

## 14. Compatibility with the current IncidentRelay codebase

The `release/2.3.1` schema already has `Team.slug` (**globally unique**), `Service.slug` (**unique per Team** via `(team,slug)` index), `Service.uid`, `ServiceEvent(category=change)` with `dedup_key`, `ServiceDependency`, `AlertGroupCorrelation` (**AlertGroup ↔ AlertGroup**, not Change ↔ AlertGroup), `Incident`, `IncidentAlertGroupLink`, `ApiToken.team`, `Profile → API Tokens`, `api_token_scopes.py`, `app/services/db_lock.py`, and a separate scheduler.

The current Profile token creation endpoint does not yet populate `ApiToken.team`; Change ingestion must extend this safely. The existing Service API uses numeric `team_id` and `slug` for creation, making `(team_id,slug)` resolution compatible with current DB constraints and requiring no change to Service slug uniqueness.

Proposed new files: `app/services/change_intelligence/` (including `identity.py` and `reconciliation.py`), `app/modules/db/changes_repo.py`, `app/api/schemas/changes.py`, `app/views/changes_view.py`, `app/api/openapi/endpoints/changes.py`, `app/templates/pages/changes.html`, `app/static/js/pages/changes.js`, `app/static/css/changes.css`, plus migrations, translations, tests, and docs.

**Conclusion:** the universal Change Events API accepts either internal IDs **or** CMDB-managed human-readable slugs, while IncidentRelay internally works with authorized canonical Service IDs. Independent CMDB synchronization can provision Services and Dependencies, and Change Intelligence safely resolves delayed references, supports cross-team impact, and preserves explainable investigation history.
