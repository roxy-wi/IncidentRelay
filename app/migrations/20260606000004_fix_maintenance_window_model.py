from app.db import database_proxy as db
from app.migrations.introspection import (
    get_columns as migration_get_columns,
)


def _database():
    return getattr(db, "obj", db)


def _is_postgres():
    return "postgres" in _database().__class__.__name__.lower()


def _is_sqlite():
    return "sqlite" in _database().__class__.__name__.lower()


def _has_column(table_name, column_name):
    return any(
        column.name == column_name
        for column in migration_get_columns(db, table_name)
    )


def _add_column_if_missing(table_name, column_name, column_sql):
    if _has_column(table_name, column_name):
        return

    if _is_postgres():
        db.execute_sql(
            f'ALTER TABLE "{table_name}" '
            f'ADD COLUMN IF NOT EXISTS "{column_name}" {column_sql}'
        )
        return

    db.execute_sql(
        f'ALTER TABLE "{table_name}" '
        f'ADD COLUMN "{column_name}" {column_sql}'
    )


def _drop_column_if_exists(table_name, column_name):
    if not _has_column(table_name, column_name):
        return

    if _is_postgres():
        db.execute_sql(
            f'ALTER TABLE "{table_name}" '
            f'DROP COLUMN IF EXISTS "{column_name}" CASCADE'
        )
        return

    # SQLite in current test env usually supports DROP COLUMN.
    db.execute_sql(
        f'ALTER TABLE "{table_name}" '
        f'DROP COLUMN "{column_name}"'
    )


def _create_index_safe(table_name, column_name, index_name):
    db.execute_sql(
        f'CREATE INDEX IF NOT EXISTS "{index_name}" '
        f'ON "{table_name}" ("{column_name}")'
    )


def _copy_recurrence_to_rrule():
    if not _has_column("maintenance_window", "recurrence"):
        return

    db.execute_sql(
        """
        UPDATE maintenance_window
        SET rrule = recurrence
        WHERE rrule IS NULL
          AND recurrence IS NOT NULL
        """
    )


def upgrade():
    _add_column_if_missing(
        "maintenance_window",
        "rrule",
        "TEXT NULL",
    )
    _add_column_if_missing(
        "maintenance_window",
        "cancelled_by_id",
        "INTEGER NULL",
    )
    _add_column_if_missing(
        "maintenance_window",
        "cancelled_at",
        "TIMESTAMP NULL",
    )
    _add_column_if_missing(
        "maintenance_window",
        "cancel_reason",
        "TEXT NULL",
    )

    _copy_recurrence_to_rrule()

    _create_index_safe(
        "maintenance_window",
        "behavior",
        "maintenance_window_behavior_idx",
    )
    _create_index_safe(
        "maintenance_window",
        "enabled",
        "maintenance_window_enabled_idx",
    )
    _create_index_safe(
        "maintenance_window",
        "starts_at",
        "maintenance_window_starts_at_idx",
    )
    _create_index_safe(
        "maintenance_window",
        "ends_at",
        "maintenance_window_ends_at_idx",
    )

    # Эти колонки были ошибочно добавлены в link-таблицу.
    # Если хочешь оставить старую таблицу без чистки — можно удалить блок ниже.
    for column_name in (
        "behavior",
        "timezone",
        "rrule",
        "created_by_id",
        "cancelled_by_id",
        "cancelled_at",
        "cancel_reason",
        "updated_at",
    ):
        _drop_column_if_exists(
            "maintenance_window_service",
            column_name,
        )


def downgrade():
    pass
