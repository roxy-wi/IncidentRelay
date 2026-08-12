"""Add per-Silence automatic reactivation preference."""

from peewee import BooleanField, SqliteDatabase
from playhouse.migrate import migrate

from app.db import init_database
from app.migrations.introspection import get_columns, table_exists
from app.modules.db.migrator import get_migrator
from app.modules.db.models import Silence


db = init_database()
migrator = get_migrator(db)
COLUMN_NAME = "reactivate_on_end"


def _column_names(table_name: str) -> set[str]:
    if not table_exists(db, table_name):
        return set()
    return {column.name for column in get_columns(db, table_name)}


def upgrade() -> None:
    table_name = Silence._meta.table_name
    if COLUMN_NAME in _column_names(table_name):
        return

    migrate(
        migrator.add_column(
            table_name,
            COLUMN_NAME,
            BooleanField(default=True),
        )
    )


def downgrade() -> None:
    table_name = Silence._meta.table_name
    if COLUMN_NAME not in _column_names(table_name):
        return

    if isinstance(db, SqliteDatabase):
        operation = migrator.drop_column(
            table_name,
            COLUMN_NAME,
            legacy=True,
        )
    else:
        operation = migrator.drop_column(table_name, COLUMN_NAME)
    migrate(operation)
