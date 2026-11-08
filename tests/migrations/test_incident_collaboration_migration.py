"""Exercise the 2.4 ownership cutover on SQLite and PostgreSQL."""

import importlib
from datetime import datetime

import pytest
from peewee import IntegrityError, MySQLDatabase

from app.migrations.introspection import get_columns
from app.modules.db.models import (
    AlertComment, AlertGroup, Incident, IncidentAlertGroupLink, IncidentEvent,
    IncidentResponder, IncidentStakeholder,
)
from tests.factories import (
    create_escalation_policy, create_group, create_rotation, create_team,
    create_user, unique,
)


@pytest.fixture
def migration(db):
    module = importlib.import_module(
        "app.migrations.20261025010000_incident_responders_stakeholders"
    )
    # Roll back the entire test schema, including DDL, even after a failure.
    with db.atomic() as transaction:
        yield module
        transaction.rollback()


def _legacy_tables(db):
    db.drop_tables([IncidentResponder, IncidentStakeholder])
    db.execute_sql('''CREATE TABLE incident_responder (
        id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL,
        target_type VARCHAR(255) NOT NULL, target_user_id INTEGER,
        target_team_id INTEGER, requested_by_id INTEGER, accepted_by_id INTEGER,
        target_rotation_id INTEGER, target_escalation_policy_id INTEGER,
        declined_by_id INTEGER,
        status VARCHAR(255), message TEXT, response_message TEXT,
        requested_at TIMESTAMP, responded_at TIMESTAMP, expires_at TIMESTAMP,
        notification_status VARCHAR(255), notification_error TEXT,
        created_at TIMESTAMP, updated_at TIMESTAMP
    )''')
    db.execute_sql('''CREATE TABLE incident_stakeholder (
        id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL, user_id INTEGER,
        email VARCHAR(255), display_name VARCHAR(255), role VARCHAR(255), source VARCHAR(255),
        active BOOLEAN, notify_on_created BOOLEAN, notify_on_priority_change BOOLEAN,
        notify_on_status_change BOOLEAN, notify_on_resolved BOOLEAN,
        notify_on_comment BOOLEAN, created_by_id INTEGER,
        created_at TIMESTAMP, updated_at TIMESTAMP
    )''')


def _insert(db, table, **values):
    names = ', '.join(f'"{name}"' for name in values)
    placeholders = ', '.join([db.param] * len(values))
    db.execute_sql(
        f'INSERT INTO "{table}" ({names}) VALUES ({placeholders})', list(values.values())
    )


def _context():
    team = create_team(create_group())
    incident = Incident.create(team=team, title="Upgrade fixture")
    user = create_user(group=team.group)
    return incident, user


def _link(incident, *, removed=False):
    alert_group = AlertGroup.create(
        team=incident.team, source="manual", title="Technical history",
        group_key=unique("legacy"), group_key_hash=unique("legacy"),
    )
    IncidentAlertGroupLink.create(
        incident=incident, alert_group=alert_group,
        removed_at=datetime(2026, 1, 1) if removed else None,
    )
    return alert_group


def _responder(db, row_id, group_id, user_id, **overrides):
    values = dict(
        id=row_id, group_id=group_id, target_type="user", target_user_id=user_id,
        status="accepted", requested_by_id=user_id, accepted_by_id=user_id,
        message="Please investigate", response_message="Investigating",
        requested_at=datetime(2026, 1, 1), responded_at=datetime(2026, 1, 2),
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 2),
        notification_status="sent",
    )
    _insert(db, "incident_responder", **(values | overrides))


def _stakeholder(db, row_id, group_id, user_id=None, **overrides):
    values = dict(
        id=row_id, group_id=group_id, user_id=user_id, role="observer", source="manual",
        active=True, created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 2),
        **{flag: False for flag in (
            "notify_on_created", "notify_on_priority_change", "notify_on_status_change",
            "notify_on_resolved", "notify_on_comment",
        )},
    )
    _insert(db, "incident_stakeholder", **(values | overrides))


def test_fresh_install_and_rerun(db, migration):
    db.drop_tables([IncidentResponder, IncidentStakeholder])
    report = migration.upgrade()
    assert report["legacy_responders"] == report["legacy_stakeholders"] == 0
    assert migration.upgrade() == {"already_applied": True}


def test_merge_preserves_actors_flags_history_and_technical_comments(db, migration):
    incident, user = _context()
    first, second = _link(incident), _link(incident)
    comment = AlertComment.create(group=first, user=user, body="Keep technical context")
    _legacy_tables(db)
    _responder(db, 40, first.id, user.id)
    _responder(db, 41, second.id, user.id, response_message="Second request accepted")
    _responder(db, 42, second.id, user.id, status="declined", accepted_by_id=None)
    _stakeholder(db, 70, first.id, user.id, notify_on_created=True)
    _stakeholder(db, 71, second.id, user.id, notify_on_resolved=True)
    _stakeholder(db, 72, second.id, user.id, role="executive")

    report = migration.upgrade()

    assert report["migrated_responders"] == 2
    assert report["merged_responders"] == 1
    assert report["migrated_stakeholders"] == 2
    assert report["merged_stakeholders"] == 1
    responder = IncidentResponder.get_by_id(40)
    assert responder.incident_id == incident.id
    assert responder.requested_by_id == responder.accepted_by_id == user.id
    assert responder.requested_at == datetime(2026, 1, 1)
    assert responder.message == "Please investigate"
    assert IncidentResponder.get_by_id(42).status == "declined"
    stakeholder = IncidentStakeholder.get_by_id(70)
    assert stakeholder.notify_on_created and stakeholder.notify_on_resolved
    assert not stakeholder.notify_on_comment
    assert IncidentStakeholder.get_by_id(72).role == "executive"
    history = list(IncidentEvent.select().where(IncidentEvent.incident == incident.id))
    assert {event.data["legacy_id"] for event in history} == {41, 71}
    assert history[0].message == "Second request accepted"
    assert AlertComment.get_by_id(comment.id).body == "Keep technical context"
    assert migration.upgrade() == {"already_applied": True}
    assert IncidentEvent.select().count() == 2
    # Also exercises sequence advancement on PostgreSQL.
    assert IncidentResponder.create(incident=incident, target_type="user").id > 42
    assert IncidentStakeholder.create(incident=incident).id > 72


def test_skip_missing_removed_and_ambiguous_links(db, migration):
    incident, user = _context()
    removed = _link(incident, removed=True)
    ambiguous = _link(incident)
    other = Incident.create(team=incident.team, title="Another Incident")
    IncidentAlertGroupLink.create(incident=other, alert_group=ambiguous)
    _legacy_tables(db)
    for row_id, group_id in enumerate((999999, removed.id, ambiguous.id), 1):
        _responder(db, row_id, group_id, user.id)
        _stakeholder(db, row_id, group_id, user.id)
    report = migration.upgrade()
    for key in ("responders", "stakeholders"):
        assert report[f"unmapped_{key}"] == 2
        assert report[f"ambiguous_{key}"] == 1
        assert report[f"migrated_{key}"] == 0
        assert report[f"legacy_{key}"] == sum(report[f"{prefix}_{key}"] for prefix in (
            "migrated", "merged", "unmapped", "ambiguous"
        ))


@pytest.mark.parametrize("inactive_first", [True, False])
def test_email_merge_does_not_enable_inactive_subscription_flags(db, migration, inactive_first):
    incident, _ = _context()
    first, second = _link(incident), _link(incident)
    _legacy_tables(db)
    _stakeholder(db, 1, first.id, email=" PERSON@Example.com ",
                 active=not inactive_first, notify_on_created=inactive_first)
    _stakeholder(db, 2, second.id, email="person@example.com",
                 active=inactive_first, notify_on_created=not inactive_first)
    migration.upgrade()
    row = IncidentStakeholder.get()
    assert row.email == "person@example.com"
    assert row.active
    assert not row.notify_on_created


@pytest.mark.parametrize("failure_point", ["row", "history", "index"])
def test_failure_rolls_back_tables_rows_and_history(db, migration, monkeypatch, failure_point):
    incident, user = _context()
    group = _link(incident)
    _legacy_tables(db)
    _responder(db, 10, group.id, user.id)
    _responder(db, 11, group.id, user.id)

    def fail(*args, **kwargs):
        raise IntegrityError("injected migration failure")

    if failure_point == "row":
        monkeypatch.setattr(IncidentResponder, "create", fail)
    elif failure_point == "history":
        monkeypatch.setattr(migration, "_merge_history", fail)
    else:
        monkeypatch.setattr(migration, "_create_indexes", fail)
    with pytest.raises(IntegrityError, match="injected"):
        migration.upgrade()
    assert "group_id" in {column.name for column in get_columns(db, "incident_responder")}
    assert db.execute_sql("SELECT COUNT(*) FROM incident_responder").fetchone()[0] == 2
    assert IncidentEvent.select().count() == 0
    monkeypatch.undo()
    assert migration.upgrade()["merged_responders"] == 1


def test_mixed_schema_is_rejected_without_dropping_tables(db, migration):
    db.drop_tables([IncidentStakeholder])
    with pytest.raises(RuntimeError, match="Incomplete"):
        migration.upgrade()
    assert "incident_id" in {column.name for column in get_columns(db, "incident_responder")}


@pytest.mark.parametrize("status", ["requested", "declined", "expired", "resolved"])
def test_non_assignment_requests_keep_distinct_history_and_metadata(db, migration, status):
    incident, user = _context()
    groups = [_link(incident), _link(incident)]
    _legacy_tables(db)
    for row_id, group in enumerate(groups, 1):
        _responder(
            db, row_id, group.id, user.id, status=status, accepted_by_id=None,
            declined_by_id=user.id if status == "declined" else None,
            expires_at=datetime(2026, 1, 3), notification_error="delivery failed",
        )
    report = migration.upgrade()
    assert report["migrated_responders"] == 2
    assert report["merged_responders"] == 0
    for row in IncidentResponder.select():
        assert row.status == status
        assert row.expires_at == datetime(2026, 1, 3)
        assert row.notification_error == "delivery failed"
        assert row.declined_by_id == (user.id if status == "declined" else None)


@pytest.mark.parametrize("target_type", ["team", "rotation", "escalation_policy"])
def test_collective_acceptance_has_concrete_actor_and_preserves_target(db, migration, target_type):
    incident, user = _context()
    target = incident.team if target_type == "team" else (
        create_rotation(incident.team) if target_type == "rotation"
        else create_escalation_policy(incident.team)
    )
    group = _link(incident)
    _legacy_tables(db)
    _responder(db, 1, group.id, None, target_type=target_type,
               accepted_by_id=user.id, **{f"target_{target_type}_id": target.id})
    migration.upgrade()
    row = IncidentResponder.get()
    assert row.target_type == target_type
    assert getattr(row, f"target_{target_type}_id") == target.id
    assert row.target_user_id == row.accepted_by_id == user.id


def test_duplicate_links_to_same_incident_remain_unambiguous(db, migration):
    incident, user = _context()
    group = _link(incident)
    IncidentAlertGroupLink.create(incident=incident, alert_group=group)
    _legacy_tables(db)
    _responder(db, 1, group.id, user.id)
    assert migration.upgrade()["migrated_responders"] == 1


def test_unique_indexes_survive_rerun_and_allow_historical_rows(db, migration):
    incident, user = _context()
    _legacy_tables(db)
    migration.upgrade()
    db.execute_sql('DROP INDEX "incident_responder_unique_commander"')
    db.execute_sql('DROP INDEX "incident_responder_unique_active_user_role"')
    migration.upgrade()
    IncidentResponder.create(incident=incident, target_type="user", target_user=user,
                              role="commander", status="accepted")
    with pytest.raises(IntegrityError), db.atomic():
        IncidentResponder.create(incident=incident, target_type="user",
                                  role="commander", status="accepted")
    IncidentResponder.create(incident=incident, target_type="user", target_user=user,
                              status="accepted")
    with pytest.raises(IntegrityError), db.atomic():
        IncidentResponder.create(incident=incident, target_type="user", target_user=user,
                                  status="accepted")
    IncidentResponder.create(incident=incident, target_type="user", target_user=user,
                              status="resolved")


def test_preflight_reports_eligible_and_skipped_counts_without_record_text(db, migration, capsys):
    incident, user = _context()
    mapped, removed = _link(incident), _link(incident, removed=True)
    _legacy_tables(db)
    _responder(db, 1, mapped.id, user.id, message="private responder text")
    _responder(db, 2, removed.id, user.id)
    report = migration.upgrade()
    assert report["eligible_responders"] == report["migrated_responders"] == 1
    assert report["unmapped_responders"] == 1
    output = capsys.readouterr().out
    assert "private responder text" not in output
    assert '"eligible_responders": 1' in output
    assert "preflight" in output and "reconciliation" in output


def test_unknown_schema_is_not_dropped(db, migration):
    db.drop_tables([IncidentResponder, IncidentStakeholder])
    db.execute_sql("CREATE TABLE incident_responder (id INTEGER PRIMARY KEY, unexpected TEXT)")
    with pytest.raises(RuntimeError, match="Unknown legacy"):
        migration.upgrade()
    assert "unexpected" in {column.name for column in get_columns(db, "incident_responder")}


def test_nontransactional_backend_is_rejected_before_connecting(migration, monkeypatch):
    database = MySQLDatabase("unused_migration_test")
    monkeypatch.setattr(migration, "init_database", lambda: database)
    with pytest.raises(RuntimeError, match="requires SQLite or PostgreSQL"):
        migration.upgrade()
    assert database.is_closed()


def test_hybrid_ownership_columns_are_rejected(db, migration):
    db.execute_sql('ALTER TABLE "incident_responder" ADD COLUMN "group_id" INTEGER')
    with pytest.raises(RuntimeError, match="Mixed collaboration ownership"):
        migration.upgrade()
    assert {"incident_id", "group_id"} <= {
        column.name for column in get_columns(db, "incident_responder")
    }


def test_deleted_accepting_user_is_not_replaced_with_requester(db, migration):
    incident, requester = _context()
    group = _link(incident)
    _legacy_tables(db)
    _responder(db, 1, group.id, None, target_type="team",
               target_team_id=incident.team_id, requested_by_id=requester.id,
               accepted_by_id=None)
    migration.upgrade()
    row = IncidentResponder.get()
    assert row.status == "accepted"
    assert row.target_user_id is None
    assert row.requested_by_id == requester.id
