from app.db import database_proxy as db


def _database():
    return db.obj


def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _table_exists(table_name):
    return table_name in _database().get_tables()


def _column_exists(table_name, column_name):
    columns = _database().get_columns(table_name)

    return any(column.name == column_name for column in columns)


def _is_sqlite():
    return _database().__class__.__name__.lower().startswith("sqlite")


def _bool_column(default=True):
    if _is_sqlite():
        return f"INTEGER NOT NULL DEFAULT {1 if default else 0}"

    return f"BOOLEAN NOT NULL DEFAULT {'TRUE' if default else 'FALSE'}"


def _add_column_if_missing(table_name, column_name, definition):
    if not _table_exists(table_name):
        return

    if _column_exists(table_name, column_name):
        return

    db.execute_sql(
        "ALTER TABLE "
        f"{_quote(table_name)} "
        "ADD COLUMN "
        f"{_quote(column_name)} {definition}"
    )


def _drop_column_if_exists(table_name, column_name):
    if not _table_exists(table_name):
        return

    if not _column_exists(table_name, column_name):
        return

    try:
        db.execute_sql(
            "ALTER TABLE "
            f"{_quote(table_name)} "
            "DROP COLUMN "
            f"{_quote(column_name)}"
        )
    except Exception:
        # SQLite on old versions may not support DROP COLUMN.
        pass


def upgrade():
    for table_name in ("service_owner", "incident_stakeholder"):
        _add_column_if_missing(
            table_name,
            "notify_on_comment",
            _bool_column(default=True),
        )


def rollback():
    for table_name in ("incident_stakeholder", "service_owner"):
        _drop_column_if_exists(table_name, "notify_on_comment")
