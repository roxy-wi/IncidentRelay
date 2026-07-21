import re

from app.db import init_database
from app.migrations.introspection import (
    get_columns as migration_get_columns,
    get_tables as migration_get_tables,
)


db = init_database()


def _is_postgres():
    database_name = db.__class__.__name__.lower()
    return "postgres" in database_name or "postgre" in database_name


def _is_mysql():
    return "mysql" in db.__class__.__name__.lower()


def _get_tables():
    return migration_get_tables(db)


def _quote_identifier(value):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise RuntimeError(f'Unsafe database identifier: "{value}"')

    quote = "`" if _is_mysql() else '"'
    return f"{quote}{value}{quote}"


def _table_columns(table_name):
    return {
        column.name
        for column in migration_get_columns(db, table_name)
    }


def _find_table(label, preferred_names, required_columns):
    tables = _get_tables()

    for table_name in preferred_names:
        if table_name in tables and required_columns.issubset(_table_columns(table_name)):
            return table_name

    matches = []

    for table_name in tables:
        try:
            columns = _table_columns(table_name)
        except Exception:
            continue

        if required_columns.issubset(columns):
            matches.append(table_name)

    if len(matches) == 1:
        return matches[0]

    available_tables = ", ".join(sorted(tables)) or "<none>"
    matching_tables = ", ".join(sorted(matches)) or "<none>"

    raise RuntimeError(
        f"Could not identify {label} table. "
        f"Matching tables: {matching_tables}. "
        f"Available tables: {available_tables}"
    )


def _column_exists(table_name, column_name):
    return column_name in _table_columns(table_name)


def _add_matcher_preset_column(table_name, preset_table):
    if _column_exists(table_name, "matcher_preset_id"):
        return

    quoted_table = _quote_identifier(table_name)
    quoted_preset_table = _quote_identifier(preset_table)

    db.execute_sql(
        f"ALTER TABLE {quoted_table} "
        f"ADD COLUMN {_quote_identifier('matcher_preset_id')} INTEGER NULL "
        f"REFERENCES {quoted_preset_table} ({_quote_identifier('id')}) "
        "ON DELETE RESTRICT"
    )


def _create_matcher_preset_index(table_name):
    index_name = f"idx_{table_name}_matcher_preset_id"
    quoted_index = _quote_identifier(index_name)
    quoted_table = _quote_identifier(table_name)
    quoted_column = _quote_identifier("matcher_preset_id")

    db.execute_sql(
        f"CREATE INDEX IF NOT EXISTS {quoted_index} "
        f"ON {quoted_table} ({quoted_column})"
    )


def _resolve_tables():
    route_table = _find_table(
        "alert route",
        ("alertroute", "alert_route", "alert_routes", "route", "routes"),
        {"id", "team_id", "name", "source", "matchers", "enabled"},
    )

    service_match_rule_table = _find_table(
        "service match rule",
        ("service_match_rule", "servicematchrule", "service_match_rules"),
        {"id", "team_id", "service_id", "route_id", "position", "matchers", "enabled"},
    )

    matcher_preset_table = _find_table(
        "matcher preset",
        ("matcher_preset", "matcherpreset", "matcher_presets"),
        {"id", "team_id", "name", "matchers", "enabled", "version"},
    )

    return route_table, service_match_rule_table, matcher_preset_table


def upgrade():
    """Add matcher preset references to routes and service match rules."""
    route_table, service_match_rule_table, matcher_preset_table = _resolve_tables()

    _add_matcher_preset_column(route_table, matcher_preset_table)
    _add_matcher_preset_column(service_match_rule_table, matcher_preset_table)

    _create_matcher_preset_index(route_table)
    _create_matcher_preset_index(service_match_rule_table)


def downgrade():
    """Remove route and service match rule matcher preset references."""
    route_table, service_match_rule_table, _ = _resolve_tables()

    route_index = _quote_identifier(f"idx_{route_table}_matcher_preset_id")
    service_match_rule_index = _quote_identifier(
        f"idx_{service_match_rule_table}_matcher_preset_id"
    )

    db.execute_sql(f"DROP INDEX IF EXISTS {route_index}")
    db.execute_sql(f"DROP INDEX IF EXISTS {service_match_rule_index}")

    if not _is_postgres():
        return

    quoted_column = _quote_identifier("matcher_preset_id")

    if _column_exists(route_table, "matcher_preset_id"):
        db.execute_sql(
            f"ALTER TABLE {_quote_identifier(route_table)} "
            f"DROP COLUMN IF EXISTS {quoted_column}"
        )

    if _column_exists(service_match_rule_table, "matcher_preset_id"):
        db.execute_sql(
            f"ALTER TABLE {_quote_identifier(service_match_rule_table)} "
            f"DROP COLUMN IF EXISTS {quoted_column}"
        )
