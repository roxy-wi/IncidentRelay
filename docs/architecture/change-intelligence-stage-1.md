# Change Intelligence: stage 1 storage and migration

This stage implements storage only: ten new models, nullable integration/episode references on ApiToken and AlertGroup, database constraints, and `request_job()` to record work in the caller's transaction. The migration does not reconstruct past episodes or create Changes/jobs from legacy alerts. No intake API, integration management, worker, correlation or lifecycle-writer changes are enabled. See [the delivery plan](change-intelligence-architecture.md#12-delivery-plan).

The migration is `20261028010000_change_intelligence_foundation`. PostgreSQL and SQLite are supported. Schema changes and graph-state initialization share one transaction; the migration runner records success in that transaction as well. A failed upgrade must not be marked applied.

## Storage contracts

- `Change.source` is a ForeignKeyField whose column is `source_id`; the sender's string name lives on `ChangeSource.source`. Composite foreign keys keep owner/integration/source, events and Service reference provenance consistent.
- Database uniqueness covers owner/source, external Change/event IDs, non-null per-Change sequences, normalized grant/reference keys, canonical Service relations and job identity. NULL event sequences remain valid for timestamp sources. An episode has a unique group/ordinal and a partial unique index permits only one open episode per group.
- `ChangeGraphState(id=1)` holds a positive graph revision. `request_job()` requires an existing transaction, coalesces requests by type/entity, increments generation and preserves a running worker's lease. It does not implement claim or processing. A rolled-back domain mutation also rolls back the job request.
- API credential deletion clears only the event's audit FK. Integration/source/owner and canonical Service history use restrictive foreign keys; they cannot silently disappear through parent cascades. Event retention and digest tombstones are not enabled by this stage, so accepted event identities are not being purged.
- Episode timestamps survive removal of their optional lifecycle-event references. Deleting an unreviewed group removes its episodes through the existing group cleanup. Retention protection for future manual reviews/Change–Incident links must be added with those models in stage 8, before those links can be created.
- The nullable `current_episode` FK validates existence. Updating it together with the correct group's open episode is the lifecycle-writer contract for stage 2; this stage deliberately does not attach new runtime operations to episodes.

## Starting episode recording and intake

Existing AlertGroups, Alerts, AlertEvents and tokens remain unchanged. Existing groups have `current_episode_id=NULL`; the new episode, Change and job tables remain empty. Only `ChangeGraphState(id=1, revision=1)` is initialized. Rerunning the migration preserves any episodes, pointers and graph revision already written by later code.

Stage 2 will record new lifecycle transitions and coordinate every writer. Already-active groups will receive one current episode with an unknown start at that transition; closed cycles will not be reconstructed. This initialization belongs to the writer rollout, not to the storage migration. No ServiceEvent is converted into a Change.

Public Change Event intake remains disabled until stage 10 verifies the entire path from intake and authorization through Service resolution, worker processing, episode correlation and authorized link display. Stage 6 is a test milestone; it does not enable production intake.

## Upgrade and recovery

1. Use a backup restored to a disposable database to exercise the upgrade first. Record group/Alert/event/token counts and verify their preservation, including after a rerun.
2. For a future production schema upgrade, back up the database and stop writers for the migration. Stage 1 does not begin episode recording and does not depend on historical reconstruction.
3. Run `python manage.py migrate` against the intended database, then `python manage.py migration-status`. Check the migration record, preserved legacy rows, NULL references, empty episode/Change/job tables and initial graph revision. On rerun, existing new-model data must be preserved.
4. On failure, preserve the error and verify that the transaction rolled back. Correct the cause and rerun the normal migration command. Do not add a success record manually or delete historical rows to make a constraint pass.
5. After the schema upgrade, existing lifecycle writers may resume: stage 1 starts no episode recording and schedules no processing. Stage 2 must switch all writers together when recording begins. Public intake remains disabled until the final end-to-end acceptance checks; this migration invokes no external systems.

The circular current-episode FK needs explicit completion after Peewee creates the tables. On SQLite, a fresh installation may contain an unused deferred column: only that NULL column is replaced, without rebuilding a populated AlertGroup table. Ordinary upgrades add the missing nullable FK. Older SQLite can rebuild an empty bootstrap table; repairing a populated unconstrained column requires SQLite 3.35+ and fails explicitly otherwise.

`downgrade()` intentionally refuses to delete the new history. For rollback, stop writers and restore the pre-upgrade backup together with matching application code. Do not roll back only the migration record. After writes have resumed, restoring a backup requires accounting for those newer writes; this migration does not claim a lossless automatic downgrade.

## Verification

After removing historical reconstruction, local verification on 2026-10-28 (Python 3.12, Windows): SQLite **81 passed, 1 skipped** (a PostgreSQL-only type assertion); PostgreSQL 16.15 **82 passed**. Ruff lint and formatting checks passed.

This regression selection includes `tests/migrations`, `tests/test_change_intelligence_models.py` and `tests/test_models.py`. The external Grafana OnCall and PagerDuty import-tool suites are excluded. This is scoped verification of the migration change, not a full release/CI run.

Run the new model and migration tests on both PostgreSQL and SQLite, plus existing migration and core-model regressions. The new tests cover preservation of legacy alerts/events/tokens, absence of generated episodes/Changes/jobs, migration rerun and failure rollback, preservation of existing episodes and graph revisions, FK/unique/check constraints, token deletion, concurrent job requests and request rollback.

Local Windows runs use an import-only substitute for the unrelated POSIX `fcntl` module; any actual file-lock call raises an error. Database locks, migrations, transactions and concurrent requests use the real database backends. Linux/POSIX runtime checks remain part of the supported-platform CI; no application source is changed to bypass those checks.
