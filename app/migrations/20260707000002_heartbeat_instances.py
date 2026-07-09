"""Add multi-instance heartbeat auto-discovery."""

from peewee import BooleanField, CharField, IntegerField
from playhouse.migrate import migrate

from app.db import init_database
from app.modules.db.migrator import get_migrator
from app.modules.db.models import Heartbeat, HeartbeatInstance, HeartbeatPing


db = init_database()
migrator = get_migrator(db)


def table_has_column(table_name, column_name):
    return any(column.name == column_name for column in db.get_columns(table_name))


def upgrade():
    heartbeat_table = Heartbeat._meta.table_name
    ping_table = HeartbeatPing._meta.table_name

    operations = []

    if not table_has_column(heartbeat_table, "instance_tracking_enabled"):
        operations.append(migrator.add_column(
            heartbeat_table,
            "instance_tracking_enabled",
            BooleanField(default=False),
        ))
    if not table_has_column(heartbeat_table, "instance_key"):
        operations.append(migrator.add_column(
            heartbeat_table,
            "instance_key",
            CharField(default="instance"),
        ))
    if not table_has_column(heartbeat_table, "expected_instances_mode"):
        operations.append(migrator.add_column(
            heartbeat_table,
            "expected_instances_mode",
            CharField(default="none"),
        ))
    if not table_has_column(heartbeat_table, "auto_discovery_ttl_days"):
        operations.append(migrator.add_column(
            heartbeat_table,
            "auto_discovery_ttl_days",
            IntegerField(null=True),
        ))
    if not table_has_column(ping_table, "instance_key"):
        operations.append(migrator.add_column(
            ping_table,
            "instance_key",
            CharField(null=True),
        ))

    if operations:
        migrate(*operations)

    db.create_tables([HeartbeatInstance], safe=True)


def downgrade():
    heartbeat_table = Heartbeat._meta.table_name
    ping_table = HeartbeatPing._meta.table_name

    db.drop_tables([HeartbeatInstance], safe=True)

    operations = []
    for column in (
        "auto_discovery_ttl_days",
        "expected_instances_mode",
        "instance_key",
        "instance_tracking_enabled",
    ):
        if table_has_column(heartbeat_table, column):
            operations.append(migrator.drop_column(heartbeat_table, column))

    if table_has_column(ping_table, "instance_key"):
        operations.append(migrator.drop_column(ping_table, "instance_key"))

    if operations:
        migrate(*operations)
