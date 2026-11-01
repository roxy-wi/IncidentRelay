"""Add an optional user color preference without rewriting existing users."""

from peewee import CharField
from playhouse.migrate import migrate

from app.db import init_database
from app.migrations.introspection import get_columns
from app.modules.db.migrator import get_migrator
from app.modules.db.models import User


def upgrade() -> None:
    """Existing and new accounts use their ID-based color until customized."""
    db = init_database()
    table = User._meta.table_name
    if "color" not in {column.name for column in get_columns(db, table)}:
        migrate(
            get_migrator(db).add_column(
                table, "color", CharField(null=True, max_length=7)
            )
        )


def downgrade() -> None:
    """Remove the preference while preserving accounts and their relations."""
    db = init_database()
    table = User._meta.table_name
    if "color" in {column.name for column in get_columns(db, table)}:
        migrate(get_migrator(db).drop_column(table, "color"))
