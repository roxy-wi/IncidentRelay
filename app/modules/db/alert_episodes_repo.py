"""Episode lookup and transaction preconditions for lifecycle services.

Callers lock the group before its episode. A lifecycle operation that also
updates an Incident must lock that Incident first. Episode transitions and
discovery eligibility are handled by app.services.alerts.episodes.
"""
from app.db import database_proxy as db
from app.modules.db.models import AlertGroupEpisode


TERMINAL_STATUSES = frozenset({"resolved", "merged"})


def _require_transaction():
    """Reject episode operations without the caller's write transaction."""
    if not db.in_transaction():
        raise RuntimeError("Episode writes require the caller's transaction")


def _current_episode(group):
    """Load and validate the current episode reference under the group lock."""
    if not group.current_episode_id:
        return None
    episode = AlertGroupEpisode.get_by_id(group.current_episode_id)
    if episode.alert_group_id != group.id or episode.state != "open":
        raise RuntimeError("AlertGroup current episode is inconsistent")
    return episode
