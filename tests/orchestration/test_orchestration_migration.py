import os

from app.modules.db.migrations import get_migrations_dir, load_migration_module


TABLES = {
    "event_orchestration",
    "event_orchestration_version",
    "event_orchestration_rule",
    "orchestration_intake_token",
    "orchestration_execution",
}


def test_event_orchestration_migration_upgrade_and_downgrade(db):
    path = os.path.join(
        get_migrations_dir(),
        "20260719090000_event_orchestration_models.py",
    )
    upgrade, downgrade = load_migration_module(path)

    upgrade()
    assert TABLES.issubset(set(db.get_tables()))

    downgrade()
    assert TABLES.isdisjoint(set(db.get_tables()))

    upgrade()
