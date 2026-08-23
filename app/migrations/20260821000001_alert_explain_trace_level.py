from peewee import CharField
from playhouse.migrate import migrate

from app.db import init_database
from app.migrations.introspection import get_columns as migration_get_columns
from app.modules.db.migrator import get_migrator
from app.modules.db.models import AlertExplainTrace


db = init_database()
migrator = get_migrator(db)


def table_has_column(table_name, column_name):
    return any(
        column.name == column_name
        for column in migration_get_columns(db, table_name)
    )


def upgrade():
    """Record the effective detail level for persisted Explain traces."""
    table_name = AlertExplainTrace._meta.table_name

    if not table_has_column(table_name, "trace_level"):
        migrate(
            migrator.add_column(
                table_name,
                "trace_level",
                CharField(default="full"),
            )
        )

    db.execute_sql(
        f"UPDATE {table_name} "
        f"SET trace_level = 'full' "
        f"WHERE trace_level IS NULL OR trace_level = ''"
    )


def downgrade():
    """Remove Explain trace detail-level metadata."""
    table_name = AlertExplainTrace._meta.table_name

    if table_has_column(table_name, "trace_level"):
        migrate(migrator.drop_column(table_name, "trace_level"))
