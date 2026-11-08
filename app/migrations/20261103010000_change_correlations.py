"""Add opt-in correlation storage without reconstructing historical episodes."""

from app.db import init_database
from app.migrations.introspection import column_exists, is_postgres
from app.modules.db.models import ChangeAlertGroupCorrelation, ChangeImpact


def upgrade():
    """Use additive DDL so SQLite never rebuilds referenced catalog tables."""
    db = init_database()
    boolean = (
        "BOOLEAN NOT NULL DEFAULT FALSE"
        if is_postgres(db)
        else "INTEGER NOT NULL DEFAULT 0"
    )
    columns = (
        ("service", "change_correlation_enabled", boolean),
        ("service", "change_correlation_exclusions", "TEXT NOT NULL DEFAULT '[]'"),
        ("alert_group_episode", "correlation_context", "TEXT"),
        ("alert_group_episode", "correlation_service_id", "INTEGER"),
        (
            "alert_group_episode",
            "context_revision",
            "BIGINT NOT NULL DEFAULT 1 CHECK (context_revision > 0)",
        ),
    )
    with db.atomic():
        for table, column, definition in columns:
            if not column_exists(db, table, column):
                db.execute_sql(
                    f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}'
                )
        db.create_tables([ChangeImpact, ChangeAlertGroupCorrelation], safe=True)
        db.execute_sql(
            "CREATE INDEX IF NOT EXISTS episode_correlation_service_start "
            "ON alert_group_episode (correlation_service_id, started_at, id)"
        )
        db.execute_sql(
            "CREATE INDEX IF NOT EXISTS episode_correlation_start "
            "ON alert_group_episode (started_at, id)"
        )


def downgrade():
    """Retain recorded context and reviews during an application rollback."""
    # Older application code ignores additive fields and projection tables.
    # Dropping them would discard manual evidence once stage 8 is enabled.
