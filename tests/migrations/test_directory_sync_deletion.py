"""Upgrade existing sources without removing their imported intervals."""

import importlib

import pytest
from peewee import SqliteDatabase

from app.modules.db.models import DirectorySyncSource as Source


def test_source_tombstone_upgrade_and_rollback(monkeypatch):
    migration = importlib.import_module("app.migrations.20261115010000_directory_sync_deletion")
    database = SqliteDatabase(":memory:")
    monkeypatch.setattr(migration, "init_database", lambda: database)
    with database.connection_context(), Source.bind_ctx(database, bind_refs=False, bind_backrefs=False):
        database.execute_sql("CREATE TABLE directory_sync_source (id INTEGER PRIMARY KEY, name TEXT, enabled INTEGER)")
        database.execute_sql("INSERT INTO directory_sync_source VALUES (1, 'Existing source', 1)")
        migration.upgrade()
        migration.upgrade()
        assert database.execute_sql("SELECT name, enabled, deleted, deleted_at FROM directory_sync_source").fetchone() == (
            "Existing source", 1, 0, None,
        )
        database.execute_sql("UPDATE directory_sync_source SET deleted = 1")
        with pytest.raises(RuntimeError, match="tombstones"):
            migration.downgrade()
        database.execute_sql("UPDATE directory_sync_source SET deleted = 0")
        migration.downgrade()
        assert [column.name for column in database.get_columns("directory_sync_source")] == ["id", "name", "enabled"]
