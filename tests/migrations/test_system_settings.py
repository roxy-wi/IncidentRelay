"""Initial values and database constraints for the system settings singleton."""

from importlib import import_module

import pytest
from peewee import IntegrityError

from app.migrations.introspection import table_exists
from app.modules.db.models import SystemSettings

migration = import_module("app.migrations.20261106010000_system_settings")


def test_migration_creates_one_row_with_defaults_and_preserves_edits_on_rerun(db):
    with db.atomic() as transaction:
        migration.downgrade()
        assert not table_exists(db, "system_settings")
        migration.upgrade()
        row = SystemSettings.get_by_id(1)
        assert row.change_worker_interval_seconds == 5
        assert row.change_pending_ttl_seconds == 604800
        assert row.change_intake_enabled is False
        assert row.change_worker_enabled is True
        SystemSettings.update(
            change_intake_enabled=True, change_worker_enabled=False, change_worker_interval_seconds=21
        ).execute()
        migration.upgrade()
        assert SystemSettings.select().count() == 1
        row = SystemSettings.get_by_id(1)
        assert row.change_worker_interval_seconds == 21
        assert row.change_intake_enabled is True
        assert row.change_worker_enabled is False
        transaction.rollback()


def test_database_requires_singleton_and_non_null_switches(db):
    with pytest.raises(IntegrityError), db.atomic():
        SystemSettings.create(id=2)
    for name in ("change_intake_enabled", "change_worker_enabled"):
        with pytest.raises(IntegrityError), db.atomic():
            SystemSettings.update(**{name: None}).execute()


@pytest.mark.parametrize("values", [
    {"change_worker_jobs_per_tick": 101}, {"change_worker_interval_seconds": None},
    {"change_worker_lease_seconds": 9}, {"change_worker_retry_max_seconds": 4},
])
def test_database_enforces_advanced_bounds(db, values):
    with pytest.raises(IntegrityError), db.atomic():
        SystemSettings.update(**values).execute()
