"""Add service owner notification defaults."""

from peewee import BooleanField
from playhouse.migrate import migrate

from app.db import init_database
from app.modules.db.migrator import get_migrator
from app.modules.db.models import ServiceOwner


db = init_database()
migrator = get_migrator(db)


def table_has_column(table_name, column_name):
    return any(
        column.name == column_name
        for column in db.get_columns(table_name)
    )


def add_boolean_column_if_missing(table_name, column_name, default=True):
    if table_has_column(table_name, column_name):
        return

    migrate(
        migrator.add_column(
            table_name,
            column_name,
            BooleanField(default=default),
        )
    )


def drop_column_if_exists(table_name, column_name):
    if not table_has_column(table_name, column_name):
        return

    migrate(
        migrator.drop_column(
            table_name,
            column_name,
        )
    )


def upgrade():
    table_name = ServiceOwner._meta.table_name

    add_boolean_column_if_missing(
        table_name,
        "notify_on_created",
        default=True,
    )
    add_boolean_column_if_missing(
        table_name,
        "notify_on_priority_change",
        default=True,
    )
    add_boolean_column_if_missing(
        table_name,
        "notify_on_status_change",
        default=True,
    )
    add_boolean_column_if_missing(
        table_name,
        "notify_on_resolved",
        default=True,
    )


def downgrade():
    table_name = ServiceOwner._meta.table_name

    drop_column_if_exists(table_name, "notify_on_resolved")
    drop_column_if_exists(table_name, "notify_on_status_change")
    drop_column_if_exists(table_name, "notify_on_priority_change")
    drop_column_if_exists(table_name, "notify_on_created")
