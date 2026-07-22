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
    webhooks_path = os.path.join(
        get_migrations_dir(),
        "20260721110000_event_orchestration_webhooks.py",
    )
    webhooks_upgrade, webhooks_downgrade = load_migration_module(webhooks_path)
    dispositions_path = os.path.join(
        get_migrations_dir(),
        "20260721100000_event_orchestration_dispositions.py",
    )
    dispositions_upgrade, dispositions_downgrade = load_migration_module(
        dispositions_path
    )
    runtime_path = os.path.join(
        get_migrations_dir(),
        "20260720090000_event_orchestration_runtime.py",
    )
    runtime_upgrade, runtime_downgrade = load_migration_module(runtime_path)
    path = os.path.join(
        get_migrations_dir(),
        "20260719090000_event_orchestration_models.py",
    )
    upgrade, downgrade = load_migration_module(path)

    # Dependent tables and columns must be removed before the base models.
    webhooks_downgrade()
    dispositions_downgrade()
    runtime_downgrade()

    upgrade()
    assert TABLES.issubset(set(db.get_tables()))

    downgrade()
    assert TABLES.isdisjoint(set(db.get_tables()))

    # Restore the current schema for the shared migrated test database.
    upgrade()
    runtime_upgrade()
    dispositions_upgrade()
    webhooks_upgrade()



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


def test_event_orchestration_dispositions_migration_upgrade_and_downgrade(db):
    runtime_path = os.path.join(
        get_migrations_dir(),
        "20260720090000_event_orchestration_runtime.py",
    )
    runtime_upgrade, _ = load_migration_module(runtime_path)
    runtime_upgrade()

    path = os.path.join(
        get_migrations_dir(),
        "20260721100000_event_orchestration_dispositions.py",
    )
    upgrade, downgrade = load_migration_module(path)

    upgrade()
    assert "pending_orchestrated_event" in set(db.get_tables())
    expected_columns = {
        "alert_group": {
            "orchestration_suppressed",
            "orchestration_suppress_reason",
        },
        "alert": {
            "orchestration_suppressed",
            "orchestration_suppress_reason",
        },
    }
    for table, column_names in expected_columns.items():
        assert column_names.issubset(
            {column.name for column in db.get_columns(table)}
        )

    downgrade()
    assert "pending_orchestrated_event" not in set(db.get_tables())
    for table, column_names in expected_columns.items():
        assert column_names.isdisjoint(
            {column.name for column in db.get_columns(table)}
        )

    upgrade()
    assert "pending_orchestrated_event" in set(db.get_tables())
    for table, column_names in expected_columns.items():
        assert column_names.issubset(
            {column.name for column in db.get_columns(table)}
        )


def test_event_orchestration_webhook_migration_upgrade_and_downgrade(db):
    path = os.path.join(
        get_migrations_dir(),
        "20260721110000_event_orchestration_webhooks.py",
    )
    upgrade, downgrade = load_migration_module(path)

    upgrade()
    assert {
        "orchestration_webhook_action",
        "automation_execution",
    }.issubset(set(db.get_tables()))

    downgrade()
    assert {
        "orchestration_webhook_action",
        "automation_execution",
    }.isdisjoint(set(db.get_tables()))

    upgrade()
    assert {
        "orchestration_webhook_action",
        "automation_execution",
    }.issubset(set(db.get_tables()))
