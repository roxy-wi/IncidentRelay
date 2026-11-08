"""Concurrent requests use separate connections on SQLite and PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event

import pytest

from app.db import database_proxy
from app.login import create_access_token
from app.modules.common import utc_now
from app.modules.db import incident_core_repo, incidents_repo
from app.modules.db.models import (
    AlertGroup,
    AuditLog,
    Incident,
    IncidentAlertGroupLink,
    IncidentEvent,
    IncidentResponder,
    IncidentService,
    IncidentStakeholder,
)
from app.services.incidents import core, responders, stakeholders
from tests.factories import (
    create_group,
    create_service,
    create_team,
    create_user,
    unique,
)


def _context():
    team = create_team(create_group())
    actors = [create_user(group=team.group, is_admin=True) for _ in range(2)]
    incident = Incident.create(team=team, title="Concurrent operation")
    return incident, actors


def _headers(user):
    token, _ = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def _concurrent(first, second):
    barrier = Barrier(2)

    def run(function):
        with database_proxy.obj.connection_context():
            barrier.wait(timeout=10)
            return function()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, function) for function in (first, second)]
        return [future.result(timeout=20) for future in futures]


@pytest.mark.parametrize(
    "collection",
    [
        "participants",
        "stakeholders",
        "affected-services",
        "responders",
    ],
)
def test_concurrent_adds_have_one_record_and_one_audit(
    app,
    db,
    monkeypatch,
    collection,
):
    incident, actors = _context()
    service = create_service(incident.team)
    headers = _headers(actors[0])
    monkeypatch.setattr(
        responders, "notify_incident_responder_requested", lambda row: None
    )

    def add(index):
        if collection == "participants":
            payload = {"user_id": actors[index].id, "role": "commander"}
            model = IncidentResponder
        elif collection == "stakeholders":
            payload = {"user_id": actors[0].id}
            model = IncidentStakeholder
        elif collection == "responders":
            payload = {"target_type": "user", "target_user_id": actors[0].id}
            model = IncidentResponder
        else:
            payload = {"service_id": service.id}
            model = IncidentService
        with app.test_client() as client:
            response = client.post(
                f"/api/incidents/{incident.id}/{collection}",
                headers=headers,
                json=payload,
            )
        return response.status_code, model

    results = _concurrent(lambda: add(0), lambda: add(1))
    expected = (
        [201, 409] if collection in {"participants", "responders"} else [200, 201]
    )
    assert sorted(status for status, _ in results) == expected
    assert results[0][1].select().count() == 1
    assert IncidentEvent.select().count() == AuditLog.select().count() == 1


def test_competing_responder_decisions_do_not_overwrite_each_other(app, db):
    incident, actors = _context()
    row = IncidentResponder.create(
        incident=incident,
        target_type="user",
        target_user=actors[0],
    )
    headers = [_headers(actor) for actor in actors]

    def decide(index, status):
        with app.test_client() as client:
            result = client.put(
                f"/api/incidents/{incident.id}/responders/{row.id}",
                headers=headers[index],
                json={"status": status},
            )
            return result.status_code, status, actors[index].id

    results = _concurrent(lambda: decide(0, "accepted"), lambda: decide(1, "declined"))
    assert sorted(result[0] for result in results) == [200, 409]
    winner = next(result for result in results if result[0] == 200)
    current = IncidentResponder.get_by_id(row.id)
    assert current.status == winner[1]
    assert IncidentEvent.get().event_type == f"responder_{winner[1]}"
    assert IncidentEvent.get().user_id == AuditLog.get().user_id == winner[2]


def test_collective_request_cannot_be_accepted_by_two_people(app, db):
    incident, actors = _context()
    row = IncidentResponder.create(
        incident=incident,
        target_type="team",
        target_team=incident.team,
    )
    headers = [_headers(actor) for actor in actors]

    def accept(index):
        with app.test_client() as client:
            result = client.put(
                f"/api/incidents/{incident.id}/responders/{row.id}",
                headers=headers[index],
                json={"status": "accepted"},
            )
            return result.status_code, actors[index].id

    results = _concurrent(lambda: accept(0), lambda: accept(1))
    assert sorted(result[0] for result in results) == [200, 409]
    winner = next(user_id for status, user_id in results if status == 200)
    current = IncidentResponder.get_by_id(row.id)
    assert current.target_user_id == current.accepted_by_id == winner
    assert IncidentEvent.get().user_id == AuditLog.get().user_id == winner


def test_different_requests_cannot_assign_same_person_twice(db):
    incident, actors = _context()
    rows = [
        IncidentResponder.create(
            incident=incident, target_type="user", target_user=actors[0]
        ),
        IncidentResponder.create(
            incident=incident, target_type="team", target_team=incident.team
        ),
    ]

    def accept(row):
        try:
            responders.set_incident_responder_status(
                incident_id=incident.id,
                responder_id=row.id,
                status="accepted",
                user=actors[0],
            )
            return "accepted"
        except incident_core_repo.IncidentConflictError:
            return "conflict"

    assert sorted(_concurrent(lambda: accept(rows[0]), lambda: accept(rows[1]))) == [
        "accepted",
        "conflict",
    ]
    assert (
        IncidentResponder.select().where(IncidentResponder.status == "accepted").count()
        == 1
    )
    assert (
        IncidentResponder.select()
        .where(IncidentResponder.status == "requested")
        .count()
        == 1
    )
    assert IncidentEvent.select().count() == AuditLog.select().count() == 1


def test_duplicate_acceptance_by_same_actor_is_idempotent(db):
    incident, actors = _context()
    row = IncidentResponder.create(
        incident=incident,
        target_type="team",
        target_team=incident.team,
    )

    def accept():
        return responders.set_incident_responder_status(
            incident_id=incident.id,
            responder_id=row.id,
            status="accepted",
            user=actors[0],
        ).id

    assert _concurrent(accept, accept) == [row.id, row.id]
    assert IncidentEvent.select().count() == AuditLog.select().count() == 1


@pytest.mark.parametrize("first", ["accept", "expire"])
def test_acceptance_and_expiration_serialize_with_inflight_write(
    db, monkeypatch, first
):
    incident, actors = _context()
    deadline = utc_now()
    now = [deadline - timedelta(seconds=1) if first == "accept" else deadline]
    row = IncidentResponder.create(
        incident=incident,
        target_type="user",
        target_user=actors[0],
        expires_at=deadline,
    )
    monkeypatch.setattr(responders, "utc_now", lambda: now[0])
    monkeypatch.setattr(incidents_repo, "utc_now", lambda: now[0])
    first_wrote = Event()
    release_first = Event()
    second_started = Event()
    original_event = incident_core_repo.create_event
    original_list = incidents_repo.list_expired_requested_responders

    def hold_first_write(incident_id, event_type, **kwargs):
        if event_type == (
            "responder_accepted" if first == "accept" else "responder_expired"
        ):
            first_wrote.set()
            assert release_first.wait(timeout=10)
        return original_event(incident_id, event_type, **kwargs)

    def selected_expirations(**kwargs):
        rows = original_list(**kwargs)
        if first == "accept":
            assert len(rows) == 1
            second_started.set()
        return rows

    monkeypatch.setattr(incident_core_repo, "create_event", hold_first_write)
    monkeypatch.setattr(
        incidents_repo, "list_expired_requested_responders", selected_expirations
    )

    def accept():
        with database_proxy.obj.connection_context():
            if first == "expire":
                second_started.set()
            try:
                responders.set_incident_responder_status(
                    incident_id=incident.id,
                    responder_id=row.id,
                    status="accepted",
                    user=actors[0],
                )
                return "accepted"
            except incident_core_repo.IncidentConflictError:
                return "conflict"

    def expire():
        with database_proxy.obj.connection_context():
            return responders.expire_due_incident_responders()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(accept if first == "accept" else expire)
        try:
            assert first_wrote.wait(timeout=10)
            now[0] = deadline + timedelta(seconds=1)
            second_future = pool.submit(expire if first == "accept" else accept)
            assert second_started.wait(timeout=10)
        finally:
            release_first.set()
        first_result = first_future.result(timeout=20)
        second_result = second_future.result(timeout=20)
    if first == "accept":
        assert first_result == "accepted"
        assert second_result == {"processed": 1, "expired": 0, "skipped": 1}
        assert IncidentResponder.get_by_id(row.id).status == "accepted"
    else:
        assert first_result["expired"] == 1
        assert second_result == "conflict"
        assert IncidentResponder.get_by_id(row.id).status == "expired"
    assert IncidentEvent.select().count() == AuditLog.select().count() == 1


def test_concurrent_incident_updates_keep_one_version_and_history(db):
    incident, actors = _context()

    def update(title):
        try:
            core.update_incident(
                incident.id, expected_version=1, title=title, user_id=actors[0].id
            )
            return title
        except core.IncidentConflictError:
            return "conflict"

    results = _concurrent(lambda: update("First"), lambda: update("Second"))
    assert results.count("conflict") == 1
    current = Incident.get_by_id(incident.id)
    assert current.row_version == 2
    assert current.title == next(result for result in results if result != "conflict")
    assert IncidentEvent.select().count() == AuditLog.select().count() == 1


def test_concurrent_declarations_from_same_alert_group_create_one_incident(
    db,
    monkeypatch,
):
    team = create_team(create_group())
    actor = create_user(group=team.group, is_admin=True)
    group = AlertGroup.create(
        team=team,
        source="manual",
        title="Concurrent declarations",
        group_key=unique("group"),
        group_key_hash=unique("hash"),
    )
    notified = []
    monkeypatch.setattr(
        stakeholders,
        "notify_stakeholders",
        lambda incident, *args, **kwargs: notified.append(incident.id),
    )

    def declare():
        try:
            return core.create_incident_from_alert_group(group.id, user_id=actor.id).id
        except core.IncidentConflictError:
            return "conflict"

    results = _concurrent(declare, declare)
    assert results.count("conflict") == 1
    incident = Incident.get()
    assert next(result for result in results if result != "conflict") == incident.id
    assert Incident.select().count() == 1
    assert IncidentAlertGroupLink.get().incident_id == incident.id
    assert IncidentEvent.select().count() == AuditLog.select().count() == 2
    assert notified == [incident.id]


def test_concurrent_removal_emits_one_service_event(app, db):
    incident, actors = _context()
    service = create_service(incident.team)
    IncidentService.create(incident=incident, service=service)
    headers = _headers(actors[0])

    def remove():
        with app.test_client() as client:
            return client.delete(
                f"/api/incidents/{incident.id}/affected-services/{service.id}",
                headers=headers,
            ).status_code

    assert sorted(_concurrent(remove, remove)) == [200, 404]
    assert IncidentService.select().count() == 0
    assert IncidentEvent.select().count() == AuditLog.select().count() == 1
