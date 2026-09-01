import os

from app.modules.db.migrations import get_migrations_dir, load_migration_module
from app.modules.db.models import AlertExplainTrace


def test_alert_explain_trace_level_migration_upgrade_and_downgrade(db):
    path = os.path.join(
        get_migrations_dir(),
        "20260821000001_alert_explain_trace_level.py",
    )
    upgrade, downgrade = load_migration_module(path)
    table_name = AlertExplainTrace._meta.table_name

    upgrade()
    assert "trace_level" in {
        column.name for column in db.get_columns(table_name)
    }

    downgrade()
    assert "trace_level" not in {
        column.name for column in db.get_columns(table_name)
    }

    # Restore the current schema for the shared test database.
    upgrade()
    assert "trace_level" in {
        column.name for column in db.get_columns(table_name)
    }
