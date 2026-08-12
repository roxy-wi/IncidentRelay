"""Add retroactive maintenance lifecycle settings and application tracking."""

from peewee import BooleanField, DateTimeField
from playhouse.migrate import migrate

from app.db import init_database
from app.migrations.introspection import get_columns as migration_get_columns
from app.modules.db.migrator import get_migrator
from app.modules.db.models import (
    MaintenanceWindow,
    MaintenanceWindowAlertApplication,
)


db = init_database()
migrator = get_migrator(db)


def _has_column(table_name: str, column_name: str) -> bool:
    return any(
        column.name == column_name
        for column in migration_get_columns(db, table_name)
    )


def upgrade():
    """Add per-window lifecycle flags and the applied-effects table."""
    table_name = MaintenanceWindow._meta.table_name
    operations = []

    if not _has_column(table_name, "apply_to_existing"):
        operations.append(
            migrator.add_column(
                table_name,
                "apply_to_existing",
                BooleanField(default=False),
            )
        )

    if not _has_column(table_name, "reactivate_on_end"):
        operations.append(
            migrator.add_column(
                table_name,
                "reactivate_on_end",
                BooleanField(default=True),
            )
        )

    if not _has_column(table_name, "reconciled_at"):
        operations.append(
            migrator.add_column(
                table_name,
                "reconciled_at",
                DateTimeField(null=True),
            )
        )

    if operations:
        migrate(*operations)

    db.create_tables([MaintenanceWindowAlertApplication], safe=True)


def downgrade():
    """Remove retroactive maintenance lifecycle storage."""
    db.drop_tables([MaintenanceWindowAlertApplication], safe=True)

    table_name = MaintenanceWindow._meta.table_name
    operations = []
    for column_name in ("reconciled_at", "reactivate_on_end", "apply_to_existing"):
        if _has_column(table_name, column_name):
            operations.append(migrator.drop_column(table_name, column_name))

    if operations:
        migrate(*operations)
