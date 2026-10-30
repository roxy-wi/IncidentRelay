"""Episode writes performed inside the AlertGroup lifecycle transaction.

Callers lock the group before its episode. A lifecycle operation that also
updates an Incident must lock that Incident first. No worker runs here.
"""

from peewee import fn

from app.db import database_proxy as db
from app.modules.db import changes_repo
from app.modules.db.models import AlertGroup, AlertGroupEpisode


TERMINAL_STATUSES = frozenset({"resolved", "merged"})


def _require_transaction():
    if not db.in_transaction():
        raise RuntimeError("Episode writes require the caller's transaction")


def _current_episode(group):
    if not group.current_episode_id:
        return None
    episode = AlertGroupEpisode.get_by_id(group.current_episode_id)
    if episode.alert_group_id != group.id or episode.state != "open":
        raise RuntimeError("AlertGroup current episode is inconsistent")
    return episode


def open_episode(group, *, started_at=None, event=None):
    """Keep the current cycle; create one only for an explicit known start."""
    _require_transaction()
    if group.status in TERMINAL_STATUSES or group.merged_into_id:
        return None
    if event is not None and event.group_id != group.id:
        raise ValueError("Episode event belongs to another AlertGroup")
    episode = _current_episode(group)
    if episode is not None:
        if event is not None and episode.start_event_id is None:
            episode.start_event = event
            episode.save(only=[AlertGroupEpisode.start_event])
        return episode

    if started_at is None:
        # Legacy active groups remain untracked until their next genuine reopen.
        return None

    ordinal = (
        AlertGroupEpisode.select(fn.MAX(AlertGroupEpisode.ordinal))
        .where(AlertGroupEpisode.alert_group == group.id)
        .scalar()
        or 0
    ) + 1
    episode = AlertGroupEpisode.create(
        alert_group=group.id,
        ordinal=ordinal,
        started_at=started_at,
        start_quality="exact" if started_at is not None else "unknown",
        start_event=event,
    )
    group.current_episode = episode
    group.save(only=[AlertGroup.current_episode])
    changes_repo.request_job("discover_episode", episode.id, target_revision=1)
    return episode


def close_episode(group, *, state, ended_at, event=None):
    """Close the current cycle without creating history for terminal groups."""
    _require_transaction()
    if state not in TERMINAL_STATUSES:
        raise ValueError("An episode can only close as resolved or merged")
    if event is not None and event.group_id != group.id:
        raise ValueError("Episode event belongs to another AlertGroup")
    episode = _current_episode(group)
    if episode is None:
        return None
    episode.state = state
    episode.ended_at = ended_at
    episode.end_event = event
    episode.save(
        only=[
            AlertGroupEpisode.state,
            AlertGroupEpisode.ended_at,
            AlertGroupEpisode.end_event,
        ]
    )
    group.current_episode = None
    group.save(only=[AlertGroup.current_episode])
    changes_repo.request_job("discover_episode", episode.id, target_revision=2)
    return episode
