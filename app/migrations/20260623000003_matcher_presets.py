from app.db import init_database
from app.modules.db.models import MatcherPreset


db = init_database()


def _column_exists(table_name, column_name):
    return any(column.name == column_name for column in db.get_columns(table_name))


def _is_postgres():
    database_name = db.__class__.__name__.lower()
    return "postgres" in database_name or "postgre" in database_name


def _add_matcher_preset_column(table_name):
    if _is_postgres():
        db.execute_sql(
            f"ALTER TABLE {table_name} "
            "ADD COLUMN IF NOT EXISTS matcher_preset_id INTEGER NULL "
            "REFERENCES matcher_preset(id) ON DELETE RESTRICT"
        )
        return

    if _column_exists(table_name, "matcher_preset_id"):
        return

    db.execute_sql(
        f"ALTER TABLE {table_name} "
        "ADD COLUMN matcher_preset_id INTEGER NULL "
        "REFERENCES matcher_preset(id) ON DELETE RESTRICT"
    )


def upgrade():
    """Create matcher presets and add rule references."""
    db.create_tables([MatcherPreset], safe=True)

    _add_matcher_preset_column("notification_policy_rule")
    _add_matcher_preset_column("priority_policy_rule")

    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS "
        "idx_notification_policy_rule_matcher_preset_id "
        "ON notification_policy_rule(matcher_preset_id)"
    )

    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS "
        "idx_priority_policy_rule_matcher_preset_id "
        "ON priority_policy_rule(matcher_preset_id)"
    )


def downgrade():
    """Remove matcher preset references and table."""
    db.execute_sql(
        "DROP INDEX IF EXISTS "
        "idx_notification_policy_rule_matcher_preset_id"
    )

    db.execute_sql(
        "DROP INDEX IF EXISTS "
        "idx_priority_policy_rule_matcher_preset_id"
    )

    if not _is_postgres():
        return

    db.execute_sql(
        "ALTER TABLE notification_policy_rule "
        "DROP COLUMN IF EXISTS matcher_preset_id"
    )

    db.execute_sql(
        "ALTER TABLE priority_policy_rule "
        "DROP COLUMN IF EXISTS matcher_preset_id"
    )

    db.drop_tables([MatcherPreset], safe=True)
