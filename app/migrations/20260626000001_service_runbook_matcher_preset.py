import re

from app.db import init_database
from app.modules.db.models import MatcherPreset, ServiceRunbook


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


def _current_schema():
    if not _is_postgres():
        return None

    row = db.execute_sql("SELECT current_schema()").fetchone()
    return row[0] if row else None


def _get_columns(table_name):
    schema = _current_schema()

    if schema:
        return db.get_columns(table_name, schema=schema)

    return db.get_columns(table_name)


def _column_exists(table_name, column_name):
    return any(column.name == column_name for column in _get_columns(table_name))


def upgrade():
    """Add matcher preset reference to service runbooks."""
    runbook_table = ServiceRunbook._meta.table_name
    preset_table = MatcherPreset._meta.table_name
    quoted_runbook_table = _quote_identifier(runbook_table)
    quoted_preset_table = _quote_identifier(preset_table)
    quoted_column = _quote_identifier("matcher_preset_id")
    quoted_id = _quote_identifier("id")
    index_name = _quote_identifier(f"idx_{runbook_table}_matcher_preset_id")

    if not _column_exists(runbook_table, "matcher_preset_id"):
        db.execute_sql(
            f"ALTER TABLE {quoted_runbook_table} "
            f"ADD COLUMN {quoted_column} INTEGER NULL "
            f"REFERENCES {quoted_preset_table} ({quoted_id}) "
            "ON DELETE RESTRICT"
        )

    db.execute_sql(
        f"CREATE INDEX IF NOT EXISTS {index_name} "
        f"ON {quoted_runbook_table} ({quoted_column})"
    )


def downgrade():
    """Remove matcher preset reference from service runbooks."""
    runbook_table = ServiceRunbook._meta.table_name
    quoted_runbook_table = _quote_identifier(runbook_table)
    quoted_column = _quote_identifier("matcher_preset_id")
    index_name = _quote_identifier(f"idx_{runbook_table}_matcher_preset_id")

    db.execute_sql(f"DROP INDEX IF EXISTS {index_name}")

    if _is_postgres() and _column_exists(runbook_table, "matcher_preset_id"):
        db.execute_sql(
            f"ALTER TABLE {quoted_runbook_table} "
            f"DROP COLUMN IF EXISTS {quoted_column}"
        )
