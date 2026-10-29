# IncidentRelay — Change Intelligence

**Architecture RFC v1.1 (implementation contract)**

**Source baseline:** `release/2.5.0` (verified 2026-10-28)

**Status:** stage 1 storage implemented; stages 2–10 planned


## Agreed decisions — 28 October 2026

- Separate AlertGroupEpisode history recorded by the new lifecycle writers, without reconstructing past cycles. Public Change Event intake starts only after the complete intake-to-alert-link flow passes acceptance checks.
- Stable integration identity, registered source/Team/Service grants and rotating machine credentials.
- Token revocation blocks new intake; accepted work uses current integration grants.
- Source selects timestamp or sequence ordering. Timestamp means sender occurred_at, never received_at.
- Latest terminal event in that order wins; different terminal outcomes at equal time are an explicit conflict until a later terminal event.
- Automatic potential-cause suggestions only; mitigation is manual in v1.

Stage 1 storage is implemented in the working tree; see [migration and verification notes](change-intelligence-stage-1.md). Runtime behavior and APIs from stages 2–10 remain planned and are not enabled.

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
14. Correlation and manual review identify an immutable AlertGroupEpisode, not merely a reusable AlertGroup.
15. Pending references pin a numeric namespace_team_id; neither a Team rename nor token rotation can move their ownership.
16. A worker publishes only with its current lease, requested generation and input revisions; manual decisions remain independent of computed fields.

## 3. Component architecture

```text
GitLab / Jenkins / Terraform / Kubernetes / Ansible / Custom
                         |
                         v
             POST /api/change-events
      Auth -> Pydantic -> registered source/team grants
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

- `id`, `uid` (UUID), `integration_id`, `source_id` (FK `ChangeSource`);
- `owner_team_id`, `external_change_id` (API `change_id`); the sender name is `ChangeSource.source`; owner and source identity are immutable;
- `kind`: `deployment`, `configuration`, `infrastructure`, `database`, `feature_flag`, `other`;
- `kind`, `environment` are immutable operation identity; a different operation or execution retry uses a new `change_id`;
- bounded `title`, `description`, `external_url`;
- `status`: `unknown`, `running`, `succeeded`, `failed`, `rolled_back`, `cancelled`;
- `lifecycle_conflict` and bounded diagnostic codes; a conflicting terminal outcome has `status=unknown`;
- `mapping_status`: `mapped`, `partially_mapped`, `unmapped`, `mapping_failed`;
- `ordering_mode` (`timestamp` / `sequence`), copied from the registered source on creation and immutable for this Change;
- `started_at`, `completed_at`, `first_occurred_at`, `last_occurred_at`, `created_at`, `updated_at`;
- `revision`, incremented on a new accepted event or a reference/authorization projection change, not on an exact retry or a read.

**Unique key:** `(source_id, external_change_id)`. A source uniquely binds `(owner_team_id, source)` to one integration (§4.10), preserving the public namespace. No payload may transfer an operation to another owner or integration.

Change is a rebuildable projection. §8 specifies ordering, terminal conflicts and field updates. Successful execution does not imply absence of harmful impact.

### 4.2. `ChangeEvent` — immutable history

- `id`, `uid`, `change_id`, `source_id`, `external_event_id` (API `event_id`), `event_type`;
- `occurred_at` (sender's event time), `received_at` (IR ingestion time), `source_sequence` according to §8;
- bounded `actor_type`, `actor_label`, `details`, plus an explicit snapshot of submitted projection fields, including absent/null distinctions;
- normalized submitted Service references and a bounded, secret-redacted diagnostic request snapshot;
- `request_digest`, `integration_id`, nullable `ingest_token_id` for credential audit, `schema_version`.

**Unique keys:** `(source_id, external_event_id)` and `(change_id, source_sequence)` for non-null sequences. An event ID belongs to exactly one operation. Its reuse for another `change_id` is `409`, even if other fields match. Retention must retain a compact identity/digest tombstone for the documented retry horizon rather than recreate an expired event as new work.

For idempotency, hash the validated submitted content, including `change_id`, but excluding credentials, `received_at` and later resolution results. Use canonical JSON key order, UTC timestamps at microsecond precision, normalized shortcuts and sorted/deduplicated Service-reference sets. ID and slug representations remain distinct. Reject excess time precision rather than silently rounding. Compute the digest before secret redaction; do not persist raw secrets or a second full unredacted payload.

An exact authorized retry returns the original event (`200`) without incrementing revision or creating jobs; a different digest is `409`. Even duplicate requests must pass current owner/source authorization. An obsolete, unresolvable owner slug is not an authentication bypass: it yields an identity error, not a global event-ID search. Historical events remain attached to their canonical IDs; senders needing rename-independent retries should use owner IDs from the outset.

Types: `change.started`, `change.updated`, `change.succeeded`, `change.failed`, `change.rolled_back`, `change.cancelled`. Events and their original references remain unchanged when authorization or mapping later changes.

### 4.3. `ChangeServiceReference` — submitted identities and deferred resolution

- `change_id`, `first_event_id`, `relation_type` (`changed` / `reported_affected`);
- `ref_type` (`id` / `slug`), original `requested_service_id` / `requested_service_slug` and `requested_team_id` / `requested_team_slug`;
- **`namespace_team_id` (required Team FK)**, resolved and authorized during ingestion even when the Service is unknown;
- `normalized_ref_key`: `id:12` or `slug:team-id:9/postgresql-prod`; canonical Team ID, never mutable Team slug, defines the namespace;
- nullable `resolved_service_id`, `resolution_status`: `resolved`, `pending_resolution`, `denied`, `invalid`, `expired`;
- `verification_state`: `trusted`, `unverified`, `rejected`; verification evidence/version, `resolved_at`, `last_attempt_at`, `attempts`, `expires_at`, `last_error_code`.

**Unique key:** `(change_id, relation_type, normalized_ref_key)`. Different submitted aliases are retained as references but converge on one canonical ChangeService relation. A changed/resolved reference is never rebound automatically.

Pending lookup is strictly `(namespace_team_id, requested_service_slug)` against an active Team and non-deleted Service. Team rename/reuse does not change that ID; deleting or moving the namespace does not trigger fallback to another Team. A Service move outside the pinned namespace requires explicit review, not rebinding. Pending Service slug renames need a new event/reference; there is no alias guessing in v1. Expiry/denial is visible to the owner and can be explicitly requeued after corrected grants, with audit and a new job generation.

Team/Service/Dependency creation remains outside this subsystem. See §6 for bounded reconciliation and §7 for uniform responses to unauthorized references.

### 4.4. `ChangeService` — canonical relationship

- `change_id`, `service_id` (FK to a technical Service);
- `relation_type`: `changed` or `reported_affected`;
- `first_reference_id`, `verification_state`, verification evidence and `input_stamp`, `created_at`, `updated_at`;
- optional original identity snapshot to troubleshoot slug renames.

**Unique key:** `(change_id, service_id, relation_type)`. Service ownership does not need to match Change ownership. Impact and correlation consume this table, **not unverified text from the incoming payload**.

### 4.5. `ChangeImpact` — derived projection

Fields: `change_id`, `service_id`, `origin_service_id`, bounded `dependency_path_snapshot`, `depth`, `reason`, `computed_at`, `engine_version`, `input_stamp`, `active`. Unique key: `(change_id, origin_service_id, service_id)`; multiple paths are bounded evidence, not duplicate impact rows.

Reverse traversal starts at authorized canonical changed services and trusted reported-affected services. A graph-based trust decision must originate at an authorized changed service; reported claims cannot establish trust for each other. Keep the computation's path snapshot and graph revision; a later graph is new evidence, not proof that this topology existed at event time. Current projections may be replaced, while reviewed evidence snapshots are retained. §4.11 and §9 define revisions and traversal policy.

### 4.6. `ChangeAlertGroupCorrelation`

- `change_id`, `episode_id` (FK `AlertGroupEpisode`; its parent identifies the AlertGroup);
- `score` (relevance, not probability), `reason`, bounded `evidence`, `input_stamp`, `engine_version`, `computed_at`, `active`;
- `review_status`: `suggested`, `confirmed`, `rejected`;
- `relation_type`: `potential_cause`, `confirmed_cause`, `mitigation`, `context`;
- `reviewed_by`, `reviewed_at`, immutable reviewed-evidence snapshot, `row_version`, `updated_at`.

Unique key: `(change_id, episode_id)`. Automated writes only update computed fields and suggest `potential_cause`; they do not change review fields. Manual review uses `row_version`, checks response permission on the AlertGroup and read permission on at least a safe Change projection, and atomically records an audit. A stale review returns `409`. Changed evidence may mark a suggestion inactive without deleting a review or carrying it to another episode. `mitigation` and `context` are manual in v1; manual creation is allowed even without an automatic suggestion.

### 4.7. `ChangeIncidentLink`

- `change_id`, `incident_id`, `relation_type`: `context`, `potential_cause`, `confirmed_cause`, `mitigation`;
- `linked_by`, `linked_at`, `removed_by`, `removed_at`, `row_version`.

One active link per `(change_id, incident_id)`; removal is soft, and re-adding reactivates the relation with an audited history entry. POST requires Incident response permission and readable Change context; changing role/removing checks `row_version`. Use the existing Incident transaction/CAS contract and atomically record the Incident event, link and audit. A duplicate same-role add is `200`; a new/reactivated link is `201`; a stale or conflicting edit is `409`. No Incident status or notification is changed, and no AlertGroup is required.

### 4.8. `ChangeJob` — durable outbox / work queue

- `job_type`, `entity_id`, `state` (`pending`, `running`, `done`, `dead`);
- `requested_generation`, `claimed_generation`, `completed_generation`;
- `target_revision`, `graph_revision`, `auth_revision`, `engine_version` (the `input_stamp`);
- `lease_owner`, unique-per-claim `lease_token`, `lease_expires_at`;
- `attempts`, `next_attempt_at`, `last_error_class`, bounded discovery `cursor`, `created_at`, `updated_at`.

Unique key: `(job_type, entity_id)`. Rescheduling atomically increases `requested_generation`; it does not create unbounded duplicate jobs. If a worker is already running, its lease is preserved and the new generation remains pending until completion/reclaim. Revision changes, not exact ingest retries, request new work. Types: `resolve_references`, `refresh_impacts`, `refresh_correlations`, `sync_service_timeline`, plus bounded discovery jobs for a new episode or catalog revision.

**Commit protocol:**

1. Ingestion persists ChangeEvent, references, aggregate revision and job request in one transaction. Episode/catalog changes persist their discovery job in their own mutation transaction; discovery creates the affected per-Change jobs durably before acknowledging itself.
2. Claim atomically selects eligible pending/expired work, assigns a fresh lease token and captures generation. PostgreSQL uses a short transaction/row lock (`SKIP LOCKED` for competing workers); SQLite uses `BEGIN IMMEDIATE` with bounded busy retry. Computation runs outside the write transaction.
3. Read the input stamp before loading dependencies/mappings. Graph and authorization changes increment their revisions in the mutation transaction. A worker must not label an old snapshot with a newer revision read afterwards.
4. Publishing is one short transaction: verify the same unexpired lease token, unchanged requested generation and current input stamp, then write projections/timeline rows and mark that generation complete. Lock/recheck the compared revision rows through commit; a check in application memory alone is insufficient.
5. If any check fails, discard the result. A worker that lost its lease cannot publish, acknowledge, extend the new owner's lease, or change its retry state. A still-owning worker schedules the current generation; recovery/discovery makes it durable. Lease expiry is not a license to overwrite another worker's work.
6. Timeline writes have a unique `(service_id, source='change_intelligence', dedup_key)` derived from event UUID + relation. Projection writes and job acknowledgement share the same DB transaction, so a crash cannot leave an unacknowledged non-idempotent side effect. No external notifications are sent.
7. Retry only transient errors with bounded exponential backoff/jitter. Keep validation/permission denials visible on references and exhausted jobs in `dead`; an audited operator retry creates a new generation. Expose backlog, oldest age and failure class without payloads/secrets.

Use one documented lock order: graph-state row → integration/auth row → Change rows in ID order → job rows. Claim/reclaim locks only job rows. Existing lifecycle order remains Incident → AlertGroup → episode; lifecycle transactions only enqueue discovery work and never acquire graph/Change locks. Discovery publishes per-Change job requests before locking its own acknowledgement row, preventing job-to-Change lock inversion. No network calls or graph traversal while holding these locks.

### 4.9. `AlertGroupEpisode` — stable technical lifecycle history

Storage added in stage 1: `id`, `uid`, `alert_group_id`, `ordinal`, nullable `started_at`, nullable `ended_at`, `state` (`open`, `resolved`, `merged`), `start_quality` (`exact`, `unknown`), nullable `start_event_id`, `end_event_id`, `created_at`. Unique `(alert_group_id, ordinal)` and at most one open episode per group (partial unique constraint for PostgreSQL/SQLite). Add nullable `AlertGroup.current_episode_id`; after the stage 2 writer rollout, an open group must reference its open episode. Stage 1 leaves existing groups' pointers NULL. An episode's ID never changes on acknowledgement, shelving or repeated intake.

- Initial live group creation creates its first episode atomically with the first child and lifecycle event. A genuine `resolved → active` reuse creates the next episode and the new child in that same transaction. A duplicate reopen creates neither another episode nor another child.
- Acknowledged → firing, unshelve and severity/assignee changes stay in the same episode. An operational Incident reopen alone does not open a technical episode. Terminal groups created only from resolved input have no fabricated open episode.
- Resolve/merge closes the current episode in the transaction that closes the group; `current_episode_id` is cleared. Repeated resolve of an already resolved group is a no-op and cannot close an uncommitted new episode. Merge closes the source's episode without relabelling it as the target's episode.
- All technical lifecycle writers must use this contract: intake/recovery, manual actions/callbacks, heartbeat, orchestration, merge and resource-deletion paths. A database error rolls back group, child, episode, lifecycle event and discovery job together. Existing AlertGroup/Incident API and notification behavior remain unchanged.
- Stage 1 creates storage only: it does not reconstruct old cycles or create episodes, Changes or discovery jobs from existing alerts/events. When all lifecycle writers switch in stage 2, an already-active group receives one current episode with `started_at=NULL, start_quality=unknown`, without parsing old events or reusing `first_seen_at`. This records current state, not a recovered history. Repeating initialization must preserve existing episodes. Automatic time-based correlation skips unknown starts; new cycles are recorded from actual lifecycle transitions. Previously closed cycles are not imported. A new terminal-only group likewise cannot manufacture a known start.
- Reviewed correlation evidence and Incident-linked history pin relevant Changes/events/episodes against retention. Cleanup removes only eligible unreviewed derived rows before their parents; it does not cascade away retained investigation evidence. New foreign-key and retention rules are part of the episode migration.

### 4.10. Stable integration identity, sources and grants

The storage models are added in stage 1; administration and machine authorization are implemented in stage 3:

- `ChangeIntegration`: `id`, `uid`, name, `active`, `auth_revision`, audit timestamps. It is a machine principal independent of a person's account and of any single credential.
- `ChangeSource`: `id`, `integration_id`, `owner_team_id`, `source`, `active`, default `ordering_mode`. Unique `(owner_team_id, source)` reserves one producer namespace. Revoking a grant/token does not free that namespace for another integration; source/owner changes require a new namespace, not rewriting historical ownership. Updating ordering mode affects only new Changes.
- `ChangeGrant`: `source_id`, `capability` (`reference`, `changed`, `reported_affected`), `target_team_id`, optional `target_service_id`, normalized `target_key` (`team:9` or `service:12`), `active`. Unique `(source_id, capability, target_key)` avoids backend-dependent NULL uniqueness. `reference` permits an unverified claim and scoped identity lookup, not trusted publication; the other capabilities also permit lookup for their target. A Service grant is valid only while it belongs to the pinned target Team. A Team grant explicitly covers future Services in that Team and therefore permits pending references of its capability; a Service-only grant does not.
- Extend `ApiToken` with nullable `change_integration_id`. Integration credentials use only `changes:ingest`, have no personal `user/group/team` authority, and cannot mint credentials or access other APIs. Reuse existing secret generation, hash storage, expiry and revocation; do not introduce another token-secret store. Existing personal tokens retain their current behavior.

An active registered source grants its integration permission to submit operations for that owner/source, but not blanket permission to claim changes on all owner Services. Explicit ChangeGrants define trusted Service claims, including claims within the owner Team. Only installation administrators manage integrations, sources, grants and machine credentials in v1; ordinary ingest tokens cannot grant themselves rights. Every such mutation is audited. Changes to grants/source activity or authorization-relevant Team/Service state advance the affected integration's auth revision transactionally.

Token rotation/revocation prevents **new requests** with that credential; accepted work remains owned by the integration and continues under its current grants. Disabling the integration/source or revoking a required grant blocks new mapping/publication. Neither credential deletion nor rotation deletes immutable events. §7 defines read visibility separately from ingest authority.

### 4.11. Graph revision and projection inputs

Add `ChangeGraphState` with one monotonic `revision` row for v1. Dependency creation/update/delete and relevant Service changes (ownership, environment, enabled/deleted state) bump it and enqueue bounded invalidation/discovery in the same transaction. Global revision is deliberately simple; per-component revisions are a future optimization, not a prerequisite.

Because the stamp is global, each graph revision schedules a paginated sweep of **all Changes in the automatic horizon plus all running Changes**, not just those first guessed to be affected; otherwise unrelated rows would remain permanently stale. Coalesce this sweep into one discovery job keyed by the graph-state ID, retaining requested generation and a durable cursor. Capture an upper Change-ID bound and scan in ID order; each bounded batch atomically queues per-Change work and advances the cursor under its lease/generation check. A new graph revision restarts the sweep's generation/cursor; new Change intake has its own job. Authorization sweeps cover all still-publishable Changes of the affected integration. Per-reference retries remain indexed by namespace/slug.

The full calculation stamp is `(Change.revision, ChangeGraphState.revision, ChangeIntegration.auth_revision, engine_version)`, plus the job's requested generation. Mapping/verification changes bump Change.revision; new episodes have their own durable discovery trigger. A new trigger arriving during computation cannot be lost when the old worker acknowledges its generation. Manual review has its own row_version and immutable evidence snapshot; automated projection replacement does not write those columns.

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
- A `changed` reference requires a changed grant; every `reported_affected` reference requires at least scoped reference permission and remains unverified until supported by the dependency graph or an explicit reported-affected grant (§7.2). Accepting a pending reference grants **no new authority** over the named Service.
- After resolution, persist `service_id` for `ChangeService`, `ChangeImpact`, and correlation. Keep the submitted slug on `ChangeServiceReference`.
- Deleting, moving, or renaming a Service must not rebind an already-resolved Change to a new Service that later reuses the slug. The CMDB must manage slug stability; renames require the sender to update future references; automatic alias mapping is outside v1 and never silently changes history.
- Reuse an `event_id` **only with the same normalized request content**. Sending an ID representation and a slug representation under the same `event_id` may result in `409`, even if they resolve to the same Service. Use a new event ID for new information.

A `201` response includes safe reference counts and `correlation_status=queued` when the engine is enabled, otherwise `not_enabled`. Counters include only categories the integration may inspect; unverified foreign claims are not an existence oracle. It does not reveal foreign-Service metadata. `200` means exact retry; `400/422` invalid schema/identity; `401` unauthenticated; `403` forbidden scope; `409` external-identity conflict; `429` rate limit.

### 5.4. Read and review API

```text
GET    /api/changes
GET    /api/changes/{id}
GET    /api/changes/{id}/events
GET    /api/changes/{id}/services
GET    /api/changes/{id}/correlations
POST   /api/changes/{id}/correlations
POST   /api/changes/{id}/correlations/{correlation_id}/review
GET    /api/services/{service_id}/changes
GET    /api/alert-groups/{alert_group_id}/related-changes
GET    /api/incidents/{incident_id}/changes
POST   /api/incidents/{incident_id}/changes
PATCH  /api/incidents/{incident_id}/changes/{link_id}
DELETE /api/incidents/{incident_id}/changes/{link_id}
```

The Changes listing accepts a `service_id` filter **or** a `service_slug` filter with Team namespace, using the same resolver. Every endpoint applies RBAC and the explicit scope rules in §7; authorization predicates are added to SQL **before** pagination. Manual correlation creation specifies episode_id and relation_type; review/role changes/removal use row_version. Nested link selectors return only readable full or safe Change projections, never raw foreign details.

## 6. CMDB integration and late Service resolution

CMDB provisions Team, Service and ServiceDependency independently through existing catalog APIs; Change Intelligence creates none of them. It does not require a new vendor-specific CMDB protocol. A source/grant must already authorize the requested namespace before a reference may be accepted.

### 6.1. Service already exists

Resolve owner Team and registered source, pin the target namespace_team_id, then resolve Service by ID or `(namespace_team_id, service_slug)`. Persist canonical ID and the original reference. A changed grant permits the direct assertion; a reference-only reported claim remains unverified until an explicit grant or verified dependency path supports it. Numeric ID and slug paths enforce the same permissions.

### 6.2. ChangeEvent arrives before the Service

1. Owner/source and target namespace are known and authorized, but Service slug is absent. Persist the event/reference with `resolution_status=pending_resolution`, pinned namespace_team_id, first_event_id and expiry; show pending in the owner's Inbox.
2. No canonical Service link, correlation or foreign publication is created yet. Identity lookup never provisions a resource.
3. Catalog creation/change enqueues indexed resolution work in the catalog transaction; a periodic sweep over due pending references is a bounded fallback. It does not scan full Change history.
4. Resolve only `(namespace_team_id, requested_service_slug)`, checking current integration/source activity, grants and resource state. A Team rename is harmless; no second lookup of the original Team slug is allowed. Persist mapping/evidence, increment Change.revision and request downstream jobs atomically.
5. Token rotation/revocation alone does not stop accepted work. Missing current grants give `denied`; invalid/deleted namespace gives `invalid`; expiry gives `expired`. No fallback to a new Team/Service with a reused slug. Owner diagnostics and an audited authorized requeue are available.
6. After successful late mapping, bounded discovery also considers eligible existing episodes. Older history beyond the automatic horizon can still be linked manually. Correlation status is `not_enabled` before phase 2, rather than an endless `queued` state.

Pending TTL, retry budget and batch size are configuration limits documented before phase 1 rollout. An explicit retry never mutates the original submitted reference; correcting a Service slug uses a new event/reference. Revoked evidence, expiry and dead jobs stay inspectable rather than disappearing silently.

### 6.3. Catalog/grant changes and historical evidence

Graph changes advance ChangeGraphState.revision; authorization changes advance integration auth_revision. Service ownership/environment/active/deleted changes participate in both as appropriate, in the mutation transaction. Changes are rebuildable event projections: a catalog edit does not rewrite received events or reassign their canonical Service IDs. It invalidates relevant derived mapping/trust/impact and durably requests bounded recomputation.

Record the path snapshot and revision used for a computation. A current graph can suggest relevance to old events, but cannot prove that the same topology existed then; display that limitation in evidence. Manual reviews retain their original evidence snapshot even when current computed support disappears. No automatic transfer to an alias or newly provisioned Service is permitted. A later external_service_ref/Service.uid integration is separate future work.

## 7. Authentication, tokens and RBAC

### 7.1. Machine intake and administration

`POST /api/change-events` requires an active integration-bound `ApiToken` with `changes:ingest`, even when global API authentication is disabled. A JWT, a personal token or wildcard scope without a ChangeIntegration identity is not sufficient. After authentication, resolve owner Team and verify that the active registered `(owner_team_id, source)` belongs to this integration, then apply grants. The client cannot select another principal through payload fields.

Machine credentials are issued/rotated in a new admin-only Change Integrations UI/API, using existing ApiToken secret handling. The existing `Profile → API Tokens` remains for human read/review tokens; it does not issue integration identities. Proposed administration routes under `/api/admin/change-integrations` manage sources, grants and tokens, require an authenticated administrator JWT, and audit every mutation. Neither an ingest token nor a personal API token can administer this namespace in v1.

Scopes: `changes:ingest` for machine POST; `changes:read` for reading; `changes:write` for manual reviews/links. No implicit `changes:ingest` through `resources:write` or personal `*`. Integration tokens are accepted only on the ingestion endpoint. Human JWTs use current RBAC; personal API tokens additionally use explicit scopes and their existing Group restriction. Nested Service/AlertGroup/Incident read endpoints require both `changes:read` and the parent resource's read scope; review/link writes require `changes:write` and the target resource's write scope. Add explicit method/path rules in `api_token_scopes.py`; do not rely on a broad prefix accidentally granting an entire new domain.

### 7.2. Reference permission and trust

1. Source ownership permits operation intake only. Each changed Service needs a `changed` grant; target Team grants permit pending slugs, Service-only grants cover only the granted existing Service.
2. Reported affected claims require at least `reference` permission for that namespace/Service. This allows an unverified claim, not cross-team publication. A `reported_affected` grant or a verified server-side dependency path from an authorized changed Service can establish trust. Persist the basis and its input stamp. Losing that path/grant invalidates computed trust; it does not rewrite the received event.
3. Check permitted namespaces before disclosing target Service existence. An internal numeric-ID lookup to determine ownership is allowed, but outside the permitted scope existing, nonexistent and soft-deleted IDs/slugs receive the same safe error response. Within an explicitly permitted namespace, an unknown Team/ID is a validation error and an unknown Service slug may become pending. This resolves the tension between pending resolution and existence-oracle prevention.
4. Merge aliases of a canonical Service deterministically: it is trusted while at least one currently authorized reference or verified path supports that relation. An unverified duplicate does not demote a trusted assertion; revoked evidence cannot keep it trusted. Preserve every original reference/evidence source.
5. A grant is permission to submit a claim, not access to raw Change data or to another Team's Incident. Human read/review permissions are evaluated separately at request time, including counters, pagination, search, Explain and safe link selectors.

### 7.3. Safe cross-team projection and Service Timeline

An owner-Team reader may see operation fields, but foreign Service details/path segments still require permission for those resources. A reader with access only to an affected Service receives a whitelist projection: opaque Change UUID, that accessible Service, event time, safe kind and relation type. Use a constant title such as “Related change”; omit sender title/description, source name, external IDs, actor, URLs, raw details and private path segments. Never serialize the full object and then try to remove a few known keys.

Service Timeline must follow the same policy. The current `serialize_service_event()` returns actor, URL and payload without Change-owner checks. Therefore new change-related ServiceEvent rows contain **only the safe projection even on owner Services**; full details are fetched from the separately authorized Change endpoint. Use constant `source=change_intelligence`, safe title/summary, null actor/URL and a whitelisted payload. Add nullable indexed `change_event_id` provenance and `change_relation_type`; existing non-Change timeline events keep their behavior. A plain source_ref URL or a raw JSON copy is insufficient.

Before pagination/counting, the timeline/related-change SQL query verifies current Service access and visibility of the matching canonical Change relation/impact. After grant, graph or Service ownership changes, stale derived visibility is withheld until revalidated; a delayed worker must not preserve an obsolete authorization decision. Owner audit/history and manually reviewed evidence are retained without exposing them through a foreign projection. Manual review uses the same redacted evidence when full owner data is unavailable; linking a Change to an Incident does not grant its participants owner-data access.

### 7.4. Revocation and accepted work

Credential revocation/expiry blocks new intake immediately, including retries; rotation does not change source identity or event ownership. Previously accepted work is reauthorized against current integration/source/grants, **not the continued existence of its old token**. Disabling the integration/source or withdrawing grants increments auth_revision and blocks dependent mapping/new publication. Jobs and events remain auditable; after an authorized re-enable, explicit reconciliation can resume them. No old secret is stored in a job.

## 8. Lifecycle and out-of-order delivery

### 8.1. Source ordering contract

The source explicitly selects one mode; it is copied to each new Change. A mode change on the source affects future Changes only. Existing operations and events never switch ordering rules.

| Mode | Required input and order | Rejection |
|---|---|---|
| `timestamp` (default for simple senders) | timezone-qualified `occurred_at`, normalized to UTC; event time, never ingestion time | Any `source_sequence` is `422` |
| `sequence` | non-negative integer `source_sequence` on every event, unique within Change; gaps and lower sequence arriving late are allowed | Missing/invalid sequence is `422`; another event reusing a sequence is `409` |

`occurred_at` remains required in both modes and drives correlation time, even when sequence orders lifecycle. `received_at` is audit only and is never a tie-breaker. Reject naive timestamps and timestamps over the configured future-skew limit (default five minutes) with `422`; do not silently replace them with server time. Backdated events remain history; automatic historical correlation is bounded separately (§9). A sequence/time inversion is diagnostic, not permission to fabricate an occurrence time.

### 8.2. Deterministic status projection

Terminal types are `succeeded`, `failed`, `rolled_back`, `cancelled`. Reduce the entire accepted set, not the arrival sequence. For sequence mode, use sequence as the order key; for timestamp mode, use occurred_at. The **greatest terminal key** determines the outcome; started/updated events cannot undo a terminal outcome.

| Accepted lifecycle evidence | Projected status |
|---|---|
| No started or terminal event; only updates | `unknown`, no lifecycle conflict |
| Started event(s), no terminal event | `running` |
| One terminal outcome at the greatest terminal key | That outcome, regardless of later-delivered started/updated |
| Several different terminal outcomes at the same greatest occurred_at, without sequence | `unknown`, `lifecycle_conflict=true`; retain all conflicting event IDs |
| A later-key terminal event after the conflict | Its outcome; current conflict clears, historical diagnosis remains |

In timestamp mode, same-time terminal events with the same outcome are not a conflict. An event ID can order display and equal-time metadata deterministically, but cannot choose between success and failure. A later-key terminal outcome can supersede an earlier different outcome (including failed → succeeded or succeeded → rolled_back); the event history is retained. Starting a new execution still requires a new change_id, not a started event that erases an old outcome.

Examples use **sender event time**:

| Events, in any delivery order | Result |
|---|---|
| failed at 10:05; succeeded at 10:10 | succeeded, even if failed arrives last |
| succeeded at 10:10; started at 10:00 delivered last | succeeded |
| succeeded and failed at exactly 10:10 | unknown + conflict |
| That conflict; rolled_back at 10:20 | rolled_back |
| sequence 20 failed at 10:10; sequence 21 succeeded at 10:09 | succeeded by sequence; time inversion diagnostic, original times retained |

### 8.3. Other fields and atomic ingestion

`kind` and normalized environment (including initial absence) cannot change within an operation (`409`). Title is non-empty; description/URL may be cleared explicitly with null. For mutable fields choose the greatest-key event that **supplies that field**, using external_event_id lexicographically for equal-time metadata. Absence means preserve; received_at and DB auto-increment IDs never decide the winner. `change.updated` updates these fields/references only, not lifecycle status; it has no arbitrary status property. Actor/details belong to each event, not a destructive merge of unrelated dictionaries.

`started_at` is the earliest occurred_at of started events; absent started is NULL. `completed_at` is the occurred_at of the winning terminal event, or NULL on no terminal/conflict. first/last_occurred_at are min/max over accepted events. Negative or inverted duration is diagnosed and not rendered as a valid duration. For correlation, the exposure interval begins at started_at when known, otherwise at the earliest terminal event time; updated-only operations and unresolved terminal conflicts do not produce automatic cause suggestions. A metadata update is not a new exposure.

Service references accumulate across events; omitted or empty lists do not remove earlier relations. Pending/denied mappings do not rewrite operation status. In one write transaction, serialize on source/Change identity, insert the immutable event, update references and deterministic projection, advance revision and request outbox work. A failure anywhere rolls back all of them. PostgreSQL uniqueness handles concurrent first inserts; SQLite reserves the write before reading. Retrying after rollback produces one event and one effective generation.

## 9. Change Intelligence / Correlation

1. Inputs are canonical authorized changed Services and trusted reported-affected Services. Unresolved, denied, unverified and expired claims do not seed correlations.
2. Traverse active, non-deleted `ServiceDependency` backwards (consumer → provider in storage, provider → consumers for impact), respecting `enabled`, `correlation_enabled`, dependency type, environment and propagation-delay evidence. Bound depth (default 5), nodes, candidates and execution time; handle cycles and choose paths deterministically. Direct matches and multiple paths must not produce duplicate correlation rows. Conflicting known environments exclude an automatic candidate; absent environment is unknown, not a match.
3. Capture path snapshots and the full input stamp. Recomputing from today's graph does not claim it was the historical graph; show computation time/revision and retain reviewed evidence separately. Ingestion does not call the existing operational Service Impact engine's status-writing side effects.
4. Only known episode starts participate automatically. For an operation's exposure interval `[start, end]`, candidate episodes start in `[start, end + W]`, where W defaults to two hours. start is defined in §8.3; end is the winning terminal time, or calculation time for a running operation. Inverted intervals are excluded with a diagnostic. Evaluate running operations on new episode triggers as well as ChangeEvents; do not use AlertGroup.first_seen_at as a reopened episode start. Retroactive discovery of completed operations/old episode starts has an explicit horizon (default seven days); do not discard a still-running operation solely because it began earlier. Older history remains available for manual linking.
5. Automatic rows always suggest `potential_cause`. A Change whose exposure starts after an episode start is not automatically its cause. **Mitigation is manual in v1**: an operator can link the later Change to that exact episode, or directly to an Incident, including without an automatic candidate. Manual links outside the automatic time window are allowed with an audited explanation; no score is invented for mitigation.
6. Score is versioned deterministic relevance, not probability. Candidate selection/ties, weights, missing-data behavior and limits are part of engine_version and must have fixed fixtures before phase 2 acceptance. Do not let unordered SQL/graph iteration change ranking. Never overwrite a manual role/review or export private path segments in Explain.
7. New ChangeEvents, episode creation/closure, mapping changes and catalog/grant changes create durable bounded discovery/recompute work. Retrying or restarting workers neither loses a trigger nor duplicates projections (§4.8).

No automatic rollback, paging/escalation, Incident creation/status change or technical status change follows from a correlation. A manual confirmed_cause is an operator's recorded judgement, not a claim that timing alone proves causation.

## 10. UI

**Operations → Changes** is a separate Inbox, with one row per Change.

- Search by ID, title, source, external ID, accessible services, and `service_slug`.
- Filters: Team (owner **or** accessible affected), Service (ID or slug + Team namespace), kind, status, source, environment, date range, correlation, `unmapped/pending`.
- A Change spanning multiple Teams still appears once; SQL-side authorization, distinct selection, counts, and pagination must be correct.
- Change Details displays lifecycle history with occurred_at and received_at, ordering mode, explicit terminal conflict, **Changed**, **Reported affected**, **Inferred impact**, mapping/expiry/job state and authorized evidence. A foreign reader receives only the safe projection, not the owner's details page.
- For `pending_resolution`, show the original slug/Team namespace, pending reason, and last attempt in the authorized owner context. Do **not** automatically create Services from the UI.
- AlertGroup Details selects the current or a historical episode and shows only that episode's Related Changes/reviews. Unknown boundaries and manual mitigation are explicit. Incident Details supports context/potential_cause/confirmed_cause/mitigation without requiring an AlertGroup.
- Service Timeline reuses `ServiceEvent` only after resolution, with stable deduplication, indexed provenance, safe stored projection and SQL visibility from §7.3. Full Change data comes from its own authorized endpoint; inferred impact is never labelled a direct modification.
- Cross-team redacted views show the user's own Service, safe change type/time/relation, without revealing private topology, raw payload, actor, or URL.

## 11. Operational and technical requirements

- Pydantic v2: strict mutually exclusive ID/slug forms, timezone-qualified event time, strict sequence integer, limits on strings/reference count/body/details. Enforce body size before parsing, request timeouts and per-integration rate limits; no global Service slug search.
- Apply authentication regardless of optional global API auth. Recheck source/grants under the ingestion transaction's authorization revision lock; an authorization check performed only before a concurrent revocation is insufficient.
- DB constraints and short write transactions on PostgreSQL/SQLite; explicit rollback and bounded transient retries. No network or graph traversal under lifecycle/Change locks. Follow §4.8 lock order; multiple integration rows lock in ID order.
- Deploy the durable worker in phase 1 using the existing scheduler and database; Redis/Celery is not required, and an in-memory-only Flask queue is insufficient. Claims, lease heartbeats, expiry, retry/dead state and projection commit must all enforce lease_token/generation. Existing scheduler singleton locks are supplementary, not proof of exclusive ownership after expiry.
- Index Change(owner_team_id,last_occurred_at), source/external unique identities, ChangeService(service_id,change_id), ChangeServiceReference(resolution_status,namespace_team_id,requested_service_slug), ChangeImpact(service_id,active), correlation(episode_id,review_status), ChangeJob(state,next_attempt_at), timeline provenance and episode(group,ordinal). Validate query plans on a bounded representative dataset before enabling discovery.
- Apply current RBAC/projection validity in SQL before counts, search and pagination. Never put full owner payload/actor/URL into a cross-team timeline entry or a client cache accessible after permission changes.
- Keep received event time and sender time distinct; UI displays UTC offsets and explicit conflict/unknown-boundary/stale/mapping states. Unknown duration or cause is not silently guessed.
- No high-cardinality IDs/slugs/uncontrolled source names in Prometheus labels. Measure ingest accepted/duplicate/rejected, pending/denied/expired references, queue age, claims/reclaims, discarded stale work, correlation duration/error classes and lifecycle conflicts.
- Redact secrets before persistence of diagnostic data and logging; allow safe URL schemes and escape content. Document payload limits, future skew, pending TTL, retry budget, discovery horizon, retention and idempotency retry horizon. Reviewed/Incident evidence is protected from cleanup (§4.9).
- Preserve old ServiceEvents without reliable external Change IDs; do not synthesize a Change or episode history from guesses. Document additive migration, writer/worker rollout and operational rollback; do not drop evidence on rollback.
- EN/RU/DE/FR/ES/ZH UI, OpenAPI, all §13 scenarios and supported Python CI. Architecture changes are not a claim that implementation or release verification is complete.

## 12. Delivery plan

Implementation is split into **10 sequential stages**. Each stage ends with a reviewable change set and its own tests; the next starts after the previous readiness criteria pass. Stage 1 storage is implemented; stages 2–10 remain planned. See [the stage 1 guide](change-intelligence-stage-1.md) for rollout restrictions and checks. Distribute the scenarios in §13 across stages rather than deferring them all to release checks.

| Milestone | Stages | Result |
|---|---|---|
| Phase 1 — Registry and durable foundations | 1–6 | Intake, history, a working pending-reference worker and Changes Inbox in a test deployment; `correlation_status=not_enabled` |
| Phase 2 — Explainable correlation | 7–8 | Cause suggestions, protected manual decisions and episode/Incident link APIs |
| Phase 3 — UI integrations and release | 9–10 | Service Timeline, AlertGroup/Incident pages and verified deployment |

A development stage is not a separate production release. Enable public Change Event intake only after stage 10 verifies the complete path: intake → authorization and Service resolution → worker → correlation with the exact AlertGroup episode → authorized link display. Stage 6 is an internal milestone, not an independent registry release. Stage 1 creates storage without capturing episodes or reconstructing past cycles; stage 2 coordinates all lifecycle writers when episode recording starts. Deploy schema, writers, worker and read policy before enabling intake. Document and localize APIs, settings and UI as they appear; stage 10 checks completeness.

### 12.1. Stage 1 — Models, constraints and migrations

- **Work:** Change, ChangeEvent, ChangeServiceReference, ChangeService, ChangeIntegration, ChangeSource, ChangeGrant, ChangeJob, ChangeGraphState and AlertGroupEpisode models; ApiToken/AlertGroup fields; uniqueness, foreign keys and indexes. Add job-request persistence within the caller's transaction. Create storage and the initial graph revision only; do not reconstruct episodes or enqueue work for existing alerts. Correlation/manual-link models and timeline fields arrive with their consumers in stages 7–9.
- **Tests:** fresh database and upgrade; rerun migration; existing alerts/events/tokens remain unchanged and no episodes/Changes/jobs are created; failure rolls back schema and initialization; one open episode; uniqueness and foreign-key constraints on PostgreSQL/SQLite. A job request rolls back with its transaction.
- **Ready when:** schema creation/upgrade preserves existing data without starting episode recording or intake; process rollout order and recovery from a failed migration are documented.

### 12.2. Stage 2 — Episodes across all AlertGroup writers

- **Work:** atomically create/close episodes on intake, genuine reopen, resolve, recovery, callbacks, heartbeat, orchestration, merge and resource deletion. At writer rollout, initialize one unknown-start current episode for already-active groups without reconstructing closed cycles. Persist discovery work in the same transaction; processing arrives in stage 5. Preserve Incident → AlertGroup → episode lock order and existing notifications.
- **Tests:** idempotent initialization of existing active groups without guessing a start; closed groups receive no historical episodes; two reopens; resolve racing reopen; repeated resolve; failures writing child, event or job. Ack → firing, unshelve and Incident-only reopen do not create an episode.
- **Ready when:** every writer follows one contract, failed transactions leave no partial episode, and existing lifecycle tests pass on both databases.

### 12.3. Stage 3 — Integrations, grants and credentials

- **Work:** administrative integration/source/grant/rotation APIs and UI; machine ApiToken, explicit scopes and route allowlist; audit and auth_revision. Implement owner/source and Service-scope checks, including reference-only grants. Preserve existing personal-token behavior.
- **Tests:** source/Team impersonation; exceeding grants; uniform safe errors for inaccessible IDs; ingest credentials cannot read or administer; rotation, revocation and concurrent permission edits. Personal wildcard scope cannot replace integration identity.
- **Ready when:** an administrator can provision an integration and replace its secret without changing event ownership; permission edits atomically advance revision. Continuing accepted work is tested with the worker in stage 5.

### 12.4. Stage 4 — Atomic intake and Change projection

- **Work:** validate the common payload; resolve ID/slug with pinned namespace_team_id; implement digest/idempotency and deterministic timestamp/sequence projection. Write event, references, Change state, revision and job request in one transaction that rechecks authorization. Keep the endpoint disabled in production until the stage 10 end-to-end acceptance checks pass.
- **Tests:** event permutations, tied conflicting terminals and a later terminal; late started; sequence gaps/reuse; absent/null; rotation and event_id retries; concurrent first requests; failure at every write step.
- **Ready when:** exact retry returns `200` without new effects and conflict returns `409`; retry after rollback persists once; delivery order cannot change the projection of an accepted event set.

### 12.5. Stage 5 — Worker, pending references and recomputation

- **Work:** claim/lease/generation, current-input checks on publication, retry/backoff, expiry, dead state and audited requeue. Connect catalog/auth revisions, episode discovery, durable sweep progress and periodic pending reconciliation. Run available handlers; do not queue endlessly waiting work for disabled correlation before stage 7. Specify TTL, limits, retry horizons and queue metrics.
- **Tests:** lease loss and late publication by the old worker; a new trigger during calculation; crash/restart around publication/acknowledgement; late CMDB provisioning, Team rename and slug reuse; accepted work after credential revocation; grant withdrawal during computation; resuming a failed sweep.
- **Ready when:** jobs survive restart, retain new requests and avoid duplicates; pending resolves only in the original Team under current authority; failures remain visible in diagnostics.

### 12.6. Stage 6 — Read API and minimal Changes Inbox

- **Work:** list/details/events/services; search, filters, counts and pagination with SQL RBAC; full owner projection and safe projection for an accessible affected Service. UI shows terminal conflicts, mapping, pending/expired/dead and processing state. Document the common API and a sender example.
- **Tests:** one multi-Team Change is not duplicated; owner, affected-team and unrelated readers see only authorized fields; filters/search/counts leak no hidden data; end-to-end intake → pending → Service creation → display.
- **Ready when:** phase 1 works in a test deployment with a worker, configuration limits are documented, and correlation is explicitly `not_enabled`. Production intake remains disabled until episode linking and the final acceptance checks are complete.

### 12.7. Stage 7 — Automatic correlation

- **Work:** ChangeImpact and ChangeAlertGroupCorrelation migrations; bounded reverse graph traversal and exact episode association. Fix the rule version and reference ranking fixtures before implementing score. Connect every recomputation trigger, including a sweep of the eligible history on global graph revision changes; publish only with a current input_stamp. Automation suggests potential_cause only.
- **Tests:** direct/indirect relationships, cycles, diamonds, disabled edges, environment, window boundaries, long-running operations and unknown episode start; Change before/after AlertGroup; graph/grant changes during calculation; repeated jobs and stable ranking.
- **Ready when:** identical inputs produce the same result and explanation, stale calculations cannot publish, and there is no automatic mitigation or operational status/notification mutation.

### 12.8. Stage 8 — Manual review and Incident links

- **Work:** manual episode-link creation, confirm/reject, context/mitigation; row_version, audit and retained evidence. Add ChangeIncidentLink and add/change/remove/reactivate APIs using Incident transactions/CAS. Protect linked evidence from retention as links are introduced. Change Details actions use the authorized full or safe projection.
- **Tests:** concurrent confirm/reject and link edit/removal; no automatic suggestion; mitigation outside the automatic window; duplicate add/reactivation; link/event/audit write failures; recomputation after review; a new episode; parent cleanup.
- **Ready when:** stale writes return `409`, retries obey `200/201`, manual decisions and evidence survive recomputation/cleanup without moving to another episode. A link grants no access to private Change data.

### 12.9. Stage 9 — Service Timeline and AlertGroup/Incident pages

- **Work:** ServiceEvent provenance fields and safe stored projection; idempotent timeline publication with SQL visibility checks. Add episode selection and Related Changes to AlertGroup, and link display/actions to Incident. Connect the preceding APIs without modifying Service status or notifications.
- **Tests:** publication retry and crash/retry create no duplicate timeline entries; one Change across every screen reveals no extra fields; access revocation, Service move, stale input_stamp and browser navigation; existing ServiceEvents retain their behavior.
- **Ready when:** owner and affected-team views are consistent across pages; private title/source/actor/URL/payload never enter another team's timeline or cache.

### 12.10. Stage 10 — Release checks

- **Work:** reconcile OpenAPI, CI/CD and CMDB examples, six locales, settings/limits, metrics, migration/worker/rollback instructions. Document feature enablement order and stopping processing without deleting history. Check key SQL query plans and bounded traversal on representative data.
- **Tests:** all §13 scenarios on PostgreSQL/SQLite, supported Python CI, upgrades with existing data, repeated/failed migrations, worker restart, end-to-end roles and AlertGroup/Incident/notification regressions. Verify intake through authorized episode-link display, including retries and Change/Alert arrival in either order, before enabling public intake. Explicitly record any unexecuted required check as a blocker.
- **Ready when:** mandatory results are recorded, no blockers remain, and deployment/recovery is reproducible. Completing the RFC or one stage does not establish release readiness for the whole Change Intelligence subsystem.

## 13. Acceptance criteria and required tests

All applicable persistence/concurrency scenarios run on PostgreSQL and SQLite. Use real independent connections for races, with barriers/events rather than timing-only sleeps. Check stored state, returned result, event/audit count and queued work, not just HTTP status.

| Area | Required regression scenarios |
|---|---|
| Identity | Slug-only and mixed-ID input; identical Service slugs in two Teams; explicit namespace mismatch; unknown numeric ID versus pending slug; aliases converge to one canonical relation |
| Pinned namespace | Rename Team, then reuse its old slug for another Team: pending resolves only in the original namespace_team_id; delete/move the namespace or Service: no automatic rebind |
| Reference permission | Unknown/existing/deleted foreign IDs yield indistinguishable denials without a namespace grant; reference-only grants do not publish unverified claims; graph-backed trust is invalidated when its evidence disappears |
| Idempotency | Same event/digest is 200 with no revision/job increase; changed digest or another change_id under that event ID is 409; concurrent first events produce one operation/event/logical job; rotation preserves namespace/deduplication |
| Ordering | All permutations of the same accepted events produce identical status and metadata; sender occurred_at wins over received_at; sequence gaps and late lower values work; missing/mixed/duplicate sequence is rejected as specified |
| Terminal conflicts | Same-time succeeded/failed in timestamp mode stores both, returns unknown + conflict; same-outcome ties do not conflict; later terminal clears current conflict; late started/updated cannot reopen a completed Change |
| Field projection | Absent versus null fields, timestamp offsets/microseconds, same-time metadata ordering, immutable kind/environment, empty Service lists, future skew and inverted durations |
| Ingest atomicity | Inject failures after Change insert, event insert, reference merge, projection and outbox write: no partial Change/event/job remains; retry succeeds once |
| Integration authority | Token for source A cannot impersonate source B or another owner; ingest cannot read, review, administer credentials or edit Incidents; personal wildcard/JWT cannot bypass machine identity |
| Revocation | Accepted pending work survives token rotation/expiry/revocation; new requests with old token fail; integration/source disable or grant withdrawal prevents mapping/publication, including a worker already computing |
| Episode rollout | Stage 1 preserves alerts/events and creates no episodes/Changes/jobs; stage 2 initializes one unknown-start current episode per already-active group without reconstructing closed cycles; acknowledged → firing is not mistaken for resolved reopen; old ServiceEvents are not invented as Changes |
| Episode atomicity | Two simultaneous reopens create one episode/child; child/event/job failure rolls everything back; manual resolve during uncommitted reopen cannot close its new episode; duplicate resolve closes once |
| All lifecycle paths | Recovery/manual callbacks, heartbeat, orchestration, merge and resource deletion close/open episodes correctly; ack/unshelve/Incident-only reopen do not create episodes |
| Job fencing | Worker A loses lease; B publishes; A resumes: A cannot publish/ack/change B's retry. Trigger arriving during computation is not lost. Crash before/after projection publication creates neither lost jobs nor duplicate timeline rows |
| Input revisions | Graph, grant or mapping changes while worker computes: stale input stamp cannot publish; stale cross-team visibility is withheld before pagination/counts; unrelated manual review is retained |
| Discovery/expiry | Change-before-AlertGroup and AlertGroup-before-Change; late CMDB provisioning; periodic fallback; bounded batch/depth/horizon; graph sweep covers unrelated Changes too, survives a batch crash and restarts on a new revision; pending expiry/dead job and audited requeue |
| Correlation | Direct/dependent match, cycles/diamonds/multiple paths, disabled/deleted edges, correlation_enabled=false, environment mismatch/unknown, long-running operation, exact window boundaries and unknown episode start |
| Human review | Concurrent confirm/reject yields one accepted version and 409 for stale review; recomputation preserves role and reviewed evidence; a new episode never inherits the previous review |
| Manual mitigation | A later change has no automatic cause suggestion but can be manually linked to an earlier episode or Incident with an audited explanation; no fake relevance probability or paging |
| Incident links | Unlinked Incident supported; duplicate add/reactivation/remove/role change obey 200/201/409; link/event/audit rollback together; no Incident status or notification mutation |
| Redaction | Same Change via inbox/details/search/counts/Explain/timeline/Incident links: affected-team viewer sees no private title/source/IDs/actor/URL/payload/path; Service move, access withdrawal and browser cache navigation do not expose stale full data |
| Retention and rollout | Reviewed/Incident evidence retained across parent cleanup; idempotency tombstones preserve retry horizon; no machine auth regression on legacy APIs; schema upgrade/retry, rollback procedure and worker deployment documented |

Document payload/retention/retry limits in configuration and OpenAPI before phase 1 acceptance. Provide fixed scoring/ranking fixtures before phase 2 acceptance. Treat unknown historical boundaries and withheld stale projections as explicit UI states, not silent data loss.

## 14. Compatibility with IncidentRelay 2.5

Checked against `release/2.5.0` on 2026-10-28 (`7cf123d` plus the local resolve/reopen fix). Stage 1 adds storage in the working tree; the remaining behavior and routes are future work. This does not enable Change Intelligence or claim it was included in the released 2.5 baseline.

Reusable existing contracts: globally unique Team.slug; Service(team,slug) and Service.uid; ServiceDependency; ServiceEvent with its dedup key; AlertGroupCorrelation for AlertGroup ↔ AlertGroup; separate operational Incident/IncidentAlertGroupLink; hashed ApiToken; centralized API scopes; scheduler/database locks. Incident collaboration in 2.5 uses its own state/version and must not be coupled to technical Change ingestion.

Required integration changes are explicit:

- Add episode persistence to every technical lifecycle writer. `reopen.py` currently preserves historical AlertGroup.first_seen_at and reuses the group with a new child; a stable cycle key cannot be inferred from that field. Preserve its Incident → AlertGroup lock order and resolved no-op behavior.
- Reuse the Incident transaction/CAS helpers for manual links and audit; preserve the independence of Incident and AlertGroup lifecycle.
- Extend ApiToken and middleware with an integration-bound principal, a route allowlist and explicit scope rules. ApiToken.team alone is not a multi-team/source grant model; the Profile endpoint remains personal-token management.
- Extend catalog write transactions with graph/auth revision and discovery hooks. Existing `db_lock.py` scheduler locks do not replace per-job lease fencing and publication checks.
- ServiceEvent's current serializer exposes actor/URL/payload. Add safe stored Change projection, provenance and SQL visibility before enabling timeline publication; retain existing event contracts for other categories.
- Update retention so new retained evidence is not removed by existing AlertGroup/Service cascades. Migration and rollback/deployment order must prevent a mix of old lifecycle writers and episode-aware readers.

Proposed modules: `app/services/change_intelligence/` (identity, projection, grants, jobs, reconciliation, correlation), `app/modules/db/changes_repo.py`, Change schemas/views/OpenAPI, episode persistence helpers, and Changes/Admin UI assets, plus migrations, translations and tests. Keep these as domain modules inside the existing application; a generic plugin/event-sourcing platform is not required.
