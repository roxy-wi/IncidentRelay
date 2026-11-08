"""Preserve manual Incident links and allow unscored manual episode relations."""

from playhouse.migrate import SchemaMigrator, migrate

from app.db import init_database
from app.migrations.introspection import get_columns
from app.modules.db.models import ChangeIncidentLink


def upgrade():
    """Retain existing suggestions; manual relations never invent a score."""
    db = init_database()
    with db.atomic():
        score = next(
            column
            for column in get_columns(db, "change_alert_group_correlation")
            if column.name == "score"
        )
        if not score.null:
            migrate(
                SchemaMigrator.from_database(db).drop_not_null(
                    "change_alert_group_correlation", "score"
                )
            )
        db.create_tables([ChangeIncidentLink], safe=True)


def downgrade():
    """Keep manual decisions and links when rolling back application code."""
