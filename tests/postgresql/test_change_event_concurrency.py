"""Real connections serialize first intake, conflicting retries and revocation."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Barrier, Event

import pytest

from app.api.schemas.change_events import ChangeEventInput
from app.api.schemas.change_integrations import GrantUpdate
from app.modules.db.models import Change, ChangeEvent, ChangeJob, ChangeService
from app.services.change_intelligence import administration as admin, ingestion
from app.services.change_intelligence.authorization import (
    ChangeAccessDenied,
    authorized_source,
)
from tests.integrations.test_change_events import event_payload, intake, setup_identity
from tests.integrations.test_change_integrations import revision

__all__ = ["intake", "setup_identity"]
pytestmark = pytest.mark.postgresql


@pytest.fixture(autouse=True)
def postgres_only(db):
    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("requires PostgreSQL")


@pytest.mark.parametrize("kind", ["duplicate", "conflict", "different-event"])
def test_concurrent_first_event(db, intake, kind):
    barrier = Barrier(2)

    def accept(index):
        body = event_payload(intake[0])
        if index:
            if kind == "conflict":
                body["title"] = "Different content"
            elif kind == "different-event":
                body["event_id"] = "other-event"
        payload = ChangeEventInput.model_validate(body)
        with db.connection_context():
            barrier.wait(timeout=10)
            try:
                _, created = ingestion.ingest_event(payload, intake[3])
                return "created" if created else "duplicate"
            except ingestion.ChangeEventConflict:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(accept, index) for index in range(2)]
        outcomes = sorted(future.result(timeout=20) for future in futures)
    assert (
        outcomes
        == {
            "duplicate": ["created", "duplicate"],
            "conflict": ["conflict", "created"],
            "different-event": ["created", "created"],
        }[kind]
    )
    count = 2 if kind == "different-event" else 1
    assert Change.select().count() == 1
    assert ChangeEvent.select().count() == count
    assert Change.get().revision == count
    assert ChangeService.select().count() == 1
    job = ChangeJob.get(ChangeJob.job_type == "resolve_references")
    assert job.requested_generation == count


def test_revocation_committed_before_intake_lock_denies_all_writes(
    db, intake, monkeypatch
):
    locked = Event()
    release = Event()
    original = admin.advance_revision

    def hold(integration):
        result = original(integration)
        locked.set()
        assert release.wait(timeout=10)
        return result

    monkeypatch.setattr(admin, "advance_revision", hold)
    identity, permission, _, raw = intake
    integration, source, _, actor = identity
    expected = revision(integration)

    def revoke():
        with db.connection_context():
            return admin.update_grant(
                integration.id,
                source.id,
                permission.id,
                GrantUpdate(
                    expected_revision=expected,
                    active=False,
                ),
                actor_id=actor.id,
            )

    def accept():
        with db.connection_context():
            return ingestion.ingest_event(
                ChangeEventInput.model_validate(event_payload(identity)), raw
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        revocation = pool.submit(revoke)
        assert locked.wait(timeout=10)
        admission = pool.submit(accept)
        release.set()
        revocation.result(timeout=15)
        with pytest.raises(ChangeAccessDenied):
            admission.result(timeout=15)
    assert Change.select().count() == 0
    assert ChangeEvent.select().count() == 0


def test_uncommitted_failed_first_event_does_not_poison_retry(db, intake, monkeypatch):
    locked = Event()
    release = Event()
    original = ingestion.changes_repo.request_job
    failed = False

    def fail_first(*args, **kwargs):
        nonlocal failed
        result = original(*args, **kwargs)
        if not failed:
            failed = True
            locked.set()
            assert release.wait(timeout=10)
            raise RuntimeError("rollback after durable job insert")
        return result

    monkeypatch.setattr(ingestion.changes_repo, "request_job", fail_first)

    def accept():
        with db.connection_context():
            return ingestion.ingest_event(
                ChangeEventInput.model_validate(event_payload(intake[0])), intake[3]
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(accept)
        assert locked.wait(timeout=10)
        second = pool.submit(accept)
        release.set()
        with pytest.raises(RuntimeError, match="rollback"):
            first.result(timeout=15)
        assert second.result(timeout=15)[1]
    assert Change.select().count() == ChangeEvent.select().count() == 1
    assert Change.get().revision == 1
    assert (
        ChangeJob.get(ChangeJob.job_type == "resolve_references").requested_generation
        == 1
    )


def test_admitted_event_commits_before_waiting_grant_revocation(
    db, intake, monkeypatch
):
    entered = Event()
    release = Event()
    revoking = Event()
    original = ingestion.changes_repo.request_job

    def hold(job_type, *args, **kwargs):
        result = original(job_type, *args, **kwargs)
        if job_type == "resolve_references":
            entered.set()
            assert release.wait(timeout=10)
        return result

    monkeypatch.setattr(ingestion.changes_repo, "request_job", hold)
    identity, permission, _, raw = intake
    integration, source, _, actor = identity
    expected = revision(integration)

    def accept():
        with db.connection_context():
            return ingestion.ingest_event(
                ChangeEventInput.model_validate(event_payload(identity)), raw
            )

    def revoke():
        with db.connection_context():
            revoking.set()
            return admin.update_grant(
                integration.id,
                source.id,
                permission.id,
                GrantUpdate(
                    expected_revision=expected,
                    active=False,
                ),
                actor_id=actor.id,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        admission = pool.submit(accept)
        assert entered.wait(timeout=10)
        revocation = pool.submit(revoke)
        assert revoking.wait(timeout=10)
        try:
            with pytest.raises(TimeoutError):
                revocation.result(timeout=0.1)
        finally:
            release.set()
        assert admission.result(timeout=15)[1]
        revocation.result(timeout=15)
    assert ChangeEvent.select().count() == 1
    body = event_payload(identity, event_id="after-revocation")
    with pytest.raises(ChangeAccessDenied):
        ingestion.ingest_event(ChangeEventInput.model_validate(body), raw)


def test_real_postgresql_lock_timeout_has_bounded_retries(db, intake):
    locked = Event()
    release = Event()
    integration, source, _, _ = intake[0]

    def holder():
        with (
            db.connection_context(),
            authorized_source(integration.id, source.owner_team_id, source.source),
        ):
            locked.set()
            assert release.wait(timeout=15)

    with ThreadPoolExecutor(max_workers=1) as pool:
        holding = pool.submit(holder)
        assert locked.wait(timeout=10)
        try:
            with pytest.raises(ingestion.ChangeIntakeBusy):
                ingestion.ingest_event(
                    ChangeEventInput.model_validate(event_payload(intake[0])), intake[3]
                )
        finally:
            release.set()
        holding.result(timeout=10)
    assert Change.select().count() == ChangeEvent.select().count() == 0
    assert ingestion.ingest_event(
        ChangeEventInput.model_validate(event_payload(intake[0])), intake[3]
    )[1]
