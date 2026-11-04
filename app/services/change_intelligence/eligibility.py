"""One opt-in policy for lifecycle requests, discovery and publication."""

from datetime import timedelta

from app.modules.common import utc_now
from app.modules.db.models import AlertGroupEpisode, Service
from app.modules.db.services_repo import is_service_active
from app.services.routing.matcher.matchers import match_value

HISTORY_DAYS = 7


def exclusion_matches(child, rule):
    """All clauses must match the same child; missing labels never match."""
    source = rule.get("source")
    labels = rule.get("labels") or {}
    if not source and not labels:
        return False
    if source is not None and not match_value(child.get("source"), source):
        return False
    actual = child.get("labels") or {}
    return all(
        key in actual and match_value(actual[key], value)
        for key, value in labels.items()
    )


def episode_eligibility(episode, *, now=None):
    """Return a stable diagnostic; never rebuild unknown historical context."""
    if episode.start_quality != "exact" or episode.started_at is None:
        return "unknown_start"
    if episode.correlation_context is None:
        return "unknown_context"
    if not episode.correlation_service_id:
        return "no_service"
    service = Service.get_or_none(Service.id == episode.correlation_service_id)
    if not is_service_active(service):
        return "service_unavailable"
    context = episode.correlation_context
    if str(service.uid) != context.get("service_uid"):
        return "service_replaced"
    if service.team_id != context.get("team_id"):
        return "service_moved"
    if not service.change_correlation_enabled:
        return "disabled"
    if episode.started_at < (now or utc_now()) - timedelta(days=HISTORY_DAYS):
        return "outside_history"
    children = context.get("children", {}).values()
    exclusions = service.change_correlation_exclusions or []
    if not any(
        not any(exclusion_matches(child, rule) for rule in exclusions)
        for child in children
    ):
        return "all_excluded" if context.get("children") else "no_children"
    return "eligible"


def eligible_episode_query(*, now=None):
    """Indexed first gate; callers also apply the exact child exclusions."""
    return (
        AlertGroupEpisode.select(AlertGroupEpisode)
        .join(Service, on=(AlertGroupEpisode.correlation_service_id == Service.id))
        .where(
            AlertGroupEpisode.started_at
            >= (now or utc_now()) - timedelta(days=HISTORY_DAYS),
            AlertGroupEpisode.start_quality == "exact",
            AlertGroupEpisode.correlation_context.is_null(False),
            Service.deleted == False,
            Service.enabled == True,
            Service.change_correlation_enabled == True,
        )
    )
