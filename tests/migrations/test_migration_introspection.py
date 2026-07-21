from pathlib import Path

from app.migrations.introspection import (
    column_exists,
    get_columns,
    get_indexes,
    get_tables,
    resolve_table_schema,
    table_exists,
)


class _Cursor:
    def __init__(self, *, one=None, all_rows=None):
        self._one = one
        self._all_rows = all_rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all_rows


class _Column:
    def __init__(self, name):
        self.name = name


class _Index:
    def __init__(self, name):
        self.name = name


class FakePostgresqlDatabase:
    def __init__(self, *, schema="incidentrelay", relation_exists=True):
        self.schema = schema
        self.relation_exists = relation_exists
        self.sql_calls = []
        self.column_calls = []
        self.index_calls = []

    def execute_sql(self, sql, params=None):
        normalized = " ".join(sql.split())
        self.sql_calls.append((normalized, params))

        if "JOIN pg_catalog.pg_namespace" in normalized:
            row = (self.schema,) if self.relation_exists else None
            return _Cursor(one=row)

        if "to_regclass(%s) IS NOT NULL" in normalized:
            return _Cursor(one=(self.relation_exists,))

        if "FROM information_schema.tables" in normalized:
            return _Cursor(all_rows=[("alert",), ("alertroute",)])

        raise AssertionError(f"Unexpected SQL: {normalized}")

    def get_columns(self, table_name, schema=None):
        self.column_calls.append((table_name, schema))
        return [_Column("id"), _Column("escalation_policy_id")]

    def get_indexes(self, table_name, schema=None):
        self.index_calls.append((table_name, schema))
        return [_Index("idx_alertroute_escalation_policy_id")]


class _DatabaseProxy:
    def __init__(self, database):
        self.obj = database


class FakeSqliteDatabase:
    def __init__(self):
        self.column_calls = []
        self.index_calls = []

    def get_columns(self, table_name):
        self.column_calls.append(table_name)
        return [_Column("id")]

    def get_indexes(self, table_name):
        self.index_calls.append(table_name)
        return [_Index("idx_alert_id")]

    def get_tables(self):
        return ["alert"]


def test_postgres_columns_use_schema_of_relation_resolved_by_search_path():
    db = FakePostgresqlDatabase(schema="incidentrelay")

    columns = get_columns(db, "alertroute")

    assert [column.name for column in columns] == ["id", "escalation_policy_id"]
    assert db.column_calls == [("alertroute", "incidentrelay")]
    assert db.sql_calls[0][1] == ("alertroute",)


def test_postgres_missing_relation_returns_no_columns_without_public_fallback():
    db = FakePostgresqlDatabase(relation_exists=False)

    assert get_columns(db, "missing_table") == []
    assert db.column_calls == []


def test_postgres_indexes_use_resolved_relation_schema():
    db = FakePostgresqlDatabase(schema="incidentrelay")

    indexes = get_indexes(db, "alertroute")

    assert [index.name for index in indexes] == [
        "idx_alertroute_escalation_policy_id"
    ]
    assert db.index_calls == [("alertroute", "incidentrelay")]


def test_postgres_table_helpers_follow_search_path():
    db = FakePostgresqlDatabase(schema="incidentrelay")

    assert resolve_table_schema(db, "alertroute") == "incidentrelay"
    assert table_exists(db, "alertroute") is True
    assert get_tables(db) == ["alert", "alertroute"]
    assert column_exists(db, "alertroute", "escalation_policy_id") is True


def test_database_proxy_is_unwrapped_before_postgres_introspection():
    database = FakePostgresqlDatabase(schema="incidentrelay")
    proxy = _DatabaseProxy(database)

    assert column_exists(proxy, "alertroute", "escalation_policy_id") is True
    assert database.column_calls == [("alertroute", "incidentrelay")]


def test_non_postgres_introspection_preserves_existing_behavior():
    db = FakeSqliteDatabase()

    assert [column.name for column in get_columns(db, "alert")] == ["id"]
    assert [index.name for index in get_indexes(db, "alert")] == ["idx_alert_id"]
    assert get_tables(db) == ["alert"]
    assert table_exists(db, "alert") is True
    assert db.column_calls == ["alert"]
    assert db.index_calls == ["alert"]


def test_migrations_do_not_call_schema_unsafe_peewee_introspection_directly():
    migrations_dir = Path(__file__).resolve().parents[2] / "app" / "migrations"
    unsafe_calls = []

    for path in sorted(migrations_dir.glob("[0-9]*.py")):
        source = path.read_text(encoding="utf-8")

        for method in ("get_columns", "get_indexes", "get_tables"):
            marker = f".{method}("
            if marker in source:
                unsafe_calls.append(f"{path.name}: {marker}")

    assert unsafe_calls == []
