from peewee import IntegerField
from playhouse.migrate import migrate

from app.db import init_database
from app.models import Group, User, UserGroup
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
    Add active_group_id to users.

    This migration is intentionally separate from the groups migration because
    some installations may already have applied the previous migration before
    active_group_id was introduced.
    """

    operations = []

    if not has_column("user", "active_group_id"):
        operations.append(migrator.add_column("user", "active_group_id", IntegerField(null=True)))

    if operations:
        migrate(*operations)

    default_group = Group.get_or_none(Group.slug == "default")

    if not default_group:
        default_group = Group.create(
            slug="default",
            name="Default",
            description="Default access group created during migration",
        )

    for user in User.select():
        if user.active_group_id:
            continue

        membership = (
            UserGroup.select()
            .where((UserGroup.user == user) & (UserGroup.active == True))
            .order_by(UserGroup.id.asc())
            .first()
        )

        if membership:
            User.update(active_group=membership.group).where(User.id == user.id).execute()
            continue

        if user.is_admin:
            UserGroup.get_or_create(user=user, group=default_group, defaults={"role": "rw"})


def downgrade():
    """
    Remove active_group_id from users.
    """

    if has_column("user", "active_group_id"):
        migrate(migrator.drop_column("user", "active_group_id"))
