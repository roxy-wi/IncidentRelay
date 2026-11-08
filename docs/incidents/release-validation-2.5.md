---
title: IncidentRelay 2.5 release validation
description: Local release checks on 27–28 October 2026, resolved concurrency blocker and remaining CI gates.
---

# Release validation — 27–28 October 2026

**The PostgreSQL resolve/reopen blocker is fixed. Linux/POSIX checks and the
Python 3.10–3.14 CI matrix still need to pass before release.**
The documentation and OpenAPI update is complete. Legacy AlertGroup responder and
stakeholder API/storage removal is approved as a 2.5 breaking change.

The 27 October checks used `7738f25` plus the workspace and documentation changes
on `release/2.5.0`, subsequently committed as `7cf123d`. The 28 October follow-up
used `7cf123d` plus the uncommitted resolve/reopen fix. No commit or push was made
for this fix. All databases were tested in isolated copies; the development
checkout's database was not used.

## Results — 27 October

| Check | Result |
|---|---|
| SQLite suite, Python 3.12.10 on Windows | 2,275 passed; 78 skipped; 2 deselected |
| SQLite coverage, including branches | 73.46% (required: 50%) |
| Full PostgreSQL 16.15 suite, including `tests/postgresql` | 2237 passed, 5 failed, 17 errors, 77 skipped in the initial run; see follow-up below |
| Final OpenAPI contracts and environment-related PostgreSQL retries | 62 passed |
| Final OpenAPI/combined activity checks on SQLite | 33 passed; the additional same-user/different-role scenario also passed |
| Workspace in real Chrome, Playwright 1.62.1 | Passed |
| Workspace Node state/navigation checks | Passed |
| Helm 3.19.0 suite | 51 passed; covers the 47 Helm skips from the general suite |
| `helm lint` | Passed; informational icon recommendation only |
| Real 2.4 → 2.5 upgrade, SQLite and PostgreSQL | Both passed |
| Python compilation, schema checks, templates | Passed |
| Complete OpenAPI 3.0.3 validation and SLO examples | Passed |
| Ruff for OpenAPI/contract changes, duplicate test check, documentation links/front matter, workflow YAML, `git diff --check` | Passed |

The PostgreSQL follow-up reran the affected tests with UTF-8 enabled and a writable
temporary directory. It also used the corrected activity test, which checks the
built specification rather than source formatting. Those failures/errors cleared.
Two initial failures require POSIX/Linux (container bootstrap and file mode 0600);
the remaining functional failure was the race fixed on 28 October below. The
initial PostgreSQL run remains a historical failing run.

## Resolve/reopen blocker fixed — 28 October 2026

The original regression test reproduced `TimeoutError` before the fix. A manual
resolve previously waited for an uncommitted reopen's row lock and could then
resolve its new occurrence. It now returns without a write when it observes an
already resolved or merged group. Active groups still acquire the row lock and
recheck their state before writing, so simultaneous resolves remain idempotent.

Follow-up results on Python 3.12.10 / Windows:

| Check | Result |
|---|---|
| PostgreSQL 16.15: alerts, PostgreSQL-specific, incidents, notifications, notifiers | 748 passed, 1 failed, 0 skipped |
| PostgreSQL smoke retry with its expected database name | 1 passed, 0 failed, 0 skipped |
| SQLite: alerts, incidents, notifications, notifiers | 737 passed, 0 failed, 0 skipped |
| Ruff for changed Python files, Python syntax, duplicate tests, `git diff --check` | Passed |

The only PostgreSQL failure was the connection smoke test's hard-coded expectation
of database name `incidentrelay_test`; the main run used the isolated database
`incidentrelay_resolve_reopen_test`. The unchanged smoke test passed when rerun
against the disposable database with its expected name. No functional failures
remain in these suites.

The tests cover both committed and rolled-back reopen, a fresh resolve after
reopen commits, simultaneous manual resolves with one event/audit/message update,
and rollback plus retry when event or audit persistence fails. Existing recovery
delivery/reopen and Incident concurrency checks also pass. These are targeted
regression suites; the full release suite was not rerun in this follow-up.

Run against a disposable database using its test configuration:

```sh
pytest tests/alerts tests/postgresql tests/incidents tests/notifications tests/notifiers \
  -o 'norecursedirs=.git .venv .tmp __pycache__' -q
```

For SQLite, omit `tests/postgresql`. The original regression remains at
`tests/postgresql/test_alert_reopen_concurrency.py::test_manual_resolve_during_uncommitted_reopen_is_noop`,
now parameterized for commit and rollback.

## Upgrade evidence and platform limits

The upgrade source was verified against release 2.4 commit
`21ea27d92927242ed499b7584a276f47cb1c68cd`, allowing Git line-ending normalization.
For each legacy table, five rows produced one retained row, one merged row,
two unmapped skips and one ambiguous skip on both databases. Technical comments,
notification flags, merge history, new inserts/sequence state and a second no-op
migration run were checked. Both upgraded schemas match the current models.

The 78 general-suite skips comprise 47 Helm checks (subsequently passed), the
browser check (subsequently passed), one PostgreSQL-only assertion (covered on
PostgreSQL), and 29 Linux container checks. Ten POSIX multiprocess metrics tests
were excluded from collection; the two deselected tests also require POSIX/Linux.
An import-only `fcntl` shim allowed Windows to load the application; it does not
validate POSIX locking. These checks still require Linux CI.

The temporary PostgreSQL server used loopback only. WAL synchronization/fsync were
disabled for test speed; these runs validate SQL transactions and concurrency,
not persistence across an OS crash or power loss. The server was stopped after
verification. The supported Python 3.10–3.14 Linux matrix and actual container
startup were not run locally. The updated CI includes PostgreSQL-specific tests
and a Chromium workspace run on Python 3.12; it has not been dispatched for these
uncommitted files.
