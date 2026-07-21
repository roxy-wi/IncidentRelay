from peewee import TextField
from playhouse.migrate import migrate

from app.db import init_database
from app.migrations.introspection import (
    get_columns as migration_get_columns,
)
from app.modules.db.migrator import get_migrator
from app.modules.db.models import AlertRoute


db = init_database()
migrator = get_migrator(db)


def table_has_column(table_name, column_name):
    return any(column.name == column_name for column in migration_get_columns(db, table_name))


def upgrade():
    route_table = AlertRoute._meta.table_name

    if not table_has_column(route_table, "integration_config"):
        migrate(
            migrator.add_column(
                route_table,
                "integration_config",
                TextField(null=True),
            )
        )


def downgrade():
    route_table = AlertRoute._meta.table_name

    if table_has_column(route_table, "integration_config"):
        migrate(
            migrator.drop_column(route_table, "integration_config")
        )
