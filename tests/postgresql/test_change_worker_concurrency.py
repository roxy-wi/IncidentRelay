"""Independent PostgreSQL connections exercise leases and publication races."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from threading import Barrier, Event

import pytest

from app.api.schemas.change_events import ChangeEventInput
from app.api.schemas.change_integrations import GrantUpdate
from app.modules.common import utc_now
from app.modules.db import changes_repo as queue, incident_core_repo
from app.modules.db.models import (
    Change,
    ChangeJob,
    ChangeService,
    ChangeServiceReference,
)
from app.services.change_intelligence import (
    administration as admin,
    ingestion,
    resolver,
    worker,
)
from tests.factories import create_service
from tests.integrations.test_change_events import event_payload, intake, setup_identity
from tests.integrations.test_change_integrations import revision
from tests.integrations.test_change_worker import claim_resolution, pending_change

__all__ = ["intake", "setup_identity"]
pytestmark = pytest.mark.postgresql


@pytest.fixture(autouse=True)
def postgres_only(db):
    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("requires PostgreSQL")


def test_concurrent_claims_have_one_owner(db, intake):
    change = pending_change(intake)
    ChangeJob.delete().where(ChangeJob.job_type != "resolve_references").execute()
    barrier = Barrier(2)

    def claim(owner):
        with db.connection_context():
            barrier.wait(timeout=10)
            return queue.claim_job(owner)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim, owner) for owner in ("first", "second")]
        results = [future.result(timeout=15) for future in futures]
    winners = [result for result in results if result is not None]
    assert len(winners) == 1 and winners[0].entity_id == change.id
    assert ChangeJob.get().attempts == 1


def test_skip_locked_claims_another_due_job(db, intake):
    first_change = pending_change(intake, change_id="one")
    second_change = pending_change(intake, change_id="two")
    ChangeJob.delete().where(ChangeJob.job_type != "resolve_references").execute()
    first = ChangeJob.get(ChangeJob.entity_id == first_change.id)
    locked, release = Event(), Event()

    def hold():
        with db.connection_context(), db.atomic():
            ChangeJob.select().where(ChangeJob.id == first.id).for_update().get()
            locked.set()
            assert release.wait(timeout=10)

    with ThreadPoolExecutor(max_workers=1) as pool:
        holding = pool.submit(hold)
        assert locked.wait(timeout=10)
        try:
            second = queue.claim_job("skip-locked")
            assert second.entity_id == second_change.id
        finally:
            release.set()
        holding.result(timeout=10)


def test_revocation_during_calculation_prevents_publication(db, intake, monkeypatch):
    change = pending_change(intake)
    create_service(intake[0][2].team, slug="late-service")
    claim = claim_resolution(change)
    calculated, release = Event(), Event()
    original = worker.compute_reference_batch

    def pause(current):
        result = original(current)
        calculated.set()
        assert release.wait(timeout=10)
        return result

    monkeypatch.setattr(worker, "compute_reference_batch", pause)

    def run():
        with db.connection_context():
            return worker.process_claim(claim)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run)
        assert calculated.wait(timeout=10)
        try:
            integration, source, _, actor = intake[0]
            admin.update_grant(
                integration.id,
                source.id,
                intake[1].id,
                GrantUpdate(
                    expected_revision=revision(integration),
                    active=False,
                ),
                actor_id=actor.id,
            )
        finally:
            release.set()
        assert future.result(timeout=15) == "stale"
    assert ChangeService.select().count() == 0
    assert ChangeJob.get_by_id(claim.id).state == "pending"


def test_new_event_during_calculation_keeps_new_generation(db, intake, monkeypatch):
    change = pending_change(intake)
    claim = claim_resolution(change)
    calculated, release = Event(), Event()
    original = worker.compute_reference_batch

    def pause(current):
        plan = original(current)
        calculated.set()
        assert release.wait(timeout=10)
        return plan

    monkeypatch.setattr(worker, "compute_reference_batch", pause)

    def run():
        with db.connection_context():
            return worker.process_claim(claim)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run)
        assert calculated.wait(timeout=10)
        try:
            payload = ChangeEventInput.model_validate(
                event_payload(intake[0], event_id="concurrent-event")
            )
            assert ingestion.ingest_event(payload, intake[3])[1]
        finally:
            release.set()
        assert future.result(timeout=15) == "stale"
    current = ChangeJob.get_by_id(claim.id)
    assert current.requested_generation == claim.claimed_generation + 1
    assert current.completed_generation < current.requested_generation
    assert current.state == "pending"


def test_expired_old_publisher_cannot_overwrite_replacement(db, intake):
    change = pending_change(intake)
    create_service(intake[0][2].team, slug="late-service")
    first = claim_resolution(change)
    plan = resolver.compute_reference_batch(first)
    ChangeJob.update(lease_expires_at=utc_now() - timedelta(seconds=1)).where(
        ChangeJob.id == first.id
    ).execute()

    def replace():
        with db.connection_context():
            second = queue.claim_job("replacement")
            assert second.reclaimed
            assert worker.process_claim(second) == "processed"

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(replace).result(timeout=15)
    version = Change.get_by_id(change.id).revision
    with pytest.raises((resolver.StaleChangeInputs, queue.LostChangeLease)):
        resolver.publish_reference_batch(first, plan)
    assert not queue.release_stale_claim(first)
    assert not queue.fail_claim(first, transient=True)
    assert ChangeJob.get_by_id(first.id).state == "done"
    assert Change.get_by_id(change.id).revision == version
    assert ChangeService.select().count() == 1


def test_expiry_at_ack_rolls_back_projection(db, intake, monkeypatch):
    change = pending_change(intake)
    create_service(intake[0][2].team, slug="late-service")
    claim = claim_resolution(change)
    plan = resolver.compute_reference_batch(claim)
    original = queue.finish_claim

    def expire(*args, **kwargs):
        monkeypatch.setattr(
            queue, "utc_now", lambda: claim.lease_expires_at + timedelta(seconds=1)
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(queue, "finish_claim", expire)
    with pytest.raises(queue.LostChangeLease):
        resolver.publish_reference_batch(claim, plan)
    assert ChangeService.select().count() == 0
    assert ChangeServiceReference.get().resolution_status == "pending_resolution"
    assert Change.get_by_id(change.id).revision == change.revision


def test_renewal_prevents_reclaim_and_completion_is_idempotent(db, intake):
    change = pending_change(intake)
    claim = claim_resolution(change)
    before = ChangeJob.get_by_id(claim.id).lease_expires_at
    queue.renew_lease(claim)
    assert ChangeJob.get_by_id(claim.id).lease_expires_at >= before
    assert queue.claim_job("competitor") is None
    with incident_core_repo.write_transaction():
        queue.lock_claim(claim)
        queue.finish_claim(claim)
    with pytest.raises(queue.LostChangeLease), incident_core_repo.write_transaction():
        queue.finish_claim(claim)


def test_discovery_does_not_revive_concurrently_failed_job(db, intake):
    pending_change(intake)
    ChangeJob.delete().where(ChangeJob.job_type != "resolve_references").execute()
    resolution = ChangeJob.get()
    ChangeJob.update(
        claimed_generation=resolution.requested_generation,
        next_attempt_at=utc_now() + timedelta(hours=1),
    ).where(ChangeJob.id == resolution.id).execute()
    worker.schedule_pending_reconciliation()
    discovery = queue.claim_job("discovery")
    plan = worker.compute_discovery_batch(discovery)
    locked, release, publishing = Event(), Event(), Event()

    def fail_job():
        with db.connection_context(), db.atomic():
            ChangeJob.select().where(ChangeJob.id == resolution.id).for_update().get()
            ChangeJob.update(state="dead", last_error_class="internal_error").where(
                ChangeJob.id == resolution.id
            ).execute()
            locked.set()
            assert release.wait(timeout=10)

    def publish():
        with db.connection_context():
            publishing.set()
            worker.publish_discovery_batch(discovery, plan)

    with ThreadPoolExecutor(max_workers=2) as pool:
        failure = pool.submit(fail_job)
        assert locked.wait(timeout=10)
        completion = pool.submit(publish)
        assert publishing.wait(timeout=10)
        try:
            with pytest.raises(TimeoutError):
                completion.result(timeout=0.1)
        finally:
            release.set()
        failure.result(timeout=10)
        completion.result(timeout=10)
    assert ChangeJob.get_by_id(resolution.id).state == "dead"
    assert (
        ChangeJob.get_by_id(resolution.id).requested_generation
        == resolution.requested_generation
    )


@pytest.mark.parametrize("operation", ["renew", "finish", "release"])
def test_lease_expiring_while_waiting_for_row_lock_is_rejected(
    db, intake, monkeypatch, operation
):
    change = pending_change(intake)
    claim = claim_resolution(change)
    locked, release, waiting = Event(), Event(), Event()
    expired = Event()
    original_clock = queue.utc_now

    def clock():
        if expired.is_set():
            return claim.lease_expires_at + timedelta(seconds=1)
        return original_clock()

    monkeypatch.setattr(queue, "utc_now", clock)

    def hold_lock():
        with db.connection_context(), db.atomic():
            ChangeJob.select().where(ChangeJob.id == claim.id).for_update().get()
            locked.set()
            assert release.wait(timeout=10)

    def run():
        with db.connection_context(), incident_core_repo.write_transaction():
            waiting.set()
            if operation == "renew":
                return queue.renew_lease(claim)
            if operation == "finish":
                return queue.finish_claim(claim)
            return queue.release_stale_claim(claim)

    with ThreadPoolExecutor(max_workers=2) as pool:
        holder = pool.submit(hold_lock)
        assert locked.wait(timeout=10)
        contender = pool.submit(run)
        assert waiting.wait(timeout=10)
        try:
            with pytest.raises(TimeoutError):
                contender.result(timeout=0.1)
        finally:
            expired.set()
            release.set()
        holder.result(timeout=10)
        if operation == "release":
            assert contender.result(timeout=10) is False
        else:
            with pytest.raises(queue.LostChangeLease):
                contender.result(timeout=10)
    current = ChangeJob.get_by_id(claim.id)
    assert current.state == "running"
    assert current.lease_token == claim.lease_token
    assert current.lease_expires_at == claim.lease_expires_at
