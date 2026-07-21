"""Add delayed notification scheduling to alert groups."""

from app.db import init_database
from app.migrations.introspection import (
    get_columns as migration_get_columns,
    get_tables as migration_get_tables,
)


db = init_database()


def _is_postgres():
    name = db.__class__.__name__.lower()
    return "postgres" in name or "postgre" in name


def _has_column(table_name: str, column_name: str) -> bool:
    if table_name not in migration_get_tables(db):
        return False

    return any(column.name == column_name for column in migration_get_columns(db, table_name))


def upgrade():
    if _is_postgres():
        _upgrade_postgres()
    else:
        _upgrade_sqlite()


def downgrade():
    pass


def _upgrade_postgres():
    db.execute_sql(
        """
        ALTER TABLE alert_group
        ADD COLUMN IF NOT EXISTS notification_due_at TIMESTAMP NULL
        """
    )

    db.execute_sql(
        """
        ALTER TABLE alert_group
        ADD COLUMN IF NOT EXISTS notification_pending BOOLEAN NOT NULL DEFAULT FALSE
        """
    )

    db.execute_sql(
        """
        ALTER TABLE alert_group
        ADD COLUMN IF NOT EXISTS notification_reason VARCHAR(255) NULL
        """
    )

    db.execute_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_alert_group_notification_due
        ON alert_group(notification_pending, notification_due_at)
        """
    )


def _upgrade_sqlite():
    if not _has_column("alert_group", "notification_due_at"):
        db.execute_sql(
            """
            ALTER TABLE alert_group
            ADD COLUMN notification_due_at TIMESTAMP NULL
            """
        )

    if not _has_column("alert_group", "notification_pending"):
        db.execute_sql(
            """
            ALTER TABLE alert_group
            ADD COLUMN notification_pending INTEGER NOT NULL DEFAULT 0
            """
        )

    if not _has_column("alert_group", "notification_reason"):
        db.execute_sql(
            """
            ALTER TABLE alert_group
            ADD COLUMN notification_reason VARCHAR(255) NULL
            """
        )

    db.execute_sql(
        """
        CREATE INDEX IF NOT EXISTS idx_alert_group_notification_due
        ON alert_group(notification_pending, notification_due_at)
        """
    )
