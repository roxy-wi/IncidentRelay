"""Separate PostgreSQL connections exercise timeline fencing and revocation."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest

from app.api.schemas.change_integrations import GrantUpdate
from app.modules.db import changes_repo
from app.modules.db.models import ServiceEvent
from app.services.change_intelligence import administration, timeline, worker
from tests.integrations.test_changes_read import changes
from tests.integrations.test_change_events import intake, setup_identity
from tests.integrations.test_change_correlation import claim_kind
from tests.integrations.test_change_integrations import revision

__all__ = ["changes", "intake", "setup_identity"]
pytestmark = pytest.mark.postgresql


@pytest.fixture(autouse=True)
def postgres_only(db):
    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("requires PostgreSQL")


def test_duplicate_publishers_commit_one_projection(db, changes):
    claim = claim_kind("sync_service_timeline", changes["change"].id)
    plan = timeline.compute_timeline_batch(claim)
    ready = Barrier(2)

    def publish():
        with db.connection_context():
            ready.wait(timeout=10)
            try:
                timeline.publish_timeline_batch(claim, plan)
                return "published"
            except changes_repo.LostChangeLease:
                return "fenced"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(publish) for _ in range(2)]
        assert sorted(future.result(timeout=15) for future in results) == [
            "fenced",
            "published",
        ]
    assert ServiceEvent.select().count() == 2


def test_revocation_during_timeline_calculation_blocks_publish(
    db, changes, monkeypatch
):
    claim = claim_kind("sync_service_timeline", changes["change"].id)
    calculated, release = Event(), Event()
    compute = worker.compute_timeline_batch

    def paused(current):
        plan = compute(current)
        calculated.set()
        assert release.wait(timeout=10)
        return plan

    monkeypatch.setattr(worker, "compute_timeline_batch", paused)

    def run():
        with db.connection_context():
            return worker.process_claim(claim)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run)
        assert calculated.wait(timeout=10)
        try:
            integration, source, _, actor = changes["intake"][0]
            administration.update_grant(
                integration.id,
                source.id,
                changes["permission"].id,
                GrantUpdate(expected_revision=revision(integration), active=False),
                actor_id=actor.id,
            )
        finally:
            release.set()
        assert future.result(timeout=15) == "stale"
    assert not ServiceEvent.select().exists()
