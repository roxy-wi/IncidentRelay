---
title: IncidentRelay 2.5 collaboration migration
description: Mapping, duplicate handling, reconciliation and recovery for the 2.4 to 2.5 collaboration cutover.
---

# IncidentRelay 2.5 collaboration migration

Migration `20261025010000_incident_responders_stakeholders` changes the owner of
responder requests and stakeholder subscriptions from AlertGroup to Incident.
It supports SQLite and PostgreSQL. Other backends are rejected before replacing
tables because this operation requires transactional DDL and partial indexes.

## Transfer rules

- An AlertGroup must have active links (`removed_at IS NULL`) to exactly one
  distinct Incident. Repeated links to that same Incident are unambiguous.
- Records without such a link are skipped. Links to multiple distinct Incidents
  are ambiguous and their records are also skipped. No Incident is synthesized.
- IDs, actor references, status, text and timestamps of retained records survive
  the transfer. PostgreSQL sequences advance past the retained IDs.
- Accepted responder requests for the same Incident, concrete user and role
  become one assignment. The row with the smallest legacy ID is retained. Other
  request statuses stay separate. Legacy requests receive the `responder` role.
- For an accepted team, rotation or escalation-policy request, `accepted_by`
  identifies the concrete assignee; the original target fields remain intact.
  If the accepting user is unknown, the migration does not invent one.
- Stakeholder duplicates are identified by Incident, recipient and role. User
  ID takes precedence over email; email-only identities are trimmed and compared
  case-insensitively. Distinct roles remain separate. The smallest ID survives.
  Active duplicate subscriptions combine notification flags with logical OR.
  Inactive subscriptions do not enable flags on an active subscription; if all
  duplicates are inactive, the result remains inactive and combines their flags.
- Each merged row produces a `collaboration_record_merged` Incident event with
  its legacy ID, original AlertGroup, retained row ID and operational provenance.
  Delivery error text and recipient addresses are not copied into these events.
- AlertGroup comments are neither moved nor rewritten. Independent Incident
  collaboration tables were introduced by the preceding 2.5 migration.

## Upgrade procedure

1. Stop the web application, ingestion workers, scheduler and other database
   writers. Keep them stopped until verification is complete.
2. Make and verify a complete backup using the database's supported backup
   mechanism. For SQLite, do not copy only the main file while WAL writes are
   possible. Confirm that the backup can be restored to a separate database.
3. First rehearse the upgrade on that separate copy. Point
   `INCIDENTRELAY_CONFIG_FILE` at its configuration before running any command.
4. Run `python manage.py migrate`, then `python -m app.check_schema`.
   Capture the migration's `preflight` and `reconciliation` JSON reports.
5. For each suffix (`responders`, `stakeholders`), check:

   ```text
   legacy = migrated + merged + unmapped + ambiguous
   eligible = migrated + merged
   ```

   `legacy` is the number read, `eligible` is the number with a unique mapping,
   `migrated` counts retained rows, and `merged` counts duplicate rows represented
   by those retained rows and history events. `unmapped` and `ambiguous` count
   intentionally skipped rows. Before replacement, the preflight report has zero
   `migrated` and `merged` counts; the final report contains the actual totals.
6. Inspect representative participants, subscriptions and unchanged technical
   comments. Verify that a new participant can be created after the transfer.
7. After a successful rehearsal, repeat with a fresh production backup and the
   production configuration, then resume application processes.

## Failure and rollback

Reading, conversion, replacement, history events and unique-index creation run
in one database transaction. A failure restores the old tables and records.
Correct the cause before retrying; do not manually mark a failed migration as
applied. Logs contain counts rather than request text or recipient addresses.

An already canonical schema can be checked again without moving rows or creating
more history; missing uniqueness indexes are recreated. A partially converted,
mixed or unrecognized schema is rejected rather than overwritten.

The migration runner does not rerun migrations recorded as applied. If an earlier
development build of 2.5 already applied this migration, changing its source is
not a repair of that database: restore the verified 2.4 backup before rehearsing
the corrected cutover.

After a committed cutover, downgrade requires restoring the complete pre-upgrade
database backup and matching application version while all writers are stopped.
Skipped legacy rows cannot be recovered from the migrated database.
