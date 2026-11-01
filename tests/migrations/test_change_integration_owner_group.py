"""Ownership upgrades retain central identities and their dependent records."""

from importlib import import_module

import pytest
from peewee import IntegrityError, SqliteDatabase

from app.modules.db.models import ChangeIntegration, ChangeSource
from tests.factories import create_group, create_team


migration = import_module(
    "app.migrations.20261030010000_change_integration_owner_group"
)


def test_ownership_upgrade_preserves_existing_central_identity(db):
    group = create_group()
    team = create_team(group)
    integration = ChangeIntegration.create(name="Existing central CI")
    try:
        migration.downgrade()
        source = ChangeSource.create(
            integration=integration.id, owner_team=team, source="existing"
        )
        migration.upgrade()
        migration.upgrade()
        restored = ChangeIntegration.get_by_id(integration.id)
        assert restored.owner_group_id is None
        assert restored.uid == integration.uid
        assert ChangeSource.get_by_id(source.id).integration_id == integration.id
    finally:
        migration.upgrade()


def test_ownership_constraint_and_non_destructive_rollback(db):
    group = create_group()
    integration = ChangeIntegration.create(name="Owned", owner_group=group)
    with pytest.raises(RuntimeError, match="Group integrations exist"):
        migration.downgrade()
    assert ChangeIntegration.get_by_id(integration.id).owner_group_id == group.id
    with pytest.raises(IntegrityError), db.atomic():
        group.delete_instance()


def test_sqlite_legacy_schema_upgrades_without_rebuilding_dependents(
    tmp_path, monkeypatch
):
    legacy = SqliteDatabase(tmp_path / "legacy.db", pragmas={"foreign_keys": 1})
    monkeypatch.setattr(migration, "init_database", lambda: legacy)
    try:
        legacy.execute_sql('CREATE TABLE "oncall_group" (id INTEGER PRIMARY KEY)')
        legacy.execute_sql(
            "CREATE TABLE change_integration (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
        )
        legacy.execute_sql(
            "CREATE TABLE old_source (id INTEGER PRIMARY KEY, integration_id INTEGER REFERENCES change_integration(id) ON DELETE CASCADE)"
        )
        legacy.execute_sql("INSERT INTO change_integration VALUES (1, 'Existing')")
        legacy.execute_sql("INSERT INTO old_source VALUES (1, 1)")
        migration.upgrade()
        migration.upgrade()
        assert legacy.execute_sql(
            "SELECT name, owner_group_id FROM change_integration"
        ).fetchall() == [("Existing", None)]
        assert legacy.execute_sql(
            "SELECT integration_id FROM old_source"
        ).fetchall() == [(1,)]
        with pytest.raises(IntegrityError):
            legacy.execute_sql("UPDATE change_integration SET owner_group_id=999")
    finally:
        legacy.close()
