"""Cut over legacy AlertGroup participants to canonical Incident ownership (2.5).

No dual-write or compatibility models are created. Historical technical AlertGroup
comments are NOT migrated or modified. Preflight counts are printed, including
records whose mapping is ambiguous; keep a database backup before upgrading.
"""
import json

from app.db import init_database
from app.modules.db.models import IncidentResponder, IncidentStakeholder, IncidentAlertGroupLink


def _table_columns(db, table):
    return {column.name for column in db.get_columns(table)} if db.table_exists(table) else set()


def _legacy_rows(db, table):
    if "group_id" not in _table_columns(db, table):
        return []
    cursor = db.execute_sql('SELECT * FROM "' + table + '"')
    columns = [value[0] for value in cursor.description]
    return [dict(zip(columns, values)) for values in cursor.fetchall()]


def _mapping(db):
    if not db.table_exists("incident_alert_group_link"):
        return {}
    groups = {}
    for link in IncidentAlertGroupLink.select().where(IncidentAlertGroupLink.removed_at.is_null(True)):
        groups.setdefault(link.alert_group_id, set()).add(link.incident_id)
    return {group_id: next(iter(incidents)) for group_id, incidents in groups.items()
            if len(incidents) == 1}


def _convert(model, row, incident_id):
    # Peewee ForeignKeyField.attr_name is the SQL column (user_id), while
    # model.create accepts field names (user). A blind filter drops FK data.
    fields = {field.column_name: name for name, field in model._meta.fields.items()}
    values = {fields[column]: value for column, value in row.items()
              if column in fields and column != "id"}
    values["incident"] = incident_id
    if model is IncidentResponder:
        values["role"] = "responder"
    return values


def upgrade():
    db = init_database()
    responder_columns = _table_columns(db, "incident_responder")
    stakeholder_columns = _table_columns(db, "incident_stakeholder")
    if "incident_id" in responder_columns and "incident_id" in stakeholder_columns:
        return {"already_applied": True}
    if "incident_id" in responder_columns or "incident_id" in stakeholder_columns:
        raise RuntimeError("Incomplete 2.5 collaboration migration: restore a backup")

    raw_responders = _legacy_rows(db, "incident_responder")
    raw_stakeholders = _legacy_rows(db, "incident_stakeholder")
    mapping = _mapping(db)
    transferable = (
        (IncidentResponder, raw_responders, "responders"),
        (IncidentStakeholder, raw_stakeholders, "stakeholders"),
    )
    report = {"legacy_responders": len(raw_responders),
              "legacy_stakeholders": len(raw_stakeholders),
              "migrated_responders": 0,
              "migrated_stakeholders": 0,
              "unmapped_responders": sum(x.get("group_id") not in mapping for x in raw_responders),
              "unmapped_stakeholders": sum(x.get("group_id") not in mapping for x in raw_stakeholders)}
    print("2.5 collaboration migration preflight: " + json.dumps(report, sort_keys=True))

    # The 2.5 migration has never run; table replacement is transactional.
    # The old relation data is intentionally not preserved when mapping is
    # ambiguous, as decided by the breaking collaboration ownership cutover.
    with db.atomic():
        db.execute_sql('DROP TABLE IF EXISTS "incident_responder"')
        db.execute_sql('DROP TABLE IF EXISTS "incident_stakeholder"')
        db.create_tables([IncidentResponder, IncidentStakeholder], safe=False)
        for model, rows, key in transferable:
            for row in rows:
                incident_id = mapping.get(row.get("group_id"))
                if incident_id is None:
                    continue
                model.create(**_convert(model, row, incident_id))
                report["migrated_" + key] += 1
        db.execute_sql('CREATE UNIQUE INDEX IF NOT EXISTS "incident_responder_unique_commander" '
                       'ON "incident_responder" ("incident_id") '
                       "WHERE role = 'commander' AND status = 'accepted'")
        db.execute_sql('CREATE UNIQUE INDEX IF NOT EXISTS "incident_responder_unique_active_user_role" '
                       'ON "incident_responder" ("incident_id", "target_user_id", "role") '
                       "WHERE status = 'accepted' AND target_user_id IS NOT NULL")

    print("2.5 collaboration migration reconciliation: " + json.dumps(report, sort_keys=True))
    return report


def downgrade():
    raise RuntimeError("2.5 collaboration cutover is irreversible; restore database backup")
