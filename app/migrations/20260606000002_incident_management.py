"""Add incident management tables and maintenance metadata.

This migration is intentionally SQL-dialect aware because tests run on SQLite,
while production can run on PostgreSQL.
"""

from datetime import datetime

from app.db import database_proxy as db
from app.migrations.introspection import (
    get_columns as migration_get_columns,
    get_tables as migration_get_tables,
)
from app.modules.db.models import (
    IncidentPriority,
    IncidentResponder,
    IncidentStakeholder,
    MaintenanceWindowScope,
)


INCIDENT_TABLE_MODELS = [
    IncidentPriority,
    MaintenanceWindowScope,
    IncidentResponder,
    IncidentStakeholder,
]


DEFAULT_PRIORITIES = [
    ("p1", "P1", "Critical impact", 1, "#dc2626", True, False),
    ("p2", "P2", "High impact", 2, "#ea580c", True, False),
    ("p3", "P3", "Normal impact", 3, "#2563eb", True, True),
    ("p4", "P4", "Low impact", 4, "#64748b", True, False),
    ("p5", "P5", "Informational", 5, "#94a3b8", True, False),
]


def _database():
    return db.obj


def _is_sqlite():
    return _database().__class__.__name__.lower().startswith("sqlite")


def _is_postgres():
    name = _database().__class__.__name__.lower()
    return "postgres" in name or "cockroach" in name


def _placeholder():
    if _is_sqlite():
        return "?"

    return "%" + "s"


def _bool_value(value):
    if _is_sqlite():
        return 1 if value else 0

    return bool(value)


def _bool_column(default=False, not_null=True):
    if _is_sqlite():
        parts = ["INTEGER"]

        if not_null:
            parts.append("NOT NULL")

        parts.append("DEFAULT")
        parts.append("1" if default else "0")

        return " ".join(parts)

    parts = ["BOOLEAN"]

    if not_null:
        parts.append("NOT NULL")

    parts.append("DEFAULT")
    parts.append("TRUE" if default else "FALSE")

    return " ".join(parts)


def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _execute(sql, params=None):
    return db.execute_sql(sql, params or ())


def _table_exists(table_name):
    return table_name in migration_get_tables(_database())


def _column_exists(table_name, column_name):
    if not _table_exists(table_name):
        return False

    return any(column.name == column_name for column in migration_get_columns(_database(), table_name))


def _add_column_if_missing(table_name, column_name, column_definition):
    if not _table_exists(table_name):
        return

    if _column_exists(table_name, column_name):
        return

    _execute(
        "ALTER TABLE {table} ADD COLUMN {column} {definition}".format(
            table=_quote(table_name),
            column=_quote(column_name),
            definition=column_definition,
        )
    )


def _drop_column_if_exists(table_name, column_name):
    if not _table_exists(table_name):
        return

    if not _column_exists(table_name, column_name):
        return

    try:
        _execute(
            "ALTER TABLE {table} DROP COLUMN {column}".format(
                table=_quote(table_name),
                column=_quote(column_name),
            )
        )
    except Exception:
        # Older SQLite versions cannot drop columns safely.
        pass


def _drop_table_if_exists(table_name):
    if not _table_exists(table_name):
        return

    suffix = " CASCADE" if _is_postgres() else ""

    _execute(
        "DROP TABLE IF EXISTS {table}{suffix}".format(
            table=_quote(table_name),
            suffix=suffix,
        )
    )


def _create_index_if_missing(index_name, table_name, column_names):
    if not _table_exists(table_name):
        return

    for column_name in column_names:
        if not _column_exists(table_name, column_name):
            return

    columns_sql = ", ".join(_quote(column_name) for column_name in column_names)

    _execute(
        "CREATE INDEX IF NOT EXISTS {index} ON {table} ({columns})".format(
            index=_quote(index_name),
            table=_quote(table_name),
            columns=columns_sql,
        )
    )


def _add_alert_group_columns():
    _add_column_if_missing("alert_group", "priority_id", "INTEGER NULL")
    _add_column_if_missing(
        "alert_group",
        "priority_slug",
        "VARCHAR(32) NOT NULL DEFAULT 'p3'",
    )
    _add_column_if_missing(
        "alert_group",
        "priority_order",
        "INTEGER NOT NULL DEFAULT 3",
    )
    _add_column_if_missing(
        "alert_group",
        "priority_set_manually",
        _bool_column(default=False, not_null=True),
    )
    _add_column_if_missing("alert_group", "priority_set_by_id", "INTEGER NULL")
    _add_column_if_missing("alert_group", "priority_set_at", "DATETIME NULL")

    _add_column_if_missing("alert_group", "maintenance_window_id", "INTEGER NULL")
    _add_column_if_missing(
        "alert_group",
        "maintenance_behavior",
        "VARCHAR(64) NULL",
    )
    _add_column_if_missing(
        "alert_group",
        "maintenance_suppressed",
        _bool_column(default=False, not_null=True),
    )


def _add_alert_columns():
    _add_column_if_missing("alert", "priority_id", "INTEGER NULL")
    _add_column_if_missing(
        "alert",
        "priority_slug",
        "VARCHAR(32) NOT NULL DEFAULT 'p3'",
    )
    _add_column_if_missing(
        "alert",
        "priority_order",
        "INTEGER NOT NULL DEFAULT 3",
    )

    _add_column_if_missing("alert", "maintenance_window_id", "INTEGER NULL")
    _add_column_if_missing(
        "alert",
        "maintenance_behavior",
        "VARCHAR(64) NULL",
    )
    _add_column_if_missing(
        "alert",
        "maintenance_suppressed",
        _bool_column(default=False, not_null=True),
    )


def _seed_default_priorities():
    if not _table_exists("incident_priority"):
        return

    now = datetime.utcnow()
    placeholder = _placeholder()

    select_sql = (
        "SELECT id FROM {table} WHERE {slug} = {placeholder}"
    ).format(
        table=_quote("incident_priority"),
        slug=_quote("slug"),
        placeholder=placeholder,
    )

    insert_sql = """
        INSERT INTO {table} (
            {slug},
            {name},
            {description},
            {level},
            {color},
            {enabled},
            {default_column},
            {created_at},
            {updated_at}
        )
        VALUES (
            {placeholder},
            {placeholder},
            {placeholder},
            {placeholder},
            {placeholder},
            {placeholder},
            {placeholder},
            {placeholder},
            {placeholder}
        )
    """.format(
        table=_quote("incident_priority"),
        slug=_quote("slug"),
        name=_quote("name"),
        description=_quote("description"),
        level=_quote("level"),
        color=_quote("color"),
        enabled=_quote("enabled"),
        default_column=_quote("default"),
        created_at=_quote("created_at"),
        updated_at=_quote("updated_at"),
        placeholder=placeholder,
    )

    update_sql = """
        UPDATE {table}
        SET
            {name} = {placeholder},
            {description} = {placeholder},
            {level} = {placeholder},
            {color} = {placeholder},
            {enabled} = {placeholder},
            {default_column} = {placeholder},
            {updated_at} = {placeholder}
        WHERE {slug} = {placeholder}
    """.format(
        table=_quote("incident_priority"),
        name=_quote("name"),
        description=_quote("description"),
        level=_quote("level"),
        color=_quote("color"),
        enabled=_quote("enabled"),
        default_column=_quote("default"),
        updated_at=_quote("updated_at"),
        slug=_quote("slug"),
        placeholder=placeholder,
    )

    for slug, name, description, level, color, enabled, is_default in DEFAULT_PRIORITIES:
        existing = _execute(select_sql, (slug,)).fetchone()

        if existing:
            _execute(
                update_sql,
                (
                    name,
                    description,
                    level,
                    color,
                    _bool_value(enabled),
                    _bool_value(is_default),
                    now,
                    slug,
                ),
            )
            continue

        _execute(
            insert_sql,
            (
                slug,
                name,
                description,
                level,
                color,
                _bool_value(enabled),
                _bool_value(is_default),
                now,
                now,
            ),
        )


def _get_priority_id(slug):
    if not _table_exists("incident_priority"):
        return None

    placeholder = _placeholder()

    row = _execute(
        "SELECT {id_column} FROM {table} WHERE {slug_column} = {placeholder}".format(
            id_column=_quote("id"),
            table=_quote("incident_priority"),
            slug_column=_quote("slug"),
            placeholder=placeholder,
        ),
        (slug,),
    ).fetchone()

    if not row:
        return None

    return row[0]


def _backfill_priority_columns():
    priority_id = _get_priority_id("p3")
    placeholder = _placeholder()

    for table_name in ("alert_group", "alert"):
        if not _table_exists(table_name):
            continue

        if _column_exists(table_name, "priority_slug"):
            _execute(
                """
                UPDATE {table}
                SET {priority_slug} = {placeholder}
                WHERE {priority_slug} IS NULL OR {priority_slug} = ''
                """.format(
                    table=_quote(table_name),
                    priority_slug=_quote("priority_slug"),
                    placeholder=placeholder,
                ),
                ("p3",),
            )

        if _column_exists(table_name, "priority_order"):
            _execute(
                """
                UPDATE {table}
                SET {priority_order} = 3
                WHERE {priority_order} IS NULL
                """.format(
                    table=_quote(table_name),
                    priority_order=_quote("priority_order"),
                )
            )

        if priority_id and _column_exists(table_name, "priority_id"):
            _execute(
                """
                UPDATE {table}
                SET {priority_id} = {placeholder}
                WHERE {priority_id} IS NULL
                """.format(
                    table=_quote(table_name),
                    priority_id=_quote("priority_id"),
                    placeholder=placeholder,
                ),
                (priority_id,),
            )

        if _column_exists(table_name, "maintenance_suppressed"):
            _execute(
                """
                UPDATE {table}
                SET {maintenance_suppressed} = {placeholder}
                WHERE {maintenance_suppressed} IS NULL
                """.format(
                    table=_quote(table_name),
                    maintenance_suppressed=_quote("maintenance_suppressed"),
                    placeholder=placeholder,
                ),
                (_bool_value(False),),
            )

    if _table_exists("alert_group") and _column_exists("alert_group", "priority_set_manually"):
        _execute(
            """
            UPDATE {table}
            SET {priority_set_manually} = {placeholder}
            WHERE {priority_set_manually} IS NULL
            """.format(
                table=_quote("alert_group"),
                priority_set_manually=_quote("priority_set_manually"),
                placeholder=placeholder,
            ),
            (_bool_value(False),),
        )


def _create_indexes():
    _create_index_if_missing(
        "idx_alert_group_priority_slug",
        "alert_group",
        ["priority_slug"],
    )
    _create_index_if_missing(
        "idx_alert_group_priority_order",
        "alert_group",
        ["priority_order"],
    )
    _create_index_if_missing(
        "idx_alert_group_maintenance_window",
        "alert_group",
        ["maintenance_window_id"],
    )
    _create_index_if_missing(
        "idx_alert_group_maintenance_suppressed",
        "alert_group",
        ["maintenance_suppressed"],
    )

    _create_index_if_missing(
        "idx_alert_priority_slug",
        "alert",
        ["priority_slug"],
    )
    _create_index_if_missing(
        "idx_alert_priority_order",
        "alert",
        ["priority_order"],
    )
    _create_index_if_missing(
        "idx_alert_maintenance_window",
        "alert",
        ["maintenance_window_id"],
    )
    _create_index_if_missing(
        "idx_alert_maintenance_suppressed",
        "alert",
        ["maintenance_suppressed"],
    )


def _drop_legacy_mvp_tables():
    _drop_table_if_exists("alert_group_responder")
    _drop_table_if_exists("alert_group_stakeholder")


def upgrade():
    _drop_legacy_mvp_tables()

    db.create_tables(INCIDENT_TABLE_MODELS, safe=True)

    _add_alert_group_columns()
    _add_alert_columns()
    _seed_default_priorities()
    _backfill_priority_columns()
    _create_indexes()


def downgrade():
    _drop_column_if_exists("alert", "maintenance_suppressed")
    _drop_column_if_exists("alert", "maintenance_behavior")
    _drop_column_if_exists("alert", "maintenance_window_id")
    _drop_column_if_exists("alert", "priority_order")
    _drop_column_if_exists("alert", "priority_slug")
    _drop_column_if_exists("alert", "priority_id")

    _drop_column_if_exists("alert_group", "maintenance_suppressed")
    _drop_column_if_exists("alert_group", "maintenance_behavior")
    _drop_column_if_exists("alert_group", "maintenance_window_id")
    _drop_column_if_exists("alert_group", "priority_set_at")
    _drop_column_if_exists("alert_group", "priority_set_by_id")
    _drop_column_if_exists("alert_group", "priority_set_manually")
    _drop_column_if_exists("alert_group", "priority_order")
    _drop_column_if_exists("alert_group", "priority_slug")
    _drop_column_if_exists("alert_group", "priority_id")

    db.drop_tables(
        [
            IncidentStakeholder,
            IncidentResponder,
            MaintenanceWindowScope,
            IncidentPriority,
        ],
        safe=True,
    )
    