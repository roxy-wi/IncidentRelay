from app.db import init_database
from app.migrations.introspection import (
    get_columns as migration_get_columns,
)
from app.modules.db.models import EscalationPolicy, EscalationPolicyRule


db = init_database()


def _column_exists(table_name, column_name):
    columns = migration_get_columns(db, table_name)
    return any(column.name == column_name for column in columns)


def _is_sqlite():
    return db.__class__.__name__.lower().startswith("sqlite")


def _is_postgres():
    name = db.__class__.__name__.lower()
    return "postgres" in name or "postgre" in name


def _add_column_if_missing(table_name, column_name, sql):
    if _column_exists(table_name, column_name):
        return
    db.execute_sql(sql)


def upgrade():
    """Create escalation policy tables and references."""
    db.create_tables([EscalationPolicy, EscalationPolicyRule], safe=True)

    if _is_postgres():
        _upgrade_postgres()
    else:
        _upgrade_sqlite()


def downgrade():
    """Drop escalation policy references and tables."""
    if _is_postgres():
        _downgrade_postgres()
    else:
        _downgrade_sqlite()

    db.drop_tables([EscalationPolicyRule, EscalationPolicy], safe=True)


def _upgrade_sqlite():
    _add_column_if_missing(
        "alertroute",
        "escalation_policy_id",
        "ALTER TABLE alertroute ADD COLUMN escalation_policy_id INTEGER NULL REFERENCES escalation_policy(id) ON DELETE SET NULL",
    )
    _add_column_if_missing(
        "alert",
        "escalation_policy_id",
        "ALTER TABLE alert ADD COLUMN escalation_policy_id INTEGER NULL REFERENCES escalation_policy(id) ON DELETE SET NULL",
    )
    _add_column_if_missing(
        "alert",
        "escalation_rule_id",
        "ALTER TABLE alert ADD COLUMN escalation_rule_id INTEGER NULL REFERENCES escalation_policy_rule(id) ON DELETE SET NULL",
    )
    _add_column_if_missing(
        "alert",
        "next_escalation_at",
        "ALTER TABLE alert ADD COLUMN next_escalation_at DATETIME NULL",
    )
    _add_column_if_missing(
        "alert",
        "last_escalated_at",
        "ALTER TABLE alert ADD COLUMN last_escalated_at DATETIME NULL",
    )
    _add_column_if_missing(
        "alert",
        "escalation_repeat_count",
        "ALTER TABLE alert ADD COLUMN escalation_repeat_count INTEGER NOT NULL DEFAULT 0",
    )

    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS idx_alert_next_escalation_at ON alert(next_escalation_at)"
    )
    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS idx_alert_escalation_policy_id ON alert(escalation_policy_id)"
    )
    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS idx_alertroute_escalation_policy_id ON alertroute(escalation_policy_id)"
    )


def _upgrade_postgres():
    _add_column_if_missing(
        "alertroute",
        "escalation_policy_id",
        "ALTER TABLE alertroute ADD COLUMN escalation_policy_id INTEGER NULL REFERENCES escalation_policy(id) ON DELETE SET NULL",
    )
    _add_column_if_missing(
        "alert",
        "escalation_policy_id",
        "ALTER TABLE alert ADD COLUMN escalation_policy_id INTEGER NULL REFERENCES escalation_policy(id) ON DELETE SET NULL",
    )
    _add_column_if_missing(
        "alert",
        "escalation_rule_id",
        "ALTER TABLE alert ADD COLUMN escalation_rule_id INTEGER NULL REFERENCES escalation_policy_rule(id) ON DELETE SET NULL",
    )
    _add_column_if_missing(
        "alert",
        "next_escalation_at",
        "ALTER TABLE alert ADD COLUMN next_escalation_at TIMESTAMP NULL",
    )
    _add_column_if_missing(
        "alert",
        "last_escalated_at",
        "ALTER TABLE alert ADD COLUMN last_escalated_at TIMESTAMP NULL",
    )
    _add_column_if_missing(
        "alert",
        "escalation_repeat_count",
        "ALTER TABLE alert ADD COLUMN escalation_repeat_count INTEGER NOT NULL DEFAULT 0",
    )

    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS idx_alert_next_escalation_at ON alert(next_escalation_at)"
    )
    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS idx_alert_escalation_policy_id ON alert(escalation_policy_id)"
    )
    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS idx_alertroute_escalation_policy_id ON alertroute(escalation_policy_id)"
    )


def _downgrade_sqlite():
    # SQLite cannot reliably drop columns without rebuilding tables. Keep the
    # nullable columns for safe downgrade and remove only indexes/tables.
    db.execute_sql("DROP INDEX IF EXISTS idx_alert_next_escalation_at")
    db.execute_sql("DROP INDEX IF EXISTS idx_alert_escalation_policy_id")
    db.execute_sql("DROP INDEX IF EXISTS idx_alertroute_escalation_policy_id")


def _downgrade_postgres():
    db.execute_sql("DROP INDEX IF EXISTS idx_alert_next_escalation_at")
    db.execute_sql("DROP INDEX IF EXISTS idx_alert_escalation_policy_id")
    db.execute_sql("DROP INDEX IF EXISTS idx_alertroute_escalation_policy_id")
    db.execute_sql("ALTER TABLE alert DROP COLUMN IF EXISTS escalation_repeat_count")
    db.execute_sql("ALTER TABLE alert DROP COLUMN IF EXISTS last_escalated_at")
    db.execute_sql("ALTER TABLE alert DROP COLUMN IF EXISTS next_escalation_at")
    db.execute_sql("ALTER TABLE alert DROP COLUMN IF EXISTS escalation_rule_id")
    db.execute_sql("ALTER TABLE alert DROP COLUMN IF EXISTS escalation_policy_id")
    db.execute_sql("ALTER TABLE alertroute DROP COLUMN IF EXISTS escalation_policy_id")
