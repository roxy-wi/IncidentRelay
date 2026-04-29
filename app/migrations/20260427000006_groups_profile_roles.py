from peewee import IntegerField
from playhouse.migrate import migrate

from app.db import init_database
from app.models import ApiToken, AuditLog, Group, NotificationChannel, Team, User, UserGroup
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
    Add groups, group membership roles and personal API tokens.

    Foreign-key columns are added as integer columns here because Peewee
    migrations cannot always add ForeignKeyField portably across SQLite,
    MySQL and PostgreSQL without explicit field metadata. The application
    models still use ForeignKeyField and map to these *_id columns normally.
    """

    db.create_tables([Group, UserGroup], safe=True)

    default_group, _ = Group.get_or_create(
        slug="default",
        defaults={
            "name": "Default",
            "description": "Default access group created during migration",
        },
    )

    operations = []

    if not has_column("team", "group_id"):
        operations.append(migrator.add_column("team", "group_id", IntegerField(null=True)))

    if not has_column("notificationchannel", "group_id"):
        operations.append(migrator.add_column("notificationchannel", "group_id", IntegerField(null=True)))

    if not has_column("apitoken", "user_id"):
        operations.append(migrator.add_column("apitoken", "user_id", IntegerField(null=True)))

    if not has_column("apitoken", "group_id"):
        operations.append(migrator.add_column("apitoken", "group_id", IntegerField(null=True)))

    if not has_column("auditlog", "group_id"):
        operations.append(migrator.add_column("auditlog", "group_id", IntegerField(null=True)))

    if not has_column("user", "active_group_id"):
        operations.append(migrator.add_column("user", "active_group_id", IntegerField(null=True)))

    if operations:
        migrate(*operations)

    Team.update(group=default_group).where(Team.group.is_null(True)).execute()
    NotificationChannel.update(group=default_group).where(NotificationChannel.group.is_null(True)).execute()

    for user in User.select():
        if user.is_admin:
            UserGroup.get_or_create(user=user, group=default_group, defaults={"role": "rw"})
        if not user.active_group_id:
            User.update(active_group=default_group).where(User.id == user.id).execute()


def downgrade():
    """
    Roll back groups and personal API token columns.
    """

    operations = []

    if has_column("user", "active_group_id"):
        operations.append(migrator.drop_column("user", "active_group_id"))

    if has_column("auditlog", "group_id"):
        operations.append(migrator.drop_column("auditlog", "group_id"))

    if has_column("apitoken", "group_id"):
        operations.append(migrator.drop_column("apitoken", "group_id"))

    if has_column("apitoken", "user_id"):
        operations.append(migrator.drop_column("apitoken", "user_id"))

    if has_column("notificationchannel", "group_id"):
        operations.append(migrator.drop_column("notificationchannel", "group_id"))

    if has_column("team", "group_id"):
        operations.append(migrator.drop_column("team", "group_id"))

    if operations:
        migrate(*operations)

    db.drop_tables([UserGroup, Group], safe=True)
