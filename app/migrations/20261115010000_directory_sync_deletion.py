"""Retain imported intervals when a synchronization source is removed."""

from playhouse.migrate import migrate

from app.db import init_database
from app.migrations.introspection import column_exists, get_indexes
from app.modules.db.migrator import get_migrator
from app.modules.db.models import DirectorySyncSource


def upgrade():
    """Add source tombstones without changing existing schedules."""
    db = init_database()
    migrator = get_migrator(db)
    for field in (DirectorySyncSource.deleted, DirectorySyncSource.deleted_at):
        if not column_exists(db, "directory_sync_source", field.name):
            migrate(migrator.add_column("directory_sync_source", field.name, field))


def downgrade():
    """Refuse rollback while removed sources retain local schedule data."""
    db = init_database()
    if column_exists(db, "directory_sync_source", "deleted"):
        if DirectorySyncSource.select(DirectorySyncSource.id).where(DirectorySyncSource.deleted == True).exists():
            raise RuntimeError("Cannot remove source tombstones while deleted synchronization sources exist")
    migrator = get_migrator(db)
    for index in get_indexes(db, "directory_sync_source"):
        if "deleted" in index.columns:
            migrate(migrator.drop_index("directory_sync_source", index.name))
    for name in ("deleted_at", "deleted"):
        if column_exists(db, "directory_sync_source", name):
            migrate(migrator.drop_column("directory_sync_source", name))
