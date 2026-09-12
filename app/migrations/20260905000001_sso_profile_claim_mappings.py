from peewee import TextField
from playhouse.migrate import migrate

from app.db import init_database
from app.migrations.introspection import get_columns as migration_get_columns
from app.modules.db.migrator import get_migrator
from app.modules.db.models import SsoProvider


db = init_database()
migrator = get_migrator(db)


def table_has_column(table_name, column_name):
    return any(
        column.name == column_name
        for column in migration_get_columns(db, table_name)
    )


def upgrade():
    """Add optional SSO claim mappings for user profile integration IDs."""
    table_name = SsoProvider._meta.table_name

    if not table_has_column(table_name, "profile_claim_mappings"):
        migrate(
            migrator.add_column(
                table_name,
                "profile_claim_mappings",
                TextField(null=True),
            )
        )


def downgrade():
    """Remove optional SSO profile claim mappings."""
    table_name = SsoProvider._meta.table_name

    if table_has_column(table_name, "profile_claim_mappings"):
        migrate(migrator.drop_column(table_name, "profile_claim_mappings"))
