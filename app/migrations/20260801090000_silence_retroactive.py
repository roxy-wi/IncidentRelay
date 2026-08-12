"""Add optional retroactive Silence application and persisted alert links."""

from peewee import BooleanField, DateTimeField, SqliteDatabase
from playhouse.migrate import migrate

from app.db import init_database
from app.migrations.introspection import get_columns, get_indexes, table_exists
from app.modules.db.migrator import get_migrator
from app.modules.db.models import Silence, SilenceAlertApplication


db = init_database()
migrator = get_migrator(db)
SILENCE_COLUMNS = (
    ("apply_to_existing", lambda: BooleanField(default=False)),
    ("reconciled_at", lambda: DateTimeField(null=True)),
    ("updated_at", lambda: DateTimeField(null=True)),
)


def _column_names(table_name: str) -> set[str]:
    if not table_exists(db, table_name):
        return set()
    return {column.name for column in get_columns(db, table_name)}


def _has_index(table_name: str, columns: tuple[str, ...]) -> bool:
    if not table_exists(db, table_name):
        return False
    return any(tuple(index.columns) == columns for index in get_indexes(db, table_name))


def upgrade() -> None:
    table_name = Silence._meta.table_name
    columns = _column_names(table_name)
    operations = []

    for column_name, field_factory in SILENCE_COLUMNS:
        if column_name not in columns:
            operations.append(
                migrator.add_column(
                    table_name,
                    column_name,
                    field_factory(),
                )
            )

    if operations:
        migrate(*operations)

    if table_exists(db, table_name):
        (
            Silence.update(updated_at=Silence.created_at)
            .where(Silence.updated_at.is_null(True))
            .execute()
        )
        if not _has_index(table_name, ("reconciled_at",)):
            migrate(
                migrator.add_index(
                    table_name,
                    ("reconciled_at",),
                    unique=False,
                )
            )

    db.create_tables([SilenceAlertApplication], safe=True)


def downgrade() -> None:
    db.drop_tables([SilenceAlertApplication], safe=True)

    table_name = Silence._meta.table_name
    columns = _column_names(table_name)
    removed_columns = {column_name for column_name, _ in SILENCE_COLUMNS}
    if table_exists(db, table_name):
        for index in get_indexes(db, table_name):
            if removed_columns.intersection(index.columns):
                migrate(migrator.drop_index(table_name, index.name))

    for column_name, _ in reversed(SILENCE_COLUMNS):
        if column_name not in columns:
            continue
        if isinstance(db, SqliteDatabase):
            operation = migrator.drop_column(
                table_name,
                column_name,
                legacy=True,
            )
        else:
            operation = migrator.drop_column(table_name, column_name)
        migrate(operation)
