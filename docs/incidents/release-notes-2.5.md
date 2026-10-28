---
title: IncidentRelay 2.5 release notes
description: Collaboration cutover, API changes and release verification gates.
---

# IncidentRelay 2.5

These notes describe the release candidate. Passing local checks does not replace
the Linux/Python CI matrix.

## Delivered behavior

- Incident owns commander/responders, stakeholders, its ServiceOwner snapshot,
  operational comments, root cause and resolution summary.
- The workspace combines attributed operational and authorized technical activity,
  preserves technical comments in AlertGroup, and exposes affected services,
  runbooks, links, readable dependencies and aggregate impact.
- Incident updates use `row_version`; participant and responder state changes are
  atomic with their history/audit records. The UI retains an edit when `409`
  requires reloading and reconciling the current record.
- Notification delivery has durable per-event/channel/recipient state, bounded
  retries, recovery of abandoned claims and duplicate suppression. See the
  [at-least-once boundary](stakeholders.md#delivery-and-retries).

`PATCH /api/incidents/<id>` accepts `root_cause` and `resolution_summary` (nullable,
up to 10,000 characters each) alongside the current `row_version`. The OpenAPI
schema documents collaboration requests, response records, limits and conflicts.
In PATCH requests, `null` leaves these fields unchanged; an empty string clears
`root_cause` or `resolution_summary`.

## Compatibility decision

The current code removes `/api/alert-groups/<id>/responders` and
`/api/alert-groups/<id>/stakeholders` (including item routes) and replaces their
storage with Incident ownership during the 2.5 migration. Integrations must use
the corresponding `/api/incidents/<incident_id>/...` routes and real Incident IDs.
There is no automatic identifier alias or forwarding compatibility layer.

**Approved for 2.5: this is a breaking API and storage change.** The earlier
2.9 cleanup schedule is superseded for responder/stakeholder routes and storage.
The local architecture roadmap now reflects this decision.

The migration intentionally skips records without one unambiguous Incident.
Keep a verified pre-upgrade backup; skipped records do not remain in the new
tables. See the [upgrade and rollback procedure](collaboration-migration-2.5.md).

## Release checks

Run in disposable databases with `INCIDENTRELAY_CONFIG_FILE` explicitly set:

```sh
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m compileall -q app manage.py run.py
python manage.py migrate
python -m app.check_schema
python -m app.check_templates
python tools/check_duplicate_tests.py
pytest --cov=app --cov-branch --cov-fail-under=50
```

Repeat migrations, schema checks and the suite on PostgreSQL 16 using a separate
configuration. Include the PostgreSQL-specific directory excluded by the default
configuration:

```sh
pytest tests -o 'norecursedirs=.git .venv .tmp __pycache__'
```

Rehearse an upgrade from the released 2.4 schema with representative linked,
unmapped, ambiguous and duplicate legacy records. Verify reconciliation counts,
unchanged technical comments, new inserts after retained IDs and a second
no-op migration run. Unit fixtures alone do not substitute for that rehearsal.

Run the workspace browser suite with Node/Playwright and Chromium installed:

```sh
INCIDENTRELAY_BROWSER_TESTS=1 pytest tests/ux/test_incident_workspace_browser.py
```

Check add/remove operations, comments, `409` draft preservation, navigation,
reopening, viewer permissions, language switching, narrow screens and UTC/DST
display. Linux-only multiprocess metrics and container entrypoint checks must
pass on Linux; Windows skips or import shims are not evidence for those checks.

Before release, require green SQLite/PostgreSQL checks, the supported Python
matrix and successful upgrade rehearsal.

[Local release validation results](release-validation-2.5.md).
