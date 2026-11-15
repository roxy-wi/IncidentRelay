"""Add opt-in GitLab routing to existing Change sources."""

from app.db import init_database
from app.migrations.introspection import column_exists


def upgrade():
    """Keep existing sources generic and preserve their event history."""
    db = init_database()
    with db.atomic():
        if not column_exists(db, "change_source", "gitlab_mappings"):
            db.execute_sql(
                "ALTER TABLE change_source ADD COLUMN gitlab_mappings "
                "TEXT NOT NULL DEFAULT '[]'"
            )


def downgrade():
    """Retain routing configuration; older versions ignore the column."""
