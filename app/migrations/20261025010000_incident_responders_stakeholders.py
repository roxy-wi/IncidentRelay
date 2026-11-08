"""Move unambiguously mapped collaboration records to Incident ownership.

Stop application writers and back up the database before upgrading. Unmapped
and ambiguous records are skipped; technical AlertGroup comments stay intact.
"""

import json

from peewee import SqliteDatabase

from app.db import init_database
from app.migrations.introspection import get_columns, is_postgres, table_exists
from app.modules.db.models import (
    IncidentAlertGroupLink, IncidentEvent, IncidentResponder, IncidentStakeholder,
)

NOTIFICATION_FLAGS = (
    "notify_on_created", "notify_on_priority_change", "notify_on_status_change",
    "notify_on_resolved", "notify_on_comment",
)


def _table_columns(db, table):
    if not table_exists(db, table):
        return set()
    return {column.name for column in get_columns(db, table)}


def _legacy_rows(db, table):
    if not table_exists(db, table):
        return []
    cursor = db.execute_sql(f'SELECT * FROM "{table}" ORDER BY "id"')
    columns = [value[0] for value in cursor.description]
    return [dict(zip(columns, values, strict=True)) for values in cursor.fetchall()]


def _mapping(db):
    groups = {}
    if table_exists(db, "incident_alert_group_link"):
        for link in IncidentAlertGroupLink.select().where(
            IncidentAlertGroupLink.removed_at.is_null(True)
        ):
            groups.setdefault(link.alert_group_id, set()).add(link.incident_id)
    return groups


def _convert(model, row, incident_id):
    # Keep IDs, actor references and timestamps for records surviving merging.
    fields = {field.column_name: name for name, field in model._meta.fields.items()}
    values = {
        fields[column]: value for column, value in row.items() if column in fields
    }
    values["incident"] = incident_id
    if model is IncidentResponder:
        values["role"] = "responder"
        if (values.get("status") == "accepted"
                and values.get("target_type") != "user"):
            values["target_user"] = values.get("accepted_by")
    elif values.get("email"):
        values["email"] = values["email"].strip().lower()
    return values


def _duplicate_key(model, values):
    if model is IncidentResponder:
        if values.get("status") == "accepted" and values.get("target_user"):
            return values["incident"], values["target_user"], values["role"]
    else:
        recipient = ("user", values["user"]) if values.get("user") else (
            "email", values.get("email")
        )
        if recipient[1]:
            return values["incident"], recipient, values.get("role", "stakeholder")
    return None


def _merge_history(model, row, values, canonical_id):
    """Keep the operational provenance of a merged record."""
    data = {
        "legacy_table": model._meta.table_name, "legacy_id": row["id"],
        "alert_group_id": row["group_id"], "canonical_id": canonical_id,
        "role": values.get("role", "stakeholder"),
    }
    for name in (
        "status", "source", "target_type", "target_user", "target_team",
        "target_rotation", "target_escalation_policy", "requested_by",
        "accepted_by", "declined_by", "requested_at", "responded_at",
        "expires_at", "created_at", "updated_at", "created_by", "active",
        "notification_status", "message", *NOTIFICATION_FLAGS,
    ):
        if name in values:
            value = values[name]
            data[name] = value.isoformat() if hasattr(value, "isoformat") else value
    IncidentEvent.create(
        incident=values["incident"], event_type="collaboration_record_merged",
        user=values.get("requested_by") or values.get("created_by"),
        message=values.get("response_message"), data=data,
    )


def _create_indexes(db):
    db.execute_sql(
        'CREATE UNIQUE INDEX IF NOT EXISTS "incident_responder_unique_commander" '
        'ON "incident_responder" ("incident_id") '
        "WHERE role = 'commander' AND status = 'accepted'"
    )
    db.execute_sql(
        'CREATE UNIQUE INDEX IF NOT EXISTS "incident_responder_unique_active_user_role" '
        'ON "incident_responder" ("incident_id", "target_user_id", "role") '
        "WHERE status = 'accepted' AND target_user_id IS NOT NULL"
    )


def upgrade():
    """Replace both tables, records and indexes in a single transaction."""
    db = init_database()
    if not isinstance(db, SqliteDatabase) and not is_postgres(db):
        raise RuntimeError(
            "2.5 collaboration migration requires SQLite or PostgreSQL; "
            "no tables were changed"
        )
    with db.atomic():
        columns = [_table_columns(db, model._meta.table_name)
                   for model in (IncidentResponder, IncidentStakeholder)]
        if any({"incident_id", "group_id"} <= names for names in columns):
            raise RuntimeError("Mixed collaboration ownership: restore a backup")
        if all("incident_id" in names for names in columns):
            _create_indexes(db)
            return {"already_applied": True}
        if any("incident_id" in names for names in columns):
            raise RuntimeError("Incomplete 2.5 collaboration migration: restore a backup")
        if any(names and "group_id" not in names for names in columns):
            raise RuntimeError(
                "Unknown legacy collaboration schema; tables were not replaced"
            )

        groups = _mapping(db)
        report = {}
        batches = []
        for model, key in ((IncidentResponder, "responders"),
                           (IncidentStakeholder, "stakeholders")):
            rows = _legacy_rows(db, model._meta.table_name)
            report.update({
                f"legacy_{key}": len(rows), f"migrated_{key}": 0,
                f"merged_{key}": 0, f"unmapped_{key}": 0, f"ambiguous_{key}": 0,
            })
            mapped = []
            for row in rows:
                incidents = groups.get(row["group_id"], set())
                if len(incidents) != 1:
                    reason = "ambiguous" if incidents else "unmapped"
                    report[f"{reason}_{key}"] += 1
                    continue
                mapped.append((row, _convert(model, row, next(iter(incidents)))))
            batches.append((model, key, mapped))
            report[f"eligible_{key}"] = len(mapped)
        print("2.5 collaboration migration preflight: " + json.dumps(report, sort_keys=True))

        db.drop_tables([IncidentResponder, IncidentStakeholder], safe=True)
        db.create_tables([IncidentResponder, IncidentStakeholder], safe=False)
        for model, key, rows in batches:
            seen = {}
            for row, values in rows:
                identity = _duplicate_key(model, values)
                existing = seen.get(identity) if identity is not None else None
                if existing is not None:
                    if model is IncidentStakeholder:
                        incoming_active = values.get("active", True)
                        for flag in NOTIFICATION_FLAGS:
                            incoming = values.get(flag, True)
                            if incoming_active and not existing.active:
                                setattr(existing, flag, incoming)
                            elif incoming_active or not existing.active:
                                setattr(existing, flag, bool(incoming or getattr(existing, flag)))
                        existing.active = existing.active or incoming_active
                        existing.save()
                    _merge_history(model, row, values, existing.id)
                    report[f"merged_{key}"] += 1
                else:
                    created = model.create(**values)
                    if identity is not None:
                        seen[identity] = created
                    report[f"migrated_{key}"] += 1
            if is_postgres(db):
                # Explicit legacy IDs do not advance PostgreSQL sequences.
                table = model._meta.table_name
                db.execute_sql(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f'COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM "{table}"'
                )
        _create_indexes(db)

    print("2.5 collaboration migration reconciliation: " + json.dumps(report, sort_keys=True))
    return report


def downgrade():
    """Require a backup restore for this ownership cutover."""
    raise RuntimeError("2.5 collaboration cutover is irreversible; restore database backup")
