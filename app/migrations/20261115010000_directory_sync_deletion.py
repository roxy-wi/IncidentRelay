"""Retain imported intervals when a synchronization source is removed."""

from peewee import SqliteDatabase
from playhouse.migrate import migrate

from app.db import init_database
from app.migrations.introspection import column_exists, get_indexes
from app.modules.db.migrator import get_migrator
from app.modules.db.models import DirectorySyncSource


def upgrade():
    """Add source tombstones without changing existing schedules."""
    db = init_database()
    if isinstance(db, SqliteDatabase):
        # Peewee adds NOT NULL in a second step by rebuilding the parent table.
        # With foreign_keys=ON, DROP TABLE cascades to bindings, shifts and duty.
        with db.atomic():
            for name, definition in (("deleted", "INTEGER NOT NULL DEFAULT 0"), ("deleted_at", "DATETIME")):
                if not column_exists(db, "directory_sync_source", name):
                    db.execute_sql(f'ALTER TABLE "directory_sync_source" ADD COLUMN "{name}" {definition}')
            if not any(index.columns == ["deleted"] for index in get_indexes(db, "directory_sync_source")):
                db.execute_sql('CREATE INDEX "directory_sync_source_deleted" ON "directory_sync_source" ("deleted")')
        return
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
            if isinstance(db, SqliteDatabase):
                # Native DROP COLUMN preserves the parent table and its children.
                db.execute_sql(f'ALTER TABLE "directory_sync_source" DROP COLUMN "{name}"')
            else:
                migrate(migrator.drop_column("directory_sync_source", name))
