"""Upgrade storage without changing legacy alerts on either supported database."""

import importlib
from datetime import datetime, timedelta

import pytest
from peewee import IntegrityError, MySQLDatabase, SqliteDatabase
from playhouse.migrate import SqliteMigrator, migrate

from app.migrations.introspection import column_exists, table_exists
from app.modules.db.migrations import MigrationError, apply_migration
from app.modules.db.models import (
    Alert,
    AlertEvent,
    AlertGroup,
    AlertGroupEpisode,
    ApiToken,
    ChangeGraphState,
    Migration,
)
from tests.factories import create_group, create_team, unique


BASE = datetime(2026, 10, 1, 10)


@pytest.fixture
def migration(db):
    module = importlib.import_module(
        "app.migrations.20261028010000_change_intelligence_foundation"
    )
    with db.atomic() as transaction:
        yield module
        transaction.rollback()


def _group(**values):
    team = create_team(create_group())
    return AlertGroup.create(
        **(
            {
                "team": team,
                "source": "test",
                "title": "Historical group",
                "group_key": unique("episode"),
                "group_key_hash": unique("episode"),
                "first_seen_at": BASE,
                "last_seen_at": BASE,
            }
            | values
        )
    )


def _child(group, start=BASE, end=None):
    return Alert.create(
        group=group,
        team=group.team,
        source="test",
        title="Occurrence",
        dedup_key=unique("occurrence"),
        group_key=group.group_key,
        first_seen_at=start,
        last_seen_at=end or start,
        resolved_at=end,
        status="resolved" if end else "firing",
    )


def _event(group, event_type, at, child=None):
    return AlertEvent.create(
        group=group, alert=child, event_type=event_type, created_at=at
    )


def _drop_column(db, table, column):
    if isinstance(db, SqliteDatabase) and table == "apitoken":
        # Test-only reconstruction of the pre-migration schema, including its
        # table-level FK declaration. Production upgrade never rebuilds these tables.
        migrate(SqliteMigrator(db).drop_column(table, column, legacy=True))
        return
    for index in db.get_indexes(table):
        if column in index.columns:
            name = index.name.replace('"', '""')
            db.execute_sql(f'DROP INDEX "{name}"')
    db.execute_sql(f'ALTER TABLE "{table}" DROP COLUMN "{column}"')


def _legacy_schema(db, migration):
    _drop_column(db, "alert_group", "current_episode_id")
    _drop_column(db, "apitoken", "change_integration_id")
    db.drop_tables(list(reversed(migration.MODELS)))


def _assert_empty_storage(db, migration):
    for model in migration.MODELS:
        assert table_exists(db, model._meta.table_name)
        assert model.select().count() == (1 if model is ChangeGraphState else 0)
    assert ChangeGraphState.get_by_id(1).revision == 1


def test_upgrade_empty_schema_creates_storage_without_episodes(db, migration):
    _legacy_schema(db, migration)

    migration.upgrade()

    _assert_empty_storage(db, migration)
    assert column_exists(db, "alert_group", "current_episode_id")
    assert column_exists(db, "apitoken", "change_integration_id")


@pytest.mark.parametrize(
    "status",
    ["firing", "acknowledged", "silenced", "maintenance", "resolved", "merged"],
)
def test_upgrade_preserves_legacy_data_without_reconstructing_episodes(
    db, migration, status
):
    group = _group(
        status=status,
        resolved_at=BASE if status == "resolved" else None,
        merged_at=BASE if status == "merged" else None,
    )
    first = _child(group, end=BASE + timedelta(minutes=10))
    _event(group, "created", BASE)
    _event(group, "reopened", BASE + timedelta(minutes=3))  # ack -> firing
    _event(group, "resolved", first.resolved_at)
    second = _child(group, BASE + timedelta(minutes=20))
    _event(group, "reopened", second.first_seen_at, second)
    _event(group, "reopened", second.first_seen_at, second)  # duplicate history
    token = ApiToken.create(
        name="Legacy", token_prefix="old", token_hash=unique("hash")
    )
    models = (AlertGroup, Alert, AlertEvent, ApiToken)
    before = [list(model.select().order_by(model.id).dicts()) for model in models]
    _legacy_schema(db, migration)

    migration.upgrade()
    migration.upgrade()

    assert before == [
        list(model.select().order_by(model.id).dicts()) for model in models
    ]
    assert AlertGroup.get_by_id(group.id).current_episode_id is None
    assert ApiToken.get_by_id(token.id).change_integration_id is None
    _assert_empty_storage(db, migration)


def test_rerun_preserves_existing_episode_and_graph_revision(db, migration):
    group = _group()
    event = _event(group, "created", BASE)
    episode = AlertGroupEpisode.create(
        alert_group=group,
        ordinal=1,
        started_at=BASE,
        start_quality="exact",
        start_event=event,
    )
    group.current_episode = episode
    group.save()
    ChangeGraphState.update(revision=7).where(ChangeGraphState.id == 1).execute()
    before = dict(AlertGroupEpisode.get_by_id(episode.id).__data__)

    migration.upgrade()

    assert AlertGroupEpisode.select().count() == 1
    assert AlertGroupEpisode.get_by_id(episode.id).__data__ == before
    assert AlertGroup.get_by_id(group.id).current_episode_id == episode.id
    assert ChangeGraphState.get_by_id(1).revision == 7


def test_failure_rolls_back_schema_and_preserves_legacy_rows(
    db, migration, monkeypatch
):
    group = _group()
    child = _child(group)
    event = _event(group, "created", BASE)
    _legacy_schema(db, migration)

    def fail_initialization(*args, **kwargs):
        raise IntegrityError("injected initialization failure")

    with monkeypatch.context() as patch:
        patch.setattr(ChangeGraphState, "insert", fail_initialization)
        with pytest.raises(IntegrityError, match="injected"):
            migration.upgrade()

    assert all(
        not table_exists(db, model._meta.table_name) for model in migration.MODELS
    )
    assert not column_exists(db, "alert_group", "current_episode_id")
    assert not column_exists(db, "apitoken", "change_integration_id")
    assert db.execute_sql("SELECT id FROM alert_group").fetchall() == [(group.id,)]
    assert Alert.get_by_id(child.id).group_id == group.id
    assert AlertEvent.get_by_id(event.id).group_id == group.id

    migration.upgrade()

    _assert_empty_storage(db, migration)
    assert AlertGroup.get_by_id(group.id).current_episode_id is None


def test_event_cleanup_preserves_boundaries_but_group_cleanup_removes_unreviewed_episode(
    db, migration
):
    group = _group(status="resolved", resolved_at=BASE + timedelta(minutes=5))
    created = _event(group, "created", BASE)
    episode = AlertGroupEpisode.create(
        alert_group=group,
        ordinal=1,
        state="resolved",
        started_at=BASE,
        start_quality="exact",
        ended_at=group.resolved_at,
        start_event=created,
    )
    created.delete_instance()
    saved = AlertGroupEpisode.get_by_id(episode.id)
    assert saved.start_event_id is None and saved.started_at == BASE
    group.delete_instance()
    assert AlertGroupEpisode.select().count() == 0


def test_downgrade_refuses_to_destroy_history(db, migration):
    group = _group()
    episode = AlertGroupEpisode.create(alert_group=group, ordinal=1)
    with pytest.raises(RuntimeError, match="history"):
        migration.downgrade()
    assert AlertGroupEpisode.get_by_id(episode.id).alert_group_id == group.id


def test_runner_records_success_only_after_schema_and_initialization_commit(
    db, migration, monkeypatch
):
    name = "20261028010000_change_intelligence_foundation"
    _group()
    _legacy_schema(db, migration)
    Migration.delete().where(Migration.name == name).execute()

    def fail_initialization(*args, **kwargs):
        raise IntegrityError("injected initialization failure")

    with monkeypatch.context() as patch:
        patch.setattr(ChangeGraphState, "insert", fail_initialization)
        with pytest.raises(MigrationError, match="injected"):
            apply_migration(migration.__file__)
    assert not Migration.select().where(Migration.name == name).exists()
    assert not table_exists(db, "change_record")
    assert not column_exists(db, "alert_group", "current_episode_id")

    apply_migration(migration.__file__)
    apply_migration(migration.__file__)

    assert Migration.select().where(Migration.name == name).count() == 1
    _assert_empty_storage(db, migration)


def test_unsupported_backend_fails_before_schema_mutation(db, migration, monkeypatch):
    monkeypatch.setattr(migration, "init_database", lambda: MySQLDatabase("unused"))
    with pytest.raises(RuntimeError, match="PostgreSQL or SQLite"):
        migration.upgrade()
