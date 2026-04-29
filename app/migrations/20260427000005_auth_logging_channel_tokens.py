from datetime import datetime

from peewee import CharField
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
    Add JWT password hashes and per-channel alert intake tokens.
    """

    operations = []

    if not has_column("user", "password_hash"):
        operations.append(migrator.add_column("user", "password_hash", CharField(null=True)))

    if operations:
        migrate(*operations)

    db.create_tables([Version], safe=True)
    Version.get_or_create(version=get_service_version())
    Version.update(updated_at=datetime.utcnow()).where(Version.version == get_service_version()).execute()


def downgrade():
    """
    Remove JWT password hashes and per-channel alert intake tokens.
    """

    operations = []

    if has_column("user", "password_hash"):
        operations.append(migrator.drop_column("user", "password_hash"))

    if operations:
        migrate(*operations)
