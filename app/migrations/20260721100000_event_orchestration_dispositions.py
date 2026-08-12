"""Add suppress/drop/pause persistence for Event Orchestration."""

from peewee import BooleanField, TextField, SqliteDatabase
from playhouse.migrate import SchemaMigrator, migrate

from app.db import init_database
from app.migrations.introspection import get_columns, get_indexes, table_exists
from app.modules.db.models import PendingOrchestratedEvent


db = init_database()
COLUMNS = {
    "alert_group": {
        "orchestration_suppressed": lambda: BooleanField(default=False),
        "orchestration_suppress_reason": lambda: TextField(null=True),
    },
    "alert": {
        "orchestration_suppressed": lambda: BooleanField(default=False),
        "orchestration_suppress_reason": lambda: TextField(null=True),
    },
}
INDEXES = (
    ("alert_group", ("orchestration_suppressed",)),
    ("alert", ("orchestration_suppressed",)),
)


def _columns(table):
    if not table_exists(db, table):
        return set()
    return {column.name for column in get_columns(db, table)}


def _indexes(table):
    if not table_exists(db, table):
        return []
    return list(get_indexes(db, table))


def _has_index(table, columns):
    expected = tuple(columns)
    return any(tuple(index.columns) == expected for index in _indexes(table))


def upgrade():
    migrator = SchemaMigrator.from_database(db)
    operations = []
    for table, columns in COLUMNS.items():
        if not table_exists(db, table):
            continue
        existing = _columns(table)
        for name, factory in columns.items():
            if name not in existing:
                operations.append(migrator.add_column(table, name, factory()))
    if operations:
        migrate(*operations)

    for table, columns in INDEXES:
        if table_exists(db, table) and not _has_index(table, columns):
            migrate(migrator.add_index(table, columns, unique=False))

    db.create_tables([PendingOrchestratedEvent], safe=True)


def downgrade():
    if table_exists(db, PendingOrchestratedEvent._meta.table_name):
        db.drop_tables([PendingOrchestratedEvent], safe=True)

    migrator = SchemaMigrator.from_database(db)
    for table, columns in reversed(tuple(COLUMNS.items())):
        if not table_exists(db, table):
            continue
        removed = set(columns)
        for index in _indexes(table):
            if removed.intersection(index.columns):
                migrate(migrator.drop_index(table, index.name))

    for table, columns in reversed(tuple(COLUMNS.items())):
        existing = _columns(table)
        for name in reversed(tuple(columns)):
            if name not in existing:
                continue
            if isinstance(db, SqliteDatabase):
                operation = migrator.drop_column(table, name, legacy=True)
            else:
                operation = migrator.drop_column(table, name)
            migrate(operation)
