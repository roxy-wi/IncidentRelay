"""Allow group-level alert events and notifications."""

from app.db import init_database
from app.migrations.introspection import (
    get_columns as migration_get_columns,
    get_tables as migration_get_tables,
)
from app.modules.db.models import AlertEvent, AlertNotification


db = init_database()


def _is_postgres():
    name = db.__class__.__name__.lower()
    return "postgres" in name or "postgre" in name


def _table_name(model):
    return model._meta.table_name


def _has_table(table_name: str) -> bool:
    return table_name in migration_get_tables(db)


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False

    return any(column.name == column_name for column in migration_get_columns(db, table_name))


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def upgrade():
    if _is_postgres():
        _upgrade_postgres()
    else:
        _upgrade_sqlite()


def downgrade():
    # Do not restore NOT NULL.
    # Group-level events/notifications are valid without alert_id.
    pass


def _upgrade_postgres():
    event_table = _table_name(AlertEvent)
    notification_table = _table_name(AlertNotification)

    if _has_column(event_table, "alert_id"):
        db.execute_sql(
            f"""
            ALTER TABLE {_quote(event_table)}
            ALTER COLUMN alert_id DROP NOT NULL
            """
        )

    if _has_column(notification_table, "alert_id"):
        db.execute_sql(
            f"""
            ALTER TABLE {_quote(notification_table)}
            ALTER COLUMN alert_id DROP NOT NULL
            """
        )

    if _has_table(event_table) and not _has_column(event_table, "group_id"):
        db.execute_sql(
            f"""
            ALTER TABLE {_quote(event_table)}
            ADD COLUMN group_id INTEGER NULL
            """
        )

    if _has_table(notification_table) and not _has_column(notification_table, "group_id"):
        db.execute_sql(
            f"""
            ALTER TABLE {_quote(notification_table)}
            ADD COLUMN group_id INTEGER NULL
            """
        )

    if _has_table(event_table):
        db.execute_sql(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{event_table}_group_id
            ON {_quote(event_table)}(group_id)
            """
        )

    if _has_table(notification_table):
        db.execute_sql(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{notification_table}_group_id
            ON {_quote(notification_table)}(group_id)
            """
        )


def _upgrade_sqlite():
    event_table = _table_name(AlertEvent)
    notification_table = _table_name(AlertNotification)

    # SQLite cannot reliably DROP NOT NULL in-place.
    # Fresh test DBs created from updated models are fine.
    # Existing SQLite dev DBs should be recreated for this breaking change.

    if _has_table(event_table) and not _has_column(event_table, "group_id"):
        db.execute_sql(
            f"""
            ALTER TABLE "{event_table}"
            ADD COLUMN group_id INTEGER NULL
            """
        )

    if _has_table(notification_table) and not _has_column(notification_table, "group_id"):
        db.execute_sql(
            f"""
            ALTER TABLE "{notification_table}"
            ADD COLUMN group_id INTEGER NULL
            """
        )

    if _has_table(event_table):
        db.execute_sql(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{event_table}_group_id
            ON "{event_table}"(group_id)
            """
        )

    if _has_table(notification_table):
        db.execute_sql(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{notification_table}_group_id
            ON "{notification_table}"(group_id)
            """
        )
