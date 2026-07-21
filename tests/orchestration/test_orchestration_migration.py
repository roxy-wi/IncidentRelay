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



def test_event_orchestration_runtime_migration_upgrade_and_downgrade(db):
    models_path = os.path.join(
        get_migrations_dir(),
        "20260719090000_event_orchestration_models.py",
    )
    models_upgrade, _ = load_migration_module(models_path)
    models_upgrade()

    path = os.path.join(
        get_migrations_dir(),
        "20260720090000_event_orchestration_runtime.py",
    )
    upgrade, downgrade = load_migration_module(path)

    upgrade()
    expected_columns = {
        "event_orchestration": "compatibility_mode",
        "alert_group": "notification_policy_id",
        "alert": "notification_policy_id",
    }
    for table, column_name in expected_columns.items():
        assert column_name in {
            column.name for column in db.get_columns(table)
        }

    downgrade()
    for table, column_name in expected_columns.items():
        assert column_name not in {
            column.name for column in db.get_columns(table)
        }

    upgrade()
    for table, column_name in expected_columns.items():
        assert column_name in {
            column.name for column in db.get_columns(table)
        }
