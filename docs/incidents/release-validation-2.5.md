---
title: IncidentRelay 2.5 release validation
description: Local release candidate checks on 27 October 2026 and remaining release gates.
---

# Release validation — 27 October 2026

**Release is blocked by the PostgreSQL resolve/reopen regression below.**
The documentation and OpenAPI update is complete. Legacy AlertGroup responder and
stakeholder API/storage removal is approved as a 2.5 breaking change.

The checks used `7738f25` plus the uncommitted workspace and documentation changes
on `release/2.5.0`. No commit or push was made. Application databases were tested
in isolated copies, not in the development checkout.

## Results

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
the remaining functional failure is the race below. Do not describe the initial
PostgreSQL run as green.

## Reproducible blocker

`tests/postgresql/test_alert_reopen_concurrency.py::test_manual_resolve_during_uncommitted_reopen_is_noop`
fails with `TimeoutError` at `resolving.result(timeout=15)`. It failed in both the
PostgreSQL-specific run and the full run; the other nine PostgreSQL-specific tests
passed. The scenario expects a manual resolve observing the old resolved state
to finish as a no-op while a new occurrence is still uncommitted. The current
resolve path waits for the AlertGroup row lock.

Reproduce in a disposable PostgreSQL test database with the test configuration:

```sh
pytest tests/postgresql/test_alert_reopen_concurrency.py::test_manual_resolve_during_uncommitted_reopen_is_noop -vv
```

Resolve the concurrency contract and rerun this test before releasing. Application
lifecycle behavior was not changed as part of the documentation step.

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
