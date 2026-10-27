"""Fault injection for Incident writes, snapshots and responder assignments."""

from datetime import timedelta
from unittest.mock import Mock

import pytest
from peewee import IntegrityError, OperationalError

from app.login import create_access_token
from app.modules.common import utc_now
from app.modules.db import audit_repo, incident_core_repo, incidents_repo
from app.modules.db.models import (
    AlertGroup,
    AuditLog,
    Incident,
    IncidentAlertGroupLink,
    IncidentEvent,
    IncidentResponder,
    IncidentService,
    IncidentStakeholder,
    ServiceOwner,
)
from app.services.incidents import core, responders, stakeholders
from tests.factories import (
    add_user_to_team,
    create_escalation_policy,
    create_group,
    create_rotation,
    create_service,
    create_team,
    create_user,
    unique,
)


@pytest.fixture(autouse=True)
def notifications(monkeypatch):
    declared = Mock(return_value=0)
    requested = Mock(return_value={"sent": 1})
    monkeypatch.setattr(stakeholders, "notify_stakeholders", declared)
    monkeypatch.setattr(responders, "notify_incident_responder_requested", requested)
    return declared, requested


def _context():
    team = create_team(create_group())
    actor = create_user(group=team.group, is_admin=True)
    return team, actor


def _technical_group(team, service=None):
    return AlertGroup.create(
        team=team,
        service=service,
        source="manual",
        title="Technical group",
        group_key=unique("group"),
        group_key_hash=unique("hash"),
    )


def _inject_failure(monkeypatch, point):
    def fail(*args, **kwargs):
        exception = IntegrityError if point == "audit_integrity" else OperationalError
        raise exception("injected database failure")

    if point == "event":
        monkeypatch.setattr(incident_core_repo, "create_event", fail)
    else:
        monkeypatch.setattr(audit_repo, "create_audit_log", fail)


@pytest.mark.parametrize("failure_point", ["snapshot", "event", "audit"])
def test_declaration_rolls_back_incident_snapshot_event_and_audit(
    db,
    monkeypatch,
    notifications,
    failure_point,
):
    team, actor = _context()
    service = create_service(team)
    for user in (actor, create_user(group=team.group)):
        ServiceOwner.create(service=service, user=user)
    if failure_point == "snapshot":
        original_create = IncidentStakeholder.create
        created = []

        def fail_second_snapshot(**values):
            if created:
                raise OperationalError("injected database failure")
            row = original_create(**values)
            created.append(row.id)
            return row

        monkeypatch.setattr(IncidentStakeholder, "create", fail_second_snapshot)
    else:
        _inject_failure(monkeypatch, failure_point)

    with pytest.raises(OperationalError, match="injected"):
        core.create_incident(
            team_id=team.id,
            service_id=service.id,
            title="Atomic declaration",
            user_id=actor.id,
        )
    assert Incident.select().count() == 0
    assert IncidentStakeholder.select().count() == 0
    assert IncidentEvent.select().count() == 0
    assert AuditLog.select().count() == 0
    notifications[0].assert_not_called()


@pytest.mark.parametrize(
    "operation", ["update", "assign", "transition", "link", "unlink"]
)
@pytest.mark.parametrize("failure_point", ["event", "audit"])
def test_incident_operations_roll_back_when_history_write_fails(
    db,
    monkeypatch,
    operation,
    failure_point,
):
    team, actor = _context()
    incident = Incident.create(team=team, title="Original")
    group = _technical_group(team)
    if operation == "unlink":
        IncidentAlertGroupLink.create(incident=incident, alert_group=group)
    before = Incident.get_by_id(incident.id).__data__.copy()
    _inject_failure(monkeypatch, failure_point)

    with pytest.raises(OperationalError, match="injected"):
        if operation == "update":
            core.update_incident(incident.id, expected_version=1, title="Changed")
        elif operation == "assign":
            core.assign_incident(incident.id, expected_version=1, assignee_id=actor.id)
        elif operation == "transition":
            core.transition_incident(incident.id, "investigating", expected_version=1)
        elif operation == "link":
            core.link_alert_group(incident.id, group.id)
        else:
            core.unlink_alert_group(incident.id, group.id)
    assert Incident.get_by_id(incident.id).__data__ == before
    assert IncidentEvent.select().count() == AuditLog.select().count() == 0
    links = list(IncidentAlertGroupLink.select())
    assert len(links) == (1 if operation == "unlink" else 0)
    if links:
        assert links[0].removed_at is None


def test_failed_primary_link_does_not_leave_incident_or_send_notification(
    db,
    notifications,
):
    team, actor = _context()
    service = create_service(team)
    ServiceOwner.create(service=service, user=actor)
    group = _technical_group(team, service)
    existing = Incident.create(team=team, title="Existing owner")
    IncidentAlertGroupLink.create(incident=existing, alert_group=group)

    with pytest.raises(core.IncidentConflictError):
        core.create_incident_from_alert_group(group.id, user_id=actor.id)
    assert [row.id for row in Incident.select()] == [existing.id]
    assert IncidentStakeholder.select().count() == 0
    assert IncidentEvent.select().count() == AuditLog.select().count() == 0
    notifications[0].assert_not_called()


def test_notification_observes_committed_primary_link_and_snapshot(db, notifications):
    team, actor = _context()
    service = create_service(team)
    ServiceOwner.create(service=service, user=actor)
    group = _technical_group(team, service)

    def check_commit(incident, *args, **kwargs):
        assert not db.in_transaction()
        assert (
            IncidentAlertGroupLink.select()
            .where(
                IncidentAlertGroupLink.incident == incident.id,
            )
            .count()
            == 1
        )
        assert IncidentStakeholder.select().count() == 1
        assert IncidentEvent.select().count() == AuditLog.select().count() == 2

    notifications[0].side_effect = check_commit
    core.create_incident_from_alert_group(group.id, user_id=actor.id)
    notifications[0].assert_called_once()


@pytest.mark.parametrize("operation", ["request", "accept", "expire"])
@pytest.mark.parametrize("failure_point", ["event", "audit", "audit_integrity"])
def test_responder_write_and_history_are_atomic(
    db,
    monkeypatch,
    notifications,
    operation,
    failure_point,
):
    team, actor = _context()
    incident = Incident.create(team=team, title="Responder transaction")
    row = None
    if operation != "request":
        row = IncidentResponder.create(
            incident=incident,
            target_type="user",
            target_user=actor,
            expires_at=utc_now()
            + timedelta(minutes=-1 if operation == "expire" else 10),
        )
    _inject_failure(monkeypatch, failure_point)
    exception = (
        IntegrityError if failure_point == "audit_integrity" else OperationalError
    )
    with pytest.raises(exception, match="injected"):
        if operation == "request":
            responders.create_incident_responder(
                incident_id=incident.id,
                user_id=actor.id,
                payload={"target_type": "user", "target_user_id": actor.id},
            )
        elif operation == "accept":
            responders.set_incident_responder_status(
                incident_id=incident.id,
                responder_id=row.id,
                status="accepted",
                user=actor,
            )
        else:
            responders.expire_due_incident_responders()
    assert IncidentResponder.select().count() == (0 if operation == "request" else 1)
    if row:
        unchanged = IncidentResponder.get_by_id(row.id)
        assert unchanged.status == "requested"
        assert unchanged.accepted_by_id is None
        assert unchanged.responded_at is None
    assert IncidentEvent.select().count() == AuditLog.select().count() == 0
    notifications[1].assert_not_called()


def test_responder_notification_runs_after_event_and_audit_commit(db, notifications):
    team, actor = _context()
    incident = Incident.create(team=team, title="Commit before delivery")

    def check_commit(row):
        assert not db.in_transaction()
        assert row.status == "requested"
        assert IncidentEvent.select().count() == AuditLog.select().count() == 1

    notifications[1].side_effect = check_commit
    responders.create_incident_responder(
        incident_id=incident.id,
        user_id=actor.id,
        payload={"target_type": "user", "target_user_id": actor.id},
    )
    notifications[1].assert_called_once()


@pytest.mark.parametrize("target_type", ["team", "rotation", "escalation_policy"])
def test_collective_acceptance_assigns_concrete_actor_once(client, db, target_type):
    team, requester = _context()
    actor = create_user(group=team.group, group_role="viewer")
    add_user_to_team(team, actor, role="viewer")
    target_team = create_team(team.group)
    add_user_to_team(target_team, actor, role="responder")
    target = (
        target_team
        if target_type == "team"
        else (
            create_rotation(target_team, users=[actor])
            if target_type == "rotation"
            else create_escalation_policy(target_team)
        )
    )
    incident = Incident.create(team=team, title="Collective request")
    row = responders.create_incident_responder(
        incident_id=incident.id,
        user_id=requester.id,
        payload={"target_type": target_type, f"target_{target_type}_id": target.id},
    )
    token, _ = create_access_token(actor)
    headers = {"Authorization": f"Bearer {token}"}
    url = f"/api/incidents/{incident.id}/responders/{row.id}"
    first = client.put(
        url, headers=headers, json={"status": "accepted", "response_message": "Joining"}
    )
    assert first.status_code == 200, first.json
    second = client.put(
        url, headers=headers, json={"status": "accepted", "response_message": "Retry"}
    )
    assert second.status_code == 200, second.json
    current = IncidentResponder.get_by_id(row.id)
    assert current.target_user_id == current.accepted_by_id == actor.id
    assert current.requested_by_id == requester.id
    assert current.target_type == target_type
    assert getattr(current, f"target_{target_type}_id") == target.id
    assert current.response_message == "Joining"
    assert (
        IncidentEvent.select()
        .where(IncidentEvent.event_type == "responder_accepted")
        .count()
        == 1
    )
    assert (
        AuditLog.select().where(AuditLog.action == "incident.responder.status").count()
        == 1
    )
    participants = client.get(
        f"/api/incidents/{incident.id}/participants", headers=headers
    )
    assert participants.json[0]["user_id"] == actor.id


def test_accepting_for_another_user_keeps_assignee_and_original_actor(db):
    team, actor = _context()
    assignee = create_user(group=team.group)
    incident = Incident.create(team=team, title="Acting for another user")
    row = IncidentResponder.create(
        incident=incident,
        target_type="user",
        target_user=assignee,
    )
    accepted = responders.set_incident_responder_status(
        incident_id=incident.id,
        responder_id=row.id,
        status="accepted",
        user=actor,
    )
    retried = responders.set_incident_responder_status(
        incident_id=incident.id,
        responder_id=row.id,
        status="accepted",
        user=assignee,
    )
    assert retried.target_user_id == assignee.id
    assert retried.accepted_by_id == actor.id
    assert retried.responded_at == accepted.responded_at
    assert IncidentEvent.get().user_id == AuditLog.get().user_id == actor.id


def test_expired_request_is_rejected_and_sweeper_records_it_once(
    client, db, admin_headers
):
    team, actor = _context()
    incident = Incident.create(team=team, title="Expired")
    row = IncidentResponder.create(
        incident=incident,
        target_type="user",
        target_user=actor,
        expires_at=utc_now() - timedelta(seconds=1),
    )
    response = client.put(
        f"/api/incidents/{incident.id}/responders/{row.id}",
        headers=admin_headers,
        json={"status": "accepted"},
    )
    assert response.status_code == 409
    assert IncidentResponder.get_by_id(row.id).status == "requested"
    assert responders.expire_due_incident_responders()["expired"] == 1
    assert responders.expire_due_incident_responders()["expired"] == 0
    assert IncidentEvent.get().event_type == "responder_expired"
    assert AuditLog.get().data["status"] == "expired"


@pytest.mark.parametrize("reason", ["state", "deadline"])
def test_status_compare_and_swap_rejects_stale_write(db, reason):
    team, actor = _context()
    incident = Incident.create(team=team, title="Stale update")
    row = IncidentResponder.create(
        incident=incident,
        target_type="user",
        target_user=actor,
        status="accepted" if reason == "state" else "requested",
        expires_at=utc_now() - timedelta(seconds=1) if reason == "deadline" else None,
    )
    with pytest.raises(incident_core_repo.IncidentConflictError):
        incidents_repo.update_incident_responder_status(
            row.id,
            "declined",
            expected_status="requested",
            user_id=actor.id,
        )
    assert IncidentResponder.get_by_id(row.id).status == row.status


@pytest.mark.parametrize(
    "collection", ["participants", "stakeholders", "affected-services"]
)
@pytest.mark.parametrize("operation", ["add", "remove"])
def test_collaboration_api_rolls_back_on_audit_error(
    client,
    db,
    admin_headers,
    monkeypatch,
    caplog,
    collection,
    operation,
):
    team, actor = _context()
    incident = Incident.create(team=team, title="Atomic API write")
    service = create_service(team)
    url = f"/api/incidents/{incident.id}/{collection}"
    if collection == "participants":
        payload = {"user_id": actor.id, "role": "commander"}
        model = IncidentResponder
    elif collection == "stakeholders":
        payload = {"user_id": actor.id}
        model = IncidentStakeholder
    else:
        payload = {"service_id": service.id}
        model = IncidentService
    before = None
    if operation == "remove":
        response = client.post(url, headers=admin_headers, json=payload)
        assert response.status_code == 201, response.json
        row_id = response.json["id"]
        before = model.get_by_id(row_id).__data__.copy()
        url += f"/{service.id if collection == 'affected-services' else row_id}"
    events_before = IncidentEvent.select().count()
    audits_before = AuditLog.select().count()
    _inject_failure(monkeypatch, "audit")
    if operation == "add":
        response = client.post(url, headers=admin_headers, json=payload)
    else:
        response = client.delete(url, headers=admin_headers)
    assert response.status_code == 500
    assert "injected database failure" in caplog.text
    if operation == "add":
        assert model.select().count() == 0
    else:
        assert model.get_by_id(row_id).__data__ == before
    assert IncidentEvent.select().count() == events_before
    assert AuditLog.select().count() == audits_before


@pytest.mark.parametrize("operation", ["assign", "accept"])
def test_database_uniqueness_conflict_recovers_savepoint(
    client,
    db,
    admin_headers,
    monkeypatch,
    operation,
):
    team, actor = _context()
    incident = Incident.create(team=team, title="Unique assignment")
    IncidentResponder.create(
        incident=incident,
        target_type="user",
        target_user=actor,
        role="responder",
        status="accepted",
    )
    pending = IncidentResponder.create(
        incident=incident,
        target_type="team",
        target_team=team,
    )
    actual_check = incidents_repo.has_participant_conflict
    first_check = True

    def stale_check(*args, **kwargs):
        nonlocal first_check
        if first_check:
            first_check = False
            return False
        return actual_check(*args, **kwargs)

    # Force the real unique index to reject the write, as with a stale precheck.
    monkeypatch.setattr(incidents_repo, "has_participant_conflict", stale_check)
    if operation == "assign":
        response = client.post(
            f"/api/incidents/{incident.id}/participants",
            headers=admin_headers,
            json={"user_id": actor.id, "role": "responder"},
        )
    else:
        token, _ = create_access_token(actor)
        response = client.put(
            f"/api/incidents/{incident.id}/responders/{pending.id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"status": "accepted"},
        )
    assert response.status_code == 409, response.json
    assert IncidentResponder.get_by_id(pending.id).status == "requested"
    assert IncidentEvent.select().count() == AuditLog.select().count() == 0
    # A different role still succeeds; the failed statement did not poison the
    # PostgreSQL transaction or the next request on this database connection.
    following = client.post(
        f"/api/incidents/{incident.id}/participants",
        headers=admin_headers,
        json={"user_id": actor.id, "role": "communications"},
    )
    assert following.status_code == 201, following.json


@pytest.mark.parametrize("operation", ["assign", "accept"])
def test_unrelated_integrity_error_is_not_reported_as_assignment_conflict(
    client,
    db,
    admin_headers,
    monkeypatch,
    operation,
):
    team, actor = _context()
    incident = Incident.create(team=team, title="Unexpected constraint error")
    pending = IncidentResponder.create(
        incident=incident,
        target_type="user",
        target_user=actor,
    )

    def fail(*args, **kwargs):
        raise IntegrityError("injected unexpected constraint failure")

    if operation == "assign":
        monkeypatch.setattr(IncidentResponder, "create", fail)
        response = client.post(
            f"/api/incidents/{incident.id}/participants",
            headers=admin_headers,
            json={"user_id": actor.id, "role": "commander"},
        )
    else:
        monkeypatch.setattr(incidents_repo, "update_incident_responder_status", fail)
        response = client.put(
            f"/api/incidents/{incident.id}/responders/{pending.id}",
            headers=admin_headers,
            json={"status": "accepted"},
        )
    assert response.status_code == 400
    assert response.json["error"] == "constraint_violation"
    assert response.json["details"] == [{"type": "integrity_error"}]
    assert IncidentResponder.get_by_id(pending.id).status == "requested"
    assert IncidentEvent.select().count() == AuditLog.select().count() == 0
