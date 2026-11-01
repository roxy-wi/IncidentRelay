"""Allow Group-owned integrations without delegating existing central identities."""

from peewee import SqliteDatabase
from playhouse.migrate import migrate

from app.db import init_database
from app.migrations.introspection import column_exists
from app.modules.db.migrator import get_migrator
from app.modules.db.models import ChangeIntegration


def upgrade():
    """Add nullable ownership; existing rows remain central (NULL)."""
    db = init_database()
    if not column_exists(db, "change_integration", "owner_group_id"):
        migrate(
            get_migrator(db).add_column(
                "change_integration", "owner_group_id", ChangeIntegration.owner_group
            )
        )


def downgrade():
    """Refuse to silently turn delegated identities into central integrations."""
    db = init_database()
    if not column_exists(db, "change_integration", "owner_group_id"):
        return
    if (
        ChangeIntegration.select()
        .where(ChangeIntegration.owner_group.is_null(False))
        .exists()
    ):
        raise RuntimeError("Cannot remove ownership while Group integrations exist")
    if isinstance(db, SqliteDatabase):
        # SQLite cannot drop a table-level FK without rebuilding this referenced
        # table. Older code ignores the nullable column; retain it to preserve
        # all source/event references during an application rollback.
        return
    migrate(get_migrator(db).drop_column("change_integration", "owner_group_id"))
