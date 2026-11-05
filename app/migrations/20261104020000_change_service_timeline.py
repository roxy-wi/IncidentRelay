"""Add Change provenance without rebuilding or rewriting legacy timeline rows."""

from playhouse.migrate import migrate

from app.db import init_database
from app.migrations.introspection import (
    column_exists,
    get_indexes,
    is_postgres,
    resolve_table_schema,
)
from app.modules.db import changes_repo
from app.modules.db.migrator import get_migrator
from app.modules.db.models import ServiceEvent


def ensure_provenance_fk(db):
    """Complete the deferred FK after the older Service migration has run."""
    schema = resolve_table_schema(db, "service_event")
    foreign_keys = (
        db.get_foreign_keys("service_event", schema=schema)
        if is_postgres(db)
        else db.get_foreign_keys("service_event")
    )
    if any(key.column == "change_event_id" for key in foreign_keys):
        return False
    if is_postgres(db):
        db.execute_sql(
            "ALTER TABLE service_event ADD CONSTRAINT service_event_change_event_fk "
            "FOREIGN KEY (change_event_id) REFERENCES change_event (id) ON DELETE RESTRICT"
        )
        return False
    # Peewee bootstrap creates the deferred column without its constraint.
    # Replace only that unused column, never rebuild the populated event table.
    if db.execute_sql(
        "SELECT 1 FROM service_event WHERE change_event_id IS NOT NULL LIMIT 1"
    ).fetchone():
        raise RuntimeError(
            "Unconstrained Change provenance contains data; refusing to discard it"
        )
    if db.server_version < (3, 35, 0) and ServiceEvent.select().exists():
        raise RuntimeError(
            "Completing populated deferred Change provenance requires SQLite 3.35 or newer"
        )
    for index in get_indexes(db, "service_event"):
        if "change_event_id" in index.columns:
            if index.columns not in (
                ["change_event_id"],
                ["service_id", "change_event_id", "change_relation_type"],
            ):
                raise RuntimeError("Unexpected Change provenance index")
            name = index.name.replace('"', '""')
            db.execute_sql(f'DROP INDEX "{name}"')
    migrator = get_migrator(db)
    # As in the episode foundation migration, older SQLite may rebuild only
    # an empty bootstrap table; populated legacy event history is never rebuilt.
    migrate(migrator.drop_column("service_event", "change_event_id"))
    migrate(
        migrator.add_column(
            "service_event", "change_event_id", ServiceEvent.change_event
        )
    )
    return True


def upgrade():
    """Add nullable columns and queue a bounded revalidation of accepted Changes."""
    db = init_database()
    added = False
    with db.atomic():
        columns = (
            (
                "change_event_id",
                'INTEGER REFERENCES "change_event" ("id") ON DELETE RESTRICT',
            ),
            (
                "change_relation_type",
                "VARCHAR(32) CHECK (change_relation_type IN "
                "('changed', 'reported_affected', 'inferred_impact'))",
            ),
        )
        for column, definition in columns:
            if not column_exists(db, "service_event", column):
                db.execute_sql(
                    f'ALTER TABLE "service_event" ADD COLUMN "{column}" {definition}'
                )
                added = True
        added = ensure_provenance_fk(db) or added
        db.execute_sql(
            "CREATE INDEX IF NOT EXISTS serviceevent_change_event_id "
            "ON service_event (change_event_id)"
        )
        db.execute_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS serviceevent_service_id_change_event_id_change_relation_type "
            "ON service_event (service_id, change_event_id, change_relation_type)"
        )
        if added:
            changes_repo.request_job("discover_graph", 1)


def downgrade():
    """Keep immutable history; older application versions ignore these columns."""
