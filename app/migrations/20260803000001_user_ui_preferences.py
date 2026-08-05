"""Add user locale and theme preferences."""

from peewee import CharField
from playhouse.migrate import migrate

from app.db import init_database
from app.migrations.introspection import get_columns as migration_get_columns
from app.modules.db.migrator import get_migrator
from app.modules.db.models import User


db = init_database()
migrator = get_migrator(db)


def table_has_column(table_name: str, column_name: str) -> bool:
    """Return True when a table already contains the requested column."""
    return any(
        column.name == column_name
        for column in migration_get_columns(db, table_name)
    )


def upgrade() -> None:
    """Add nullable locale and system-default theme preferences."""
    user_table = User._meta.table_name
    operations = []

    if not table_has_column(user_table, "locale"):
        operations.append(
            migrator.add_column(
                user_table,
                "locale",
                CharField(null=True),
            )
        )

    if not table_has_column(user_table, "theme"):
        operations.append(
            migrator.add_column(
                user_table,
                "theme",
                CharField(default="system"),
            )
        )

    if operations:
        migrate(*operations)


def downgrade() -> None:
    """Remove user locale and theme preferences."""
    user_table = User._meta.table_name
    operations = []

    if table_has_column(user_table, "theme"):
        operations.append(migrator.drop_column(user_table, "theme"))

    if table_has_column(user_table, "locale"):
        operations.append(migrator.drop_column(user_table, "locale"))

    if operations:
        migrate(*operations)
