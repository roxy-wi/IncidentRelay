"""Add manual status override fields for business services."""

from peewee import CharField, DateTimeField, IntegerField, TextField
from playhouse.migrate import SchemaMigrator, migrate

from app.db import init_database
from app.migrations.introspection import (
    get_columns as migration_get_columns,
)


db = init_database()


def _column_names(table_name):
    return {column.name for column in migration_get_columns(db, table_name)}


def _has_column(table_name, column_name):
    return column_name in _column_names(table_name)


def _add_column_if_missing(migrator, table_name, column_name, field):
    if _has_column(table_name, column_name):
        return

    migrate(
        migrator.add_column(
            table_name,
            column_name,
            field,
        )
    )


def _drop_column_if_exists(migrator, table_name, column_name):
    if not _has_column(table_name, column_name):
        return

    migrate(
        migrator.drop_column(
            table_name,
            column_name,
        )
    )


def upgrade():
    migrator = SchemaMigrator.from_database(db)

    _add_column_if_missing(
        migrator,
        "business_service",
        "manual_status",
        CharField(max_length=32, null=True),
    )

    _add_column_if_missing(
        migrator,
        "business_service",
        "manual_status_message",
        TextField(null=True),
    )

    _add_column_if_missing(
        migrator,
        "business_service",
        "manual_status_until",
        DateTimeField(null=True),
    )

    _add_column_if_missing(
        migrator,
        "business_service",
        "manual_status_set_by_id",
        IntegerField(null=True),
    )

    _add_column_if_missing(
        migrator,
        "business_service",
        "manual_status_set_at",
        DateTimeField(null=True),
    )


def downgrade():
    migrator = SchemaMigrator.from_database(db)

    for column_name in (
        "manual_status_set_at",
        "manual_status_set_by_id",
        "manual_status_until",
        "manual_status_message",
        "manual_status",
    ):
        _drop_column_if_exists(
            migrator,
            "business_service",
            column_name,
        )
