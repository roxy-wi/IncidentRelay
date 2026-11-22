"""Upgrade existing sources without removing their imported intervals."""

import importlib

import pytest
from peewee import SqliteDatabase

from app.modules.db.models import DirectorySyncSource as Source


def test_source_tombstone_upgrade_and_rollback(monkeypatch):
    migration = importlib.import_module("app.migrations.20261115010000_directory_sync_deletion")
    database = SqliteDatabase(":memory:", pragmas={"foreign_keys": 1})
    monkeypatch.setattr(migration, "init_database", lambda: database)
    with database.connection_context(), Source.bind_ctx(database, bind_refs=False, bind_backrefs=False):
        database.execute_sql("CREATE TABLE directory_sync_source (id INTEGER PRIMARY KEY, name TEXT, enabled INTEGER)")
        database.execute_sql("INSERT INTO directory_sync_source VALUES (1, 'Existing source', 1)")
        children = ("directory_sync_binding", "directory_sync_shift", "directory_sync_current")
        for table in children:
            database.execute_sql(
                f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL "
                "REFERENCES directory_sync_source(id) ON DELETE CASCADE, payload TEXT)"
            )
            database.execute_sql(f"INSERT INTO {table} VALUES (1, 1, 'preserve this data')")
        migration.upgrade()
        migration.upgrade()
        for table in children:
            assert database.execute_sql(f"SELECT * FROM {table}").fetchall() == [(1, 1, "preserve this data")]
        assert database.execute_sql("PRAGMA foreign_keys").fetchone() == (1,)
        assert database.execute_sql("PRAGMA foreign_key_check").fetchall() == []
        assert any(index.columns == ["deleted"] for index in database.get_indexes("directory_sync_source"))
        assert database.execute_sql("SELECT name, enabled, deleted, deleted_at FROM directory_sync_source").fetchone() == (
            "Existing source", 1, 0, None,
        )
        database.execute_sql("UPDATE directory_sync_source SET deleted = 1")
        with pytest.raises(RuntimeError, match="tombstones"):
            migration.downgrade()
        database.execute_sql("UPDATE directory_sync_source SET deleted = 0")
        migration.downgrade()
        assert [column.name for column in database.get_columns("directory_sync_source")] == ["id", "name", "enabled"]
        for table in children:
            assert database.execute_sql(f"SELECT * FROM {table}").fetchall() == [(1, 1, "preserve this data")]
        assert database.execute_sql("PRAGMA foreign_key_check").fetchall() == []
