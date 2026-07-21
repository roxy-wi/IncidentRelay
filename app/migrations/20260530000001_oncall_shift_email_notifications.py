from datetime import datetime

from peewee import (
    AutoField,
    BooleanField,
    CharField,
    DateTimeField,
    ForeignKeyField,
    IntegerField,
    TextField,
)
from playhouse.migrate import migrate

from app.db import init_database
from app.migrations.introspection import (
    get_columns as migration_get_columns,
    get_tables as migration_get_tables,
)
from app.modules.db.migrator import get_migrator
from app.modules.db.models import BaseModel, Rotation, User


db = init_database()
migrator = get_migrator(db)


def table_has_column(table_name, column_name):
    return any(column.name == column_name for column in migration_get_columns(db, table_name))


def table_exists(table_name):
    return table_name in migration_get_tables(db)


class OnCallShiftEmailNotificationMigration(BaseModel):
    id = AutoField()

    user = ForeignKeyField(
        User,
        backref="oncall_shift_email_notifications",
        on_delete="CASCADE",
    )
    rotation = ForeignKeyField(
        Rotation,
        backref="oncall_shift_email_notifications",
        on_delete="CASCADE",
    )

    event_type = CharField(index=True)

    slot_start_at = DateTimeField(index=True)
    slot_end_at = DateTimeField(index=True)

    layer_id = IntegerField(null=True)
    override_id = IntegerField(null=True)

    fingerprint = CharField(unique=True, index=True)

    status = CharField(default="pending", index=True)
    last_error = TextField(null=True)

    created_at = DateTimeField(default=datetime.utcnow)
    sent_at = DateTimeField(null=True)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "oncall_shift_email_notification"
        database = db
        indexes = (
            (("user", "event_type", "slot_start_at", "slot_end_at"), False),
            (("rotation", "event_type", "slot_start_at"), False),
        )


def upgrade():
    """Add on-call shift email preferences and notification dedup table."""
    user_table = User._meta.table_name

    operations = []

    if not table_has_column(user_table, "notify_oncall_shift_start_email"):
        operations.append(
            migrator.add_column(
                user_table,
                "notify_oncall_shift_start_email",
                BooleanField(default=True),
            )
        )

    if not table_has_column(user_table, "notify_oncall_shift_end_email"):
        operations.append(
            migrator.add_column(
                user_table,
                "notify_oncall_shift_end_email",
                BooleanField(default=True),
            )
        )

    if operations:
        migrate(*operations)

    db.create_tables(
        [OnCallShiftEmailNotificationMigration],
        safe=True,
    )


def downgrade():
    """Drop on-call shift email notification table and user preferences."""
    user_table = User._meta.table_name

    if table_exists("oncall_shift_email_notification"):
        db.drop_tables(
            [OnCallShiftEmailNotificationMigration],
            safe=True,
        )

    operations = []

    if table_has_column(user_table, "notify_oncall_shift_start_email"):
        operations.append(
            migrator.drop_column(
                user_table,
                "notify_oncall_shift_start_email",
            )
        )

    if table_has_column(user_table, "notify_oncall_shift_end_email"):
        operations.append(
            migrator.drop_column(
                user_table,
                "notify_oncall_shift_end_email",
            )
        )

    if operations:
        migrate(*operations)
