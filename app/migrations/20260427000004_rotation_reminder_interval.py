from datetime import datetime

from peewee import IntegerField
from playhouse.migrate import migrate

from app.db import init_database
from app.models import Version
from app.modules.db.migrator import get_migrator
from app.version import get_service_version


db = init_database()
migrator = get_migrator(db)


def has_column(table_name, column_name):
    """
    Return True when a table already has a column.
    """

    return any(column.name == column_name for column in db.get_columns(table_name))


def upgrade():
    """
    Add per-rotation reminder interval settings.
    """

    if not has_column("rotation", "reminder_interval_seconds"):
        migrate(
            migrator.add_column(
                "rotation",
                "reminder_interval_seconds",
                IntegerField(default=300),
            )
        )

    db.create_tables([Version], safe=True)
    Version.get_or_create(version=get_service_version())
    Version.update(updated_at=datetime.utcnow()).where(Version.version == get_service_version()).execute()


def downgrade():
    """
    Remove per-rotation reminder interval settings.
    """

    if has_column("rotation", "reminder_interval_seconds"):
        migrate(migrator.drop_column("rotation", "reminder_interval_seconds"))
