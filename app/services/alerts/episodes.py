"""Episode lifecycle and eligible Change Intelligence discovery requests.

The caller owns the write transaction and locks the group before its episode.
Eligibility and durable discovery requests are evaluated inside that transaction.
Repositories must not import this service.
"""

from peewee import fn

from app.modules.db import alert_episodes_repo, changes_repo
from app.modules.db.models import Alert, AlertGroup, AlertGroupEpisode, Service


def open_episode(group, *, started_at=None, event=None):
    """Keep the current cycle; create one only for an explicit known start."""
    alert_episodes_repo._require_transaction()
    if group.status in alert_episodes_repo.TERMINAL_STATUSES or group.merged_into_id:
        return None
    if event is not None and event.group_id != group.id:
        raise ValueError("Episode event belongs to another AlertGroup")
    episode = alert_episodes_repo._current_episode(group)
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
        correlation_context={"children": {}},
    )
    group.current_episode = episode
    group.save(only=[AlertGroup.current_episode])
    refresh_context(group)
    return episode


def close_episode(group, *, state, ended_at, event=None):
    """Close the current cycle without creating history for terminal groups."""
    alert_episodes_repo._require_transaction()
    if state not in alert_episodes_repo.TERMINAL_STATUSES:
        raise ValueError("An episode can only close as resolved or merged")
    if event is not None and event.group_id != group.id:
        raise ValueError("Episode event belongs to another AlertGroup")
    episode = alert_episodes_repo._current_episode(group)
    if episode is None:
        return None
    refresh_context(group)
    episode = AlertGroupEpisode.get_by_id(episode.id)
    episode.context_revision += 1
    episode.state = state
    episode.ended_at = ended_at
    episode.end_event = event
    episode.save(
        only=[
            AlertGroupEpisode.context_revision,
            AlertGroupEpisode.state,
            AlertGroupEpisode.ended_at,
            AlertGroupEpisode.end_event,
        ]
    )
    group.current_episode = None
    group.save(only=[AlertGroup.current_episode])
    request_discovery(episode)
    return episode


def request_discovery(episode):
    """Exclude ineligible episodes before creating any search work."""
    from app.services.change_intelligence.eligibility import episode_eligibility

    if episode_eligibility(episode) == "eligible":
        changes_repo.request_job(
            "discover_episode", episode.id, target_revision=episode.context_revision
        )


def refresh_context(group, *, alerts=None, observed_alert=None):
    """Snapshot observed children under the caller's group lock.

    A NULL context belongs to an older episode and is deliberately left alone.
    Resolved children already observed in this cycle remain in its membership.
    """
    alert_episodes_repo._require_transaction()
    episode = alert_episodes_repo._current_episode(group)
    if episode is None or episode.correlation_context is None:
        return
    old = episode.correlation_context
    children = dict(old.get("children", {}))
    if alerts is None:
        alerts = Alert.select().where(Alert.group == group.id).order_by(Alert.id)
    for alert in alerts:
        key = str(alert.id)
        if key in children or alert.status != "resolved":
            children[key] = {"source": alert.source, "labels": alert.labels or {}}
    if observed_alert is not None:
        if observed_alert.group_id != group.id:
            raise ValueError("Observed alert belongs to another group")
        children[str(observed_alert.id)] = {
            "source": observed_alert.source,
            "labels": observed_alert.labels or {},
        }
    service = (
        Service.get_or_none(Service.id == group.service_id)
        if group.service_id
        else None
    )
    context = {
        "service_id": group.service_id,
        "service_uid": str(service.uid) if service else None,
        "team_id": service.team_id if service else None,
        "environment": service.environment if service else None,
        "children": children,
    }
    if old == context:
        return
    episode.correlation_context = context
    episode.correlation_service_id = group.service_id
    episode.context_revision += 1
    episode.save(
        only=[
            AlertGroupEpisode.correlation_context,
            AlertGroupEpisode.correlation_service_id,
            AlertGroupEpisode.context_revision,
        ]
    )
    request_discovery(episode)
