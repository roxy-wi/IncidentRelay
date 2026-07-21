"""Introduce alert groups as primary incident objects."""

from peewee import IntegerField

from app.db import init_database
from app.migrations.introspection import (
    get_columns as migration_get_columns,
)
from app.modules.db.migrator import get_migrator
from app.modules.db.models import (
    Alert,
    AlertEvent,
    AlertGroup,
    AlertGroupMerge,
    AlertNotification,
)

from playhouse.migrate import migrate


db = init_database()
migrator = get_migrator(db)


def _has_column(table_name, column_name):
    return any(column.name == column_name for column in migration_get_columns(db, table_name))


def _create_index(table_name, index_name, columns):
    db.execute_sql(
        f"""
        CREATE INDEX IF NOT EXISTS {index_name}
        ON {table_name} ({columns})
        """
    )


def upgrade():
    db.create_tables([AlertGroup, AlertGroupMerge], safe=True)

    operations = []

    alert_table = Alert._meta.table_name
    event_table = AlertEvent._meta.table_name
    notification_table = AlertNotification._meta.table_name

    if not _has_column(alert_table, "group_id"):
        operations.append(
            migrator.add_column(
                alert_table,
                "group_id",
                IntegerField(null=True),
            )
        )

    if not _has_column(event_table, "group_id"):
        operations.append(
            migrator.add_column(
                event_table,
                "group_id",
                IntegerField(null=True),
            )
        )

    if not _has_column(notification_table, "group_id"):
        operations.append(
            migrator.add_column(
                notification_table,
                "group_id",
                IntegerField(null=True),
            )
        )

    if operations:
        migrate(*operations)

    _create_index(alert_table, "idx_alert_group_id", "group_id")
    _create_index(event_table, "idx_alert_event_group_id", "group_id")
    _create_index(notification_table, "idx_alert_notification_group_id", "group_id")

    _create_index("alert_group", "idx_alert_group_team_status", "team_id, status")
    _create_index("alert_group", "idx_alert_group_source_key_status", "source, group_key_hash, status")
    _create_index("alert_group", "idx_alert_group_route_status", "route_id, status")
    _create_index("alert_group", "idx_alert_group_service_status", "service_id, status")


def downgrade():
    db.drop_tables([AlertGroupMerge, AlertGroup], safe=True)
