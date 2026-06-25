from peewee import CharField, IntegerField
from playhouse.migrate import migrate

from app.db import init_database
from app.modules.db.migrator import get_migrator
from app.modules.db.models import (
    AlertRoute,
    NotificationPolicy,
    NotificationPolicyRule,
    NotificationPolicyRuleChannel,
    Service,
)


db = init_database()
migrator = get_migrator(db)


def table_has_column(table_name, column_name):
    return any(
        column.name == column_name
        for column in db.get_columns(table_name)
    )


def upgrade():
    """Create notification policy tables and resource links."""
    db.create_tables(
        [
            NotificationPolicy,
            NotificationPolicyRule,
            NotificationPolicyRuleChannel,
        ],
        safe=True,
    )

    service_table = Service._meta.table_name
    route_table = AlertRoute._meta.table_name

    operations = []

    if not table_has_column(
        service_table,
        "notification_policy_id",
    ):
        operations.append(
            migrator.add_column(
                service_table,
                "notification_policy_id",
                IntegerField(null=True),
            )
        )

    if not table_has_column(
        route_table,
        "notification_channel_mode",
    ):
        operations.append(
            migrator.add_column(
                route_table,
                "notification_channel_mode",
                CharField(default="route_only"),
            )
        )

    if operations:
        migrate(*operations)

    db.execute_sql(
        f"CREATE INDEX IF NOT EXISTS "
        f"{service_table}_notification_policy_id "
        f"ON {service_table}(notification_policy_id)"
    )

    db.execute_sql(
        f"CREATE INDEX IF NOT EXISTS "
        f"{route_table}_notification_channel_mode "
        f"ON {route_table}(notification_channel_mode)"
    )

    # Explicitly preserve current behavior for all existing routes.
    db.execute_sql(
        f"UPDATE {route_table} "
        f"SET notification_channel_mode = 'route_only' "
        f"WHERE notification_channel_mode IS NULL "
        f"OR notification_channel_mode = ''"
    )


def downgrade():
    """Remove notification policy tables and resource links."""
    service_table = Service._meta.table_name
    route_table = AlertRoute._meta.table_name

    operations = []

    if table_has_column(
        service_table,
        "notification_policy_id",
    ):
        operations.append(
            migrator.drop_column(
                service_table,
                "notification_policy_id",
            )
        )

    if table_has_column(
        route_table,
        "notification_channel_mode",
    ):
        operations.append(
            migrator.drop_column(
                route_table,
                "notification_channel_mode",
            )
        )

    if operations:
        migrate(*operations)

    db.drop_tables(
        [
            NotificationPolicyRuleChannel,
            NotificationPolicyRule,
            NotificationPolicy,
        ],
        safe=True,
    )
