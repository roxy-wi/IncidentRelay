"""Widen externally controlled alert text fields for reliable intake."""

from peewee import TextField
from playhouse.migrate import migrate

from app.db import init_database
from app.migrations.introspection import (
    get_columns,
    get_indexes,
    is_postgres,
    table_exists,
)
from app.modules.db.migrator import get_migrator
from app.modules.db.models import Alert, AlertGroup


db = init_database()
migrator = get_migrator(db)

TEXT_COLUMNS = (
    (AlertGroup._meta.table_name, "title"),
    (Alert._meta.table_name, "title"),
    (Alert._meta.table_name, "external_id"),
    (Alert._meta.table_name, "group_key"),
)

ALERT_GROUP_KEY_INDEX_COLUMNS = {
    ("group_key",),
    ("group_key", "status"),
}


def _is_sqlite():
    return "sqlite" in db.__class__.__name__.lower()


def _column(table_name, column_name):
    if not table_exists(db, table_name):
        return None

    return next(
        (
            column
            for column in get_columns(db, table_name)
            if column.name == column_name
        ),
        None,
    )


def _is_text_column(column):
    data_type = str(getattr(column, "data_type", "") or "").lower()
    return "text" in data_type


def _drop_alert_group_key_indexes():
    table_name = Alert._meta.table_name

    if not table_exists(db, table_name):
        return

    for index in list(get_indexes(db, table_name)):
        if tuple(index.columns) not in ALERT_GROUP_KEY_INDEX_COLUMNS:
            continue
        if getattr(index, "unique", False):
            continue

        migrate(migrator.drop_index(table_name, index.name))


def upgrade():
    """Allow long upstream titles/ids/group keys without PostgreSQL failures."""
    _drop_alert_group_key_indexes()

    # SQLite does not enforce VARCHAR length. Existing SQLite installations
    # therefore already accept these values; new installations use TextField
    # from the model definitions.
    if _is_sqlite():
        return

    operations = []

    for table_name, column_name in TEXT_COLUMNS:
        column = _column(table_name, column_name)
        if column is None or _is_text_column(column):
            continue

        if is_postgres(db):
            quoted_table = '"' + table_name.replace('"', '""') + '"'
            quoted_column = '"' + column_name.replace('"', '""') + '"'
            db.execute_sql(
                f"ALTER TABLE {quoted_table} "
                f"ALTER COLUMN {quoted_column} TYPE TEXT"
            )
            continue

        operations.append(
            migrator.alter_column_type(
                table_name,
                column_name,
                TextField(null=bool(column.null)),
            )
        )

    if operations:
        migrate(*operations)


def downgrade():
    # Do not narrow these columns back to VARCHAR(255): after this migration
    # they may legitimately contain longer values. Older IncidentRelay code
    # remains compatible with TEXT because Peewee CharField does not enforce
    # max_length at runtime.
    pass
