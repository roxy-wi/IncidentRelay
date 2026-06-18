"""Add user timezone preference."""

from playhouse.migrate import migrate
from peewee import CharField

from app.db import init_database
from app.modules.db.migrator import get_migrator
from app.modules.db.models import User


db = init_database()
migrator = get_migrator(db)


def table_has_column(table_name, column_name):
    return any(
        column.name == column_name
        for column in db.get_columns(table_name)
    )


def upgrade():
    """Add nullable timezone preference to users."""
    user_table = User._meta.table_name

    if not table_has_column(user_table, "timezone"):
        migrate(
            migrator.add_column(
                user_table,
                "timezone",
                CharField(null=True),
            )
        )


def downgrade():
    """Remove nullable timezone preference from users."""
    user_table = User._meta.table_name

    if table_has_column(user_table, "timezone"):
        migrate(
            migrator.drop_column(
                user_table,
                "timezone",
            )
        )
