"""Add indexes used by resolved alert retention cleanup."""

from playhouse.migrate import migrate

from app.db import init_database
from app.migrations.introspection import get_indexes, table_exists
from app.modules.db.migrator import get_migrator
from app.modules.db.models import Alert, AlertGroup


db = init_database()
migrator = get_migrator(db)
INDEXES = (
    (AlertGroup._meta.table_name, ("status", "resolved_at")),
    (Alert._meta.table_name, ("status", "resolved_at")),
)


def _matching_index(table_name: str, columns: tuple[str, ...]):
    if not table_exists(db, table_name):
        return None

    for index in get_indexes(db, table_name):
        if tuple(index.columns) == columns:
            return index
    return None


def upgrade() -> None:
    for table_name, columns in INDEXES:
        if not table_exists(db, table_name):
            continue
        if _matching_index(table_name, columns) is not None:
            continue
        migrate(migrator.add_index(table_name, columns, unique=False))


def downgrade() -> None:
    for table_name, columns in reversed(INDEXES):
        index = _matching_index(table_name, columns)
        if index is not None:
            migrate(migrator.drop_index(table_name, index.name))
