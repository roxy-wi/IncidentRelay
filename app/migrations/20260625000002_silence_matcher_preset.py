import re

from app.db import init_database
from app.migrations.introspection import (
    get_columns as migration_get_columns,
)
from app.modules.db.models import MatcherPreset, Silence


db = init_database()


def _is_postgres():
    name = db.__class__.__name__.lower()
    return "postgres" in name or "postgre" in name


def _is_mysql():
    return "mysql" in db.__class__.__name__.lower()


def _quote_identifier(value):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise RuntimeError(f'Unsafe database identifier: "{value}"')

    quote = "`" if _is_mysql() else '"'
    return f"{quote}{value}{quote}"


def _get_columns(table_name):
    return migration_get_columns(db, table_name)


def _column_exists(table_name, column_name):
    return any(column.name == column_name for column in _get_columns(table_name))


def upgrade():
    """Add matcher preset reference to silences."""
    silence_table = Silence._meta.table_name
    preset_table = MatcherPreset._meta.table_name

    quoted_silence_table = _quote_identifier(silence_table)
    quoted_preset_table = _quote_identifier(preset_table)
    quoted_column = _quote_identifier("matcher_preset_id")
    index_name = _quote_identifier(f"idx_{silence_table}_matcher_preset_id")

    if not _column_exists(silence_table, "matcher_preset_id"):
        db.execute_sql(
            f"ALTER TABLE {quoted_silence_table} "
            f"ADD COLUMN {quoted_column} INTEGER NULL "
            f"REFERENCES {quoted_preset_table} ({_quote_identifier('id')}) "
            "ON DELETE RESTRICT"
        )

    db.execute_sql(
        f"CREATE INDEX IF NOT EXISTS {index_name} "
        f"ON {quoted_silence_table} ({quoted_column})"
    )


def downgrade():
    """Remove matcher preset reference from silences."""
    silence_table = Silence._meta.table_name
    quoted_silence_table = _quote_identifier(silence_table)
    quoted_column = _quote_identifier("matcher_preset_id")
    index_name = _quote_identifier(f"idx_{silence_table}_matcher_preset_id")

    db.execute_sql(f"DROP INDEX IF EXISTS {index_name}")

    if _is_postgres() and _column_exists(silence_table, "matcher_preset_id"):
        db.execute_sql(
            f"ALTER TABLE {quoted_silence_table} "
            f"DROP COLUMN IF EXISTS {quoted_column}"
        )
