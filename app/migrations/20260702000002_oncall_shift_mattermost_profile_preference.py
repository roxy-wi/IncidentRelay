"""Add personal preference for Mattermost on-call shift notifications."""

from peewee import BooleanField
from playhouse.migrate import migrate

from app.db import init_database
from app.modules.db.migrator import get_migrator
from app.modules.db.models import User


db = init_database()
migrator = get_migrator(db)


def table_has_column(table_name, column_name):
    """Return True if table already has column."""
    return any(column.name == column_name for column in db.get_columns(table_name))


def upgrade():
    """Add Mattermost shift start notification preference to users."""
    user_table = User._meta.table_name

    if table_has_column(user_table, "notify_oncall_shift_start_mattermost"):
        return

    migrate(
        migrator.add_column(
            user_table,
            "notify_oncall_shift_start_mattermost",
            BooleanField(default=True),
        )
    )


def downgrade():
    """Remove Mattermost shift start notification preference from users."""
    user_table = User._meta.table_name

    if not table_has_column(user_table, "notify_oncall_shift_start_mattermost"):
        return

    migrate(
        migrator.drop_column(
            user_table,
            "notify_oncall_shift_start_mattermost",
        )
    )
