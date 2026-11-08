"""Independent requests serialize review and Incident collaboration writes."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.modules.db.models import (
    AuditLog,
    ChangeAlertGroupCorrelation,
    ChangeIncidentLink,
    IncidentEvent,
)
from tests.integrations.test_change_integration_groups import headers
from tests.integrations.test_change_reviews import (
    incident_url,
    intake,
    link_body,
    review_body,
    review_case,
    review_url,
    setup_identity,
)

__all__ = ["intake", "review_case", "setup_identity"]
pytestmark = pytest.mark.postgresql


@pytest.fixture(autouse=True)
def postgres_only(db):
    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("Independent connection races require PostgreSQL")


def race_requests(app, db, auth, calls):
    barrier = Barrier(len(calls))

    def run(call):
        method, path, payload = call
        with db.connection_context(), app.test_client() as client:
            barrier.wait(timeout=10)
            response = client.open(path, method=method, headers=auth, json=payload)
            return response.status_code

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(run, call) for call in calls]
        return sorted(future.result(timeout=20) for future in futures)


def test_concurrent_confirm_reject_accepts_one_version(app, db, review_case):
    case = review_case
    results = race_requests(
        app,
        db,
        headers(case.user),
        [
            ("POST", review_url(case), review_body(case, decision=decision))
            for decision in ("confirmed", "rejected")
        ],
    )
    assert results == [200, 409]
    assert ChangeAlertGroupCorrelation.get_by_id(case.row.id).row_version == 2
    assert (
        AuditLog.select().where(AuditLog.action == "change.correlation.review").count()
        == 1
    )


def test_concurrent_incident_add_is_idempotent(app, db, review_case):
    case = review_case
    call = ("POST", incident_url(case), link_body(case))
    assert race_requests(app, db, headers(case.user), [call, call]) == [200, 201]
    assert ChangeIncidentLink.select().count() == 1
    assert IncidentEvent.select().count() == 1


def test_concurrent_incident_role_change_and_remove(app, client, db, review_case):
    case = review_case
    auth = headers(case.user)
    added = client.post(incident_url(case), headers=auth, json=link_body(case))
    assert added.status_code == 201
    path = incident_url(case) + f"/{added.json['id']}"
    results = race_requests(
        app,
        db,
        auth,
        [
            (
                "PATCH",
                path,
                {"row_version": 1, "relation_type": "mitigation", "note": "Fixed"},
            ),
            ("DELETE", path, {"row_version": 1, "note": "Wrong relation"}),
        ],
    )
    assert results == [200, 409]
    assert ChangeIncidentLink.get().row_version == 2
    assert IncidentEvent.select().count() == 2
