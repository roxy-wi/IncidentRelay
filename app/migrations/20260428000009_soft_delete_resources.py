from peewee import BooleanField, DateTimeField
from playhouse.migrate import migrate

from app.db import init_database
from app.modules.db.models import (
    AlertRoute,
    ApiToken,
    Group,
    NotificationChannel,
    Rotation,
    Silence,
    Team,
    User,
)
from app.modules.db.migrator import get_migrator


db = init_database()
migrator = get_migrator(db)


MODELS = [
    User,
    Group,
    Team,
    Rotation,
    NotificationChannel,
    AlertRoute,
    Silence,
    ApiToken,
]


def table_exists(table_name):
    """
    Return True when a table exists.
    """

    return table_name in db.get_tables()


def has_column(table_name, column_name):
    """
    Return True when a table already has a column.
    """

    if not table_exists(table_name):
        return False

    return any(column.name == column_name for column in db.get_columns(table_name))


def upgrade():
    """
    Add soft-delete fields to resource tables.
    """

    operations = []

    for model in MODELS:
        table_name = model._meta.table_name

        if not table_exists(table_name):
            continue

        if not has_column(table_name, "deleted"):
            operations.append(
                migrator.add_column(
                    table_name,
                    "deleted",
                    BooleanField(default=False),
                )
            )

        if not has_column(table_name, "deleted_at"):
            operations.append(
                migrator.add_column(
                    table_name,
                    "deleted_at",
                    DateTimeField(null=True),
                )
            )

    if operations:
        migrate(*operations)


def downgrade():
    """
    Remove soft-delete fields from resource tables.
    """

    operations = []

    for model in MODELS:
        table_name = model._meta.table_name

        if not table_exists(table_name):
            continue

        if has_column(table_name, "deleted_at"):
            operations.append(migrator.drop_column(table_name, "deleted_at"))

        if has_column(table_name, "deleted"):
            operations.append(migrator.drop_column(table_name, "deleted"))

    if operations:
        migrate(*operations)
