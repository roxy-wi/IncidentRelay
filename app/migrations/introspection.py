"""Schema-aware database introspection helpers for migrations.

Peewee's PostgreSQL introspection methods default to the ``public`` schema
when no schema is provided. IncidentRelay supports custom ``search_path``
configurations, so migrations must resolve the schema of the unqualified
relation exactly as PostgreSQL would before checking columns or indexes.
"""

from typing import Any, List, Optional


def _database(database):
    """Unwrap a DatabaseProxy while accepting a regular database object."""
    return getattr(database, "obj", database)


def is_postgres(database) -> bool:
    name = _database(database).__class__.__name__.lower()
    return "postgres" in name or "postgre" in name or "cockroach" in name


def resolve_table_schema(database, table_name: str) -> Optional[str]:
    """Return the schema PostgreSQL resolves for an unqualified table name."""
    db = _database(database)

    if not is_postgres(db):
        return None

    row = db.execute_sql(
        """
        SELECT namespace.nspname
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE relation.oid = pg_catalog.to_regclass(%s)
        """,
        (table_name,),
    ).fetchone()

    return row[0] if row and row[0] else None


def get_columns(database, table_name: str) -> List[Any]:
    """Return columns for the relation selected by the active search_path."""
    db = _database(database)
    schema = resolve_table_schema(db, table_name)

    if is_postgres(db):
        if schema is None:
            return []
        return db.get_columns(table_name, schema=schema)

    return db.get_columns(table_name)


def get_indexes(database, table_name: str) -> List[Any]:
    """Return indexes for the relation selected by the active search_path."""
    db = _database(database)
    schema = resolve_table_schema(db, table_name)

    if is_postgres(db):
        if schema is None:
            return []
        return db.get_indexes(table_name, schema=schema)

    return db.get_indexes(table_name)


def get_tables(database) -> List[str]:
    """Return table names visible through the active PostgreSQL search_path."""
    db = _database(database)

    if not is_postgres(db):
        return db.get_tables()

    rows = db.execute_sql(
        """
        SELECT DISTINCT table_name
        FROM information_schema.tables
        WHERE table_schema = ANY (pg_catalog.current_schemas(FALSE))
          AND table_type IN ('BASE TABLE', 'LOCAL TEMPORARY')
        ORDER BY table_name
        """
    ).fetchall()

    return [row[0] for row in rows]


def table_exists(database, table_name: str) -> bool:
    """Return whether an unqualified relation resolves on the active search_path."""
    db = _database(database)

    if is_postgres(db):
        row = db.execute_sql(
            "SELECT pg_catalog.to_regclass(%s) IS NOT NULL",
            (table_name,),
        ).fetchone()
        return bool(row and row[0])

    return table_name in db.get_tables()


def column_exists(database, table_name: str, column_name: str) -> bool:
    return any(column.name == column_name for column in get_columns(database, table_name))


def index_exists(database, table_name: str, index_name: str) -> bool:
    return any(index.name == index_name for index in get_indexes(database, table_name))
