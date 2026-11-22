# Persistence and application operations

`app/modules/db` contains persistence queries, row locks and storage helpers.
It must not import `app.services`, `app.views` or `app.notifiers`, including
imports inside functions. Moving an import into a function does not remove the
dependency. Repositories do not dispatch application callbacks through a global
registry either.

Application services coordinate operations that combine persisted state with
authorization, lifecycle decisions, metrics or work scheduling. HTTP handlers,
workers, imports and CLI commands call those services. Services can use the
existing repositories and Peewee models; there is no additional persistence
framework or event bus.

## Operation entry points

| Operation | Application module |
|---|---|
| Create, restore, update and delete groups | `app.services.group_management` |
| Create, restore, update and delete teams | `app.services.team_management` |
| Service lifecycle and dependency graph changes | `app.services.service_catalog.mutations` |
| Create, acknowledge, resolve, recalculate and merge alert groups | `app.services.alerts.group_state` |
| Open, refresh and close episodes; request eligible discovery | `app.services.alerts.episodes` |
| Close alert groups when resources are deleted | `app.services.alerts.resource_deletion` |
| Delete heartbeats and routes with their runtime state | `app.services.heartbeat_management`, `app.services.route_management` |
| Validate, publish and roll back orchestration versions | `app.services.orchestration.publication` |

These Python entry points replace the corresponding internal repository
functions. Public HTTP routes, request/response schemas and database schemas are
unchanged. Read operations remain in the repositories. Application callers and
test interception points must use the service module for a lifecycle operation.

## Transaction ownership

- Catalog operations retain `catalog_authorization_change` or `graph_change`.
  Catalog locks, integration locks, authorization rechecks, mutation and durable
  invalidation requests remain inside the same transaction and in the same order.
  Do not move `recheck_team_write` outside that transaction.
- Group and team deletion call the child lifecycle services. Nested operations
  participate in the outer transaction; a child failure rolls back the cascade.
- Episode writes require the caller's transaction and group lock. Lifecycle
  operations decide eligibility and persist discovery work before committing.
  A storage-only write must not silently replace one of these operations.
- Orchestration publication validates the locked draft and publishes that same
  version. Rollback clones and validates a new version inside the existing
  transaction. Never validate a draft outside its publication lock.
- Alert-group counters are emitted by the lifecycle service at the existing
  transition points. In-memory/external metrics are not transactional database
  state; moving the hook does not introduce a new exactly-once guarantee.

## Shared technical functions

`app.modules.token_hashing.hash_token` implements the existing token digest
without importing HTTP authentication. The authentication service re-exports it
for existing consumers. `app.modules.db.system_settings_repo.get_settings`
reads the settings singleton afresh; the settings service retains authorization
and auditing for updates. Queue lease and retry settings retain their existing
read timing and behavior.

## Verification

`tests/architecture/test_repository_dependencies.py` checks all repository
imports, including function-local and literal dynamic imports. It runs in the
normal pytest CI suite. Transaction-boundary regression tests accompany the
existing lifecycle, deletion, publication, token-authority and Change Intelligence
tests. PostgreSQL concurrency tests continue to exercise row locking separately
from SQLite tests.

This dependency contract does not change the Flask package bootstrap in
`app/__init__.py`; separating package initialization from application construction
is a distinct task.
