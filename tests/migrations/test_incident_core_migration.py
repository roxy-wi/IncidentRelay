from pathlib import Path

import pytest

from app.modules.db import migrations
from app.modules.db.models import (
    AlertGroup, IncidentComment, IncidentResponder, IncidentService,
    IncidentStakeholder,
    IncidentNotificationDelivery,
)
from tests.factories import create_group, create_team, unique


INCIDENT_CORE_MIGRATION = "20260917070000_incident_core"
INCIDENT_CORE_TABLES = (
    "incident",
    "incident_event",
    "incident_alert_group_link",
)


@pytest.fixture(autouse=True)
def isolated_core_schema(db):
    """Remove later dependants while testing the reversible 2.3 migration."""
    with db.atomic() as transaction:
        db.drop_tables([
            IncidentNotificationDelivery,
            IncidentComment, IncidentResponder, IncidentService, IncidentStakeholder,
        ])
        yield
        transaction.rollback()


def _load_migration():
    migration_path = Path(migrations.get_migrations_dir()) / (
        INCIDENT_CORE_MIGRATION + ".py"
    )
    return migrations.load_migration_module(str(migration_path))


def _assert_tables(db, expected):
    for table_name in INCIDENT_CORE_TABLES:
        assert db.table_exists(table_name) is expected


def test_incident_core_migration_upgrade_downgrade_and_rerun(db):
    upgrade, downgrade = _load_migration()
    assert downgrade is not None

    # Start from the fully migrated test schema, then exercise the 2.3
    # migration as an isolated reversible unit.
    _assert_tables(db, True)

    try:
        downgrade()
        _assert_tables(db, False)

        report = upgrade()
        _assert_tables(db, True)
        assert report["alert_groups_before"] == 0
        assert report["alert_groups_after"] == 0
        assert report["incidents_after"] == 0
        assert report["historical_incidents_backfilled"] == 0

        # safe=True is required because interrupted deployments can retry a
        # migration after DDL was already committed by the backend.
        upgrade()
        _assert_tables(db, True)

        downgrade()
        _assert_tables(db, False)

        # A repeated rollback must be safe for operator recovery workflows.
        downgrade()
        _assert_tables(db, False)
    finally:
        # Never leave the session-scoped migrated test database without the
        # Incident tables, even when one of the assertions above fails.
        upgrade()

    _assert_tables(db, True)


def test_incident_core_migration_preserves_existing_alert_groups(db):
    upgrade, downgrade = _load_migration()
    assert downgrade is not None

    group = create_group()
    team = create_team(group)
    key = unique("incident-core-migration")
    alert_group = AlertGroup.create(
        team=team,
        source="manual",
        group_key_hash=key,
        group_key=key,
        title="Existing technical history",
    )

    try:
        downgrade()
        _assert_tables(db, False)

        preserved = AlertGroup.get_by_id(alert_group.id)
        assert preserved.title == "Existing technical history"
        assert preserved.team_id == team.id

        report = upgrade()
        _assert_tables(db, True)
        assert report["alert_groups_before"] == 1
        assert report["alert_groups_after"] == 1
        assert report["incidents_after"] == 0
        assert report["historical_incidents_backfilled"] == 0

        preserved = AlertGroup.get_by_id(alert_group.id)
        assert preserved.title == "Existing technical history"
        assert preserved.team_id == team.id
    finally:
        upgrade()
