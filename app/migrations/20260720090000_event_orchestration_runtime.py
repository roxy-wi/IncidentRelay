"""Add runtime rollout state and persisted notification-policy overrides."""

from peewee import CharField, IntegerField, SqliteDatabase
from playhouse.migrate import SchemaMigrator, migrate

from app.db import init_database


db = init_database()
RUNTIME_COLUMNS = {
    "event_orchestration": {
        "compatibility_mode": lambda: CharField(
            max_length=32,
            default="legacy",
        ),
    },
    "alert_group": {
        "notification_policy_id": lambda: IntegerField(null=True),
    },
    "alert": {
        "notification_policy_id": lambda: IntegerField(null=True),
    },
}
RUNTIME_INDEXES = (
    ("event_orchestration", ("group_id", "compatibility_mode", "enabled")),
    ("alert_group", ("notification_policy_id",)),
    ("alert", ("notification_policy_id",)),
)


def _table_exists(table):
    return table in db.get_tables()


def _columns(table):
    if not _table_exists(table):
        return set()
    return {column.name for column in db.get_columns(table)}


def _indexes(table):
    if not _table_exists(table):
        return []
    return list(db.get_indexes(table))


def _has_index(table, columns):
    expected = tuple(columns)
    return any(tuple(index.columns) == expected for index in _indexes(table))


def upgrade():
    migrator = SchemaMigrator.from_database(db)
    operations = []

    for table, columns in RUNTIME_COLUMNS.items():
        if not _table_exists(table):
            continue
        existing = _columns(table)
        for name, field_factory in columns.items():
            if name not in existing:
                operations.append(
                    migrator.add_column(table, name, field_factory())
                )

    if operations:
        migrate(*operations)

    for table, columns in RUNTIME_INDEXES:
        if _table_exists(table) and not _has_index(table, columns):
            migrate(migrator.add_index(table, columns, unique=False))


def downgrade():
    migrator = SchemaMigrator.from_database(db)

    for table, columns in reversed(tuple(RUNTIME_COLUMNS.items())):
        if not _table_exists(table):
            continue
        removed_columns = set(columns)
        for index in _indexes(table):
            if removed_columns.intersection(index.columns):
                migrate(migrator.drop_index(table, index.name))

    for table, columns in reversed(tuple(RUNTIME_COLUMNS.items())):
        existing = _columns(table)
        for name in reversed(tuple(columns)):
            if name not in existing:
                continue
            if isinstance(db, SqliteDatabase):
                operation = migrator.drop_column(
                    table,
                    name,
                    legacy=True,
                )
            else:
                operation = migrator.drop_column(table, name)
            migrate(operation)
