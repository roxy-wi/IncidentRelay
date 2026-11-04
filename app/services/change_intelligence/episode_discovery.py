"""Discover recent or running Changes for an explicitly eligible episode."""

from peewee import fn

from app.modules.common import utc_now
from app.modules.db import changes_repo, incident_core_repo
from app.modules.db.models import AlertGroupEpisode, Change, ChangeGraphState
from app.services.change_intelligence.authorization import lock_row
from app.services.change_intelligence.correlation import history_changes
from app.services.change_intelligence.eligibility import episode_eligibility
from app.services.change_intelligence.resolver import StaleChangeInputs
from app.settings import Config


def compute_episode_discovery(claim):
    """Capture a bounded ID range only after the shared eligibility gate."""
    graph_revision = ChangeGraphState.get_by_id(1).revision
    episode = AlertGroupEpisode.get_or_none(AlertGroupEpisode.id == claim.entity_id)
    stamp = {
        "graph_revision": graph_revision,
        "target_revision": episode.context_revision if episode else 0,
        "engine_version": "episode-discovery-v1",
    }
    reason = episode_eligibility(episode) if episode else "entity_missing"
    plan = {
        "episode": episode,
        "stamp": stamp,
        "reason": reason,
        "ids": [],
        "complete": True,
        "after_id": 0,
        "upper_id": 0,
    }
    if reason != "eligible":
        return plan
    cursor = claim.cursor or {}
    if any(cursor.get(key) != value for key, value in stamp.items()):
        cursor = {}
    query = history_changes(utc_now())
    upper = cursor.get("upper_id")
    if upper is None:
        upper = query.select(fn.MAX(Change.id)).scalar() or 0
    ids = [
        row.id
        for row in query.select(Change.id)
        .where(Change.id > cursor.get("after_id", 0), Change.id <= upper)
        .order_by(Change.id)
        .limit(Config.CHANGE_WORKER_BATCH_SIZE)
    ]
    after = ids[-1] if ids else upper
    plan.update(
        ids=ids,
        after_id=after,
        upper_id=upper,
        complete=after >= upper or len(ids) < Config.CHANGE_WORKER_BATCH_SIZE,
    )
    return plan


def publish_episode_discovery(claim, plan):
    """The episode fence and all new requests commit with the sweep cursor."""
    with incident_core_repo.write_transaction():
        graph = lock_row(ChangeGraphState.select().where(ChangeGraphState.id == 1))
        if graph.revision != plan["stamp"]["graph_revision"]:
            raise StaleChangeInputs()
        changes = [
            lock_row(Change.select().where(Change.id == change_id))
            for change_id in plan["ids"]
        ]
        episode = lock_row(
            AlertGroupEpisode.select().where(AlertGroupEpisode.id == claim.entity_id)
        )
        if (episode.context_revision if episode else 0) != plan["stamp"][
            "target_revision"
        ]:
            raise StaleChangeInputs()
        if plan["reason"] == "eligible" and episode_eligibility(episode) != "eligible":
            raise StaleChangeInputs()
        for change in filter(None, changes):
            changes_repo.request_job(
                "refresh_correlations", change.id, target_revision=change.revision
            )
        changes_repo.lock_claim(claim)
        cursor = (
            None
            if plan["complete"]
            else {
                **plan["stamp"],
                "upper_id": plan["upper_id"],
                "after_id": plan["after_id"],
            }
        )
        changes_repo.finish_claim(
            claim,
            cursor=cursor,
            delay=None if plan["complete"] else 0,
            stamp=plan["stamp"],
            error_class=None if plan["reason"] == "eligible" else plan["reason"],
        )
