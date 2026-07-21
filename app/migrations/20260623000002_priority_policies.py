from app.db import init_database
from app.migrations.introspection import (
    get_columns as migration_get_columns,
)
from app.modules.db.models import MatcherPreset, PriorityPolicy, PriorityPolicyRule


db = init_database()


def _column_exists(table_name, column_name):
    return any(
        column.name == column_name
        for column in migration_get_columns(db, table_name)
    )


def _is_postgres():
    name = db.__class__.__name__.lower()
    return "postgres" in name or "postgre" in name


def _add_column_if_missing(table_name, column_name, sql):
    if _column_exists(table_name, column_name):
        return

    db.execute_sql(sql)


def upgrade():
    """Create priority policy tables and Service reference."""
    db.create_tables(
        [
            MatcherPreset,
            PriorityPolicy,
            PriorityPolicyRule,
        ],
        safe=True,
    )

    _add_column_if_missing(
        "service",
        "priority_policy_id",
        (
            "ALTER TABLE service "
            "ADD COLUMN priority_policy_id INTEGER NULL "
            "REFERENCES priority_policy(id) ON DELETE SET NULL"
        ),
    )

    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS "
        "idx_service_priority_policy_id "
        "ON service(priority_policy_id)"
    )


def downgrade():
    """Remove priority policy references and tables."""
    db.execute_sql(
        "DROP INDEX IF EXISTS idx_service_priority_policy_id"
    )

    if _is_postgres():
        db.execute_sql(
            "ALTER TABLE service "
            "DROP COLUMN IF EXISTS priority_policy_id"
        )

    db.drop_tables(
        [
            PriorityPolicyRule,
            PriorityPolicy,
            MatcherPreset,
        ],
        safe=True,
    )
