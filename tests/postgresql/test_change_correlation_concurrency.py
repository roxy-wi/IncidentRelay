"""Independent connections fence stale correlation and serialize duplicate work."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest

from app.modules.db import alert_episodes_repo, incident_core_repo
from app.modules.db.models import (
    AlertGroupEpisode,
    ChangeAlertGroupCorrelation,
    ChangeJob,
    Service,
)
from app.services.change_intelligence import correlation as engine
from app.services.change_intelligence.catalog import graph_change
from app.services.change_intelligence.resolver import StaleChangeInputs
from tests.integrations.test_change_correlation import (
    claim_kind,
    episode_for,
    intake,
    operation,
    opt_in,
    request_change,
    setup_identity,
)

__all__ = ["intake", "setup_identity"]
pytestmark = pytest.mark.postgresql


@pytest.fixture(autouse=True)
def postgres_only(db):
    if "postgres" not in db.__class__.__name__.lower():
        pytest.skip("requires PostgreSQL")


@pytest.mark.parametrize("mutation", ["episode", "policy"])
def test_publication_waits_and_rechecks_committed_input(
    db, intake, monkeypatch, mutation
):
    service = opt_in(intake[0][2])
    episode = episode_for(service)
    change = operation(intake)
    claim = claim_kind("refresh_impacts", change.id)
    plan = engine.compute_correlation_batch(claim)
    waiting = Event()
    original = engine.lock_row

    def observed(query):
        if (mutation == "episode" and query.model is AlertGroupEpisode) or (
            mutation == "policy"
            and query.model._meta.table_name == "change_graph_state"
        ):
            waiting.set()
        return original(query)

    monkeypatch.setattr(engine, "lock_row", observed)

    def publish():
        with db.connection_context():
            try:
                engine.publish_correlation_batch(claim, plan)
            except StaleChangeInputs:
                return "stale"
            return "published"

    with ThreadPoolExecutor(max_workers=1) as pool:
        if mutation == "episode":
            with incident_core_repo.write_transaction():
                group = incident_core_repo.lock_alert_group(episode.alert_group_id)
                original(
                    AlertGroupEpisode.select().where(AlertGroupEpisode.id == episode.id)
                )
                future = pool.submit(publish)
                assert waiting.wait(timeout=10)
                AlertGroupEpisode.update(
                    context_revision=AlertGroupEpisode.context_revision + 1
                ).where(AlertGroupEpisode.id == episode.id).execute()
                alert_episodes_repo.request_discovery(
                    AlertGroupEpisode.get_by_id(episode.id)
                )
        else:
            with graph_change():
                future = pool.submit(publish)
                assert waiting.wait(timeout=10)
                Service.update(change_correlation_enabled=False).where(
                    Service.id == service.id
                ).execute()
        assert future.result(timeout=15) == "stale"
    assert ChangeAlertGroupCorrelation.select().count() == 0


def test_two_job_types_publish_one_pair_without_duplicates(db, intake):
    service = opt_in(intake[0][2])
    episode_for(service)
    change = operation(intake)
    request_change(change)
    first = claim_kind("refresh_impacts", change.id)
    second = claim_kind("refresh_correlations", change.id)
    plans = [
        (claim, engine.compute_correlation_batch(claim)) for claim in (first, second)
    ]
    barrier = Barrier(2)

    def publish(item):
        with db.connection_context():
            barrier.wait(timeout=10)
            engine.publish_correlation_batch(*item)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(publish, item) for item in plans]
        for future in futures:
            future.result(timeout=15)
    assert ChangeAlertGroupCorrelation.select().count() == 1
    assert all(
        ChangeJob.get_by_id(claim.id).state == "done" for claim in (first, second)
    )
