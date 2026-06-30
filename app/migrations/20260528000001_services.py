from peewee import IntegerField
from playhouse.migrate import migrate

from app.db import init_database
from app.modules.db.migrator import get_migrator
from app.modules.db.models import (
    Alert,
    AlertRoute,
    Service,
    ServiceChannel,
    ServiceDependency,
    ServiceRunbook,
    ServiceLink,
    ServiceMatchRule,
    MaintenanceWindow,
    MaintenanceWindowService,
    ServiceOwner,
    ServiceSli,
    ServiceSlo,
    ServiceSloMeasurement,
)

db = init_database()
migrator = get_migrator(db)


def table_has_column(table_name, column_name):
    return any(column.name == column_name for column in db.get_columns(table_name))


def upgrade():
    """Create service-related tables and link routes/alerts to services."""
    route_table = AlertRoute._meta.table_name
    alert_table = Alert._meta.table_name

    db.create_tables(
        [
            Service,
            ServiceChannel,
            ServiceDependency,
            ServiceRunbook,
            ServiceLink,
            MaintenanceWindow,
            MaintenanceWindowService,
            ServiceOwner,
            ServiceSli,
            ServiceSlo,
            ServiceSloMeasurement,
        ],
        safe=True,
    )

    operations = []

    if not table_has_column(route_table, "service_id"):
        operations.append(
            migrator.add_column(
                route_table,
                "service_id",
                IntegerField(null=True),
            )
        )

    if not table_has_column(alert_table, "service_id"):
        operations.append(
            migrator.add_column(
                alert_table,
                "service_id",
                IntegerField(null=True),
            )
        )

    if operations:
        migrate(*operations)

    db.create_tables(
        [
            ServiceMatchRule,
        ],
        safe=True,
    )

    db.execute_sql(
        f"CREATE INDEX IF NOT EXISTS {route_table}_service_id "
        f"ON {route_table}(service_id)"
    )
    db.execute_sql(
        f"CREATE INDEX IF NOT EXISTS {alert_table}_service_id "
        f"ON {alert_table}(service_id)"
    )


def downgrade():
    """Drop service-related tables and route/alert service links."""
    route_table = AlertRoute._meta.table_name
    alert_table = Alert._meta.table_name

    db.drop_tables(
        [
            ServiceMatchRule,
        ],
        safe=True,
    )

    operations = []

    if table_has_column(route_table, "service_id"):
        operations.append(migrator.drop_column(route_table, "service_id"))

    if table_has_column(alert_table, "service_id"):
        operations.append(migrator.drop_column(alert_table, "service_id"))

    if operations:
        migrate(*operations)

    db.drop_tables(
        [
            ServiceSloMeasurement,
            ServiceSlo,
            ServiceSli,
            ServiceOwner,
            MaintenanceWindowService,
            MaintenanceWindow,
            ServiceLink,
            ServiceRunbook,
            ServiceDependency,
            ServiceChannel,
            Service,
        ],
        safe=True,
    )
