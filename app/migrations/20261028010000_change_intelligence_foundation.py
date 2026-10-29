"""Add Change Intelligence storage without reconstructing existing alert history."""

from peewee import SqliteDatabase
from playhouse.migrate import migrate

from app.db import init_database
from app.migrations.introspection import (
    column_exists,
    get_indexes,
    is_postgres,
    resolve_table_schema,
)
from app.modules.db.migrator import get_migrator
from app.modules.db.models import (
    AlertGroup,
    AlertGroupEpisode,
    ApiToken,
    Change,
    ChangeEvent,
    ChangeGrant,
    ChangeGraphState,
    ChangeIntegration,
    ChangeJob,
    ChangeService,
    ChangeServiceReference,
    ChangeSource,
)


MODELS = (
    ChangeIntegration,
    ChangeSource,
    ChangeGrant,
    Change,
    ChangeEvent,
    ChangeServiceReference,
    ChangeService,
    ChangeGraphState,
    ChangeJob,
    AlertGroupEpisode,
)


def _add_existing_table_fields(db):
    """Add nullable fields and complete the circular episode foreign key."""
    migrator = get_migrator(db)
    for model, field in (
        (ApiToken, ApiToken.change_integration),
        (AlertGroup, AlertGroup.current_episode),
    ):
        table = model._meta.table_name
        column = field.column_name
        if not column_exists(db, table, column):
            migrate(migrator.add_column(table, column, field))

    # Peewee deliberately omits DeferredForeignKey constraints from CREATE
    # TABLE to break the AlertGroup -> episode -> AlertEvent -> group cycle.
    schema = resolve_table_schema(db, "alert_group")
    foreign_keys = (
        db.get_foreign_keys("alert_group", schema=schema)
        if is_postgres(db)
        else db.get_foreign_keys("alert_group")
    )
    if any(key.column == "current_episode_id" for key in foreign_keys):
        return
    if is_postgres(db):
        db.execute_sql(
            "ALTER TABLE alert_group ADD CONSTRAINT alert_group_current_episode_fk "
            "FOREIGN KEY (current_episode_id) REFERENCES alert_group_episode (id) "
            "ON DELETE SET NULL"
        )
        return

    # Fresh installs already have an empty, unconstrained deferred column.
    # Replace only this unused column; never rebuild AlertGroup and cascade
    # away its existing children. An unexpected populated column needs review.
    if AlertGroup.select().where(AlertGroup.current_episode.is_null(False)).exists():
        raise RuntimeError(
            "Unconstrained current_episode_id contains data; refusing to replace it"
        )
    for index in get_indexes(db, "alert_group"):
        if "current_episode_id" in index.columns:
            if index.columns != ["current_episode_id"]:
                raise RuntimeError("Unexpected composite current_episode_id index")
            name = index.name.replace('"', '""')
            db.execute_sql(f'DROP INDEX "{name}"')
    if db.server_version < (3, 35, 0) and AlertGroup.select().exists():
        raise RuntimeError(
            "Repairing a populated, unconstrained current_episode_id requires SQLite 3.35+"
        )
    # On older SQLite Peewee rebuilds the table, which is safe only for the
    # empty bootstrap table. Ordinary upgrades add the missing column above.
    migrate(migrator.drop_column("alert_group", "current_episode_id"))
    migrate(
        migrator.add_column(
            "alert_group", "current_episode_id", AlertGroup.current_episode
        )
    )


def upgrade():
    """Create storage atomically, leaving existing alerts and events unchanged."""
    db = init_database()
    if not isinstance(db, SqliteDatabase) and not is_postgres(db):
        raise RuntimeError("Change Intelligence requires PostgreSQL or SQLite")
    with db.atomic():
        db.create_tables(MODELS, safe=True)
        _add_existing_table_fields(db)
        ChangeGraphState.insert(id=1, revision=1).on_conflict_ignore().execute()


def downgrade():
    """Refuse a destructive downgrade of accepted events or episode evidence."""
    raise RuntimeError(
        "Change Intelligence downgrade would remove history. "
        "Restore the pre-upgrade backup with compatible application code instead."
    )
