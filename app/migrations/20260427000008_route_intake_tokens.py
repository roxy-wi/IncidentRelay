from peewee import CharField
from playhouse.migrate import migrate

from app.db import init_database
from app.modules.db.migrator import get_migrator


db = init_database()
migrator = get_migrator(db)


def has_column(table_name, column_name):
    """
    Return True when a table already has a column.
    """

    return any(column.name == column_name for column in db.get_columns(table_name))


def upgrade():
    """
    Add alert intake token columns to routes.
    """

    operations = []

    if not has_column("alertroute", "intake_token_prefix"):
        operations.append(migrator.add_column("alertroute", "intake_token_prefix", CharField(null=True)))

    if not has_column("alertroute", "intake_token_hash"):
        operations.append(migrator.add_column("alertroute", "intake_token_hash", CharField(null=True)))

    if operations:
        migrate(*operations)


def downgrade():
    """
    Remove route alert intake token columns.
    """

    operations = []

    if has_column("alertroute", "intake_token_hash"):
        operations.append(migrator.drop_column("alertroute", "intake_token_hash"))

    if has_column("alertroute", "intake_token_prefix"):
        operations.append(migrator.drop_column("alertroute", "intake_token_prefix"))

    if operations:
        migrate(*operations)
