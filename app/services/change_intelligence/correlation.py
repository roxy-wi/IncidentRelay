"""Bounded automatic suggestions; never change operational state or reviews."""

from collections import deque
from datetime import timedelta
import time

from peewee import fn

from app.modules.common import utc_now
from app.modules.db import changes_repo, incident_core_repo
from app.modules.db.models import (
    AlertGroupEpisode,
    Change,
    ChangeAlertGroupCorrelation,
    ChangeEvent,
    ChangeGraphState,
    ChangeImpact,
    ChangeIntegration,
    ChangeJob,
    ChangeService,
    ChangeSource,
    Service,
    ServiceDependency,
)
from app.modules.db.services_repo import is_service_active
from app.services.change_intelligence.authorization import (
    active_integration_group,
    lock_row,
)
from app.services.change_intelligence.eligibility import (
    HISTORY_DAYS,
    eligible_episode_query,
    episode_eligibility,
)
from app.services.change_intelligence.projection import TERMINAL_TYPES
from app.services.change_intelligence.resolver import (
    ENGINE_VERSION as REFERENCE_ENGINE,
    StaleChangeInputs,
)
from app.settings import Config

ENGINE_VERSION = "correlation-v1"
WINDOW_SECONDS = 7200
MAX_DEPTH = 5
MAX_IMPACTS = 200
MAX_EDGES = 1000
COMPUTE_SECONDS = 5


class CorrelationLimitReached(RuntimeError):
    """A partial graph is not published as a complete explanation."""


def relevance_score(relation, depth, gap_seconds, environment_match):
    """Relation, then elapsed time; the result is relevance, not probability."""
    base = {"changed": 90, "reported_affected": 80}.get(relation)
    if base is None:
        base = 70 - 5 * (depth - 1)
    recency = max(0, 4 - int(gap_seconds * 4 // WINDOW_SECONDS))
    return base + recency + int(environment_match)


def history_changes(now):
    """Keep still-running operations even when their start is older."""
    return Change.select().where(
        (Change.status == "running")
        | (Change.last_occurred_at >= now - timedelta(days=HISTORY_DAYS))
    )


def automatic_work_needed(change):
    """Skip old operations unless an existing projection needs deactivation."""
    if change.status == "running" or (
        change.last_occurred_at
        and change.last_occurred_at >= utc_now() - timedelta(days=HISTORY_DAYS)
    ):
        return True
    return (
        ChangeImpact.select()
        .where(ChangeImpact.change == change.id, ChangeImpact.active == True)
        .exists()
        or ChangeAlertGroupCorrelation.select()
        .where(
            ChangeAlertGroupCorrelation.change == change.id,
            ChangeAlertGroupCorrelation.active == True,
        )
        .exists()
    )


def request_after_mapping(change):
    """Polling unchanged pending references must not restart failed projections."""
    if not automatic_work_needed(change):
        return
    existing = ChangeJob.get_or_none(
        ChangeJob.job_type == "refresh_impacts", ChangeJob.entity_id == change.id
    )
    if existing and existing.target_revision >= change.revision:
        if existing.state in {"pending", "running", "dead"}:
            return
        if (
            existing.engine_version == ENGINE_VERSION
            and existing.last_error_class != "mapping_pending"
        ):
            return
    changes_repo.request_job(
        "refresh_impacts", change.id, target_revision=change.revision
    )


def input_stamp(change, integration, graph_revision):
    """Capture these revisions before reading any derived input."""
    return {
        "target_revision": change.revision,
        "auth_revision": integration.auth_revision,
        "graph_revision": graph_revision,
        "engine_version": ENGINE_VERSION,
    }


def mapping_current(change, integration, stamp):
    """Trust canonical links only after a complete pass under these inputs."""
    source = ChangeSource.get_by_id(change.source_id)
    job = ChangeJob.get_or_none(
        ChangeJob.job_type == "resolve_references", ChangeJob.entity_id == change.id
    )
    return bool(
        integration.active
        and source.active
        and active_integration_group(integration)
        and job
        and job.state in {"done", "pending"}
        and job.cursor is None
        and job.last_error_class is None
        and job.requested_generation == job.claimed_generation
        and job.engine_version == REFERENCE_ENGINE
        and all(
            getattr(job, key) == stamp[key]
            for key in ("target_revision", "graph_revision", "auth_revision")
        )
    )


def operation_interval(change, now):
    """A terminal-only operation starts at its earliest terminal event time."""
    start = change.started_at
    if start is None:
        start = (
            ChangeEvent.select(fn.MIN(ChangeEvent.occurred_at))
            .where(
                ChangeEvent.change == change.id,
                ChangeEvent.event_type.in_(TERMINAL_TYPES),
            )
            .scalar()
        )
    end = now if change.status == "running" else change.completed_at
    if change.lifecycle_conflict or start is None or end is None:
        return None, "unknown_interval"
    if end < start:
        return None, "invalid_interval"
    if change.status != "running" and end < now - timedelta(days=HISTORY_DAYS):
        return None, "outside_history"
    return (start, end), None


def compatible_environment(first, second):
    """Unknown is allowed as unknown evidence; known mismatches are excluded."""
    return not first or not second or first == second


def compute_paths(change, *, deadline):
    """Breadth first provider-to-consumer walk with stable shortest paths."""
    links = list(
        ChangeService.select()
        .where(
            ChangeService.change == change.id,
            ChangeService.verification_state == "trusted",
        )
        .order_by(ChangeService.service, ChangeService.relation_type)
        .limit(MAX_IMPACTS + 1)
    )
    if len(links) > MAX_IMPACTS:
        raise CorrelationLimitReached()
    services = {}

    def usable(service_id):
        if service_id not in services:
            service = Service.get_or_none(Service.id == service_id)
            services[service_id] = service if is_service_active(service) else None
        return services[service_id]

    impacts, candidates = [], {}
    edge_count = 0
    for link in links:
        origin = usable(link.service_id)
        if origin is None or not compatible_environment(
            change.environment, origin.environment
        ):
            continue
        direct = {
            "service_id": origin.id,
            "origin_service_id": origin.id,
            "relation": link.relation_type,
            "depth": 0,
            "path": [],
            "environment": origin.environment,
        }
        candidates.setdefault(origin.id, []).append(direct)
        if link.relation_type != "changed":
            continue
        queue = deque([direct])
        visited = {origin.id}
        while queue:
            if time.monotonic() > deadline:
                raise CorrelationLimitReached()
            current = queue.popleft()
            impacts.append(current)
            if len(impacts) > MAX_IMPACTS:
                raise CorrelationLimitReached()
            if current["depth"] >= MAX_DEPTH:
                continue
            edges = list(
                ServiceDependency.select()
                .where(
                    ServiceDependency.depends_on_service == current["service_id"],
                    ServiceDependency.enabled == True,
                    ServiceDependency.deleted == False,
                    ServiceDependency.correlation_enabled == True,
                    ServiceDependency.dependency_type.in_(("hard", "soft", "external")),
                )
                .order_by(ServiceDependency.service, ServiceDependency.id)
                .limit(MAX_EDGES - edge_count + 1)
            )
            edge_count += len(edges)
            if edge_count > MAX_EDGES:
                raise CorrelationLimitReached()
            for edge in edges:
                service = usable(edge.service_id)
                if (
                    service is None
                    or service.id in visited
                    or not compatible_environment(
                        change.environment, service.environment
                    )
                    or not compatible_environment(
                        origin.environment, service.environment
                    )
                    or not compatible_environment(
                        current["environment"], service.environment
                    )
                ):
                    continue
                visited.add(service.id)
                item = {
                    "service_id": service.id,
                    "origin_service_id": origin.id,
                    "relation": "dependency",
                    "depth": current["depth"] + 1,
                    "environment": service.environment,
                    "path": current["path"]
                    + [
                        {
                            "dependency_id": edge.id,
                            "provider_service_id": edge.depends_on_service_id,
                            "consumer_service_id": edge.service_id,
                            "dependency_type": edge.dependency_type,
                            "propagation_delay_seconds": edge.propagation_delay_seconds,
                        }
                    ],
                }
                candidates.setdefault(service.id, []).append(item)
                queue.append(item)
    return impacts, candidates


def suggestion(change, episode, candidates, interval):
    """Select one deterministic explanation for this exact episode."""
    if interval is None or episode_eligibility(episode) != "eligible":
        return None
    start, end = interval
    if not start <= episode.started_at <= end + timedelta(seconds=WINDOW_SECONDS):
        return None
    environment = episode.correlation_context.get("environment")
    if not compatible_environment(change.environment, environment):
        return None
    gap = max(0, int((episode.started_at - end).total_seconds()))
    choices = []
    for path in candidates.get(episode.correlation_service_id, []):
        if not compatible_environment(path["environment"], environment):
            continue
        known = bool(
            change.environment and environment and change.environment == environment
        )
        score = relevance_score(path["relation"], path["depth"], gap, known)
        choices.append(
            (
                (
                    -score,
                    path["depth"],
                    path["origin_service_id"],
                    tuple(edge["dependency_id"] for edge in path["path"]),
                ),
                path,
            )
        )
    if not choices:
        return None
    key, path = min(choices, key=lambda item: item[0])
    return {
        "score": -key[0],
        "reason": path["relation"],
        "active": True,
        "evidence": {
            "origin_service_id": path["origin_service_id"],
            "service_id": episode.correlation_service_id,
            "depth": path["depth"],
            "path": path["path"],
            "environment": "match" if change.environment and environment else "unknown",
            "interval_start": start.isoformat(),
            "interval_end": end.isoformat(),
            "episode_start": episode.started_at.isoformat(),
            "gap_seconds": gap,
        },
    }


def compute_correlation_batch(claim):
    """Read a bounded batch outside write locks; publication validates all inputs."""
    now = utc_now()
    deadline = time.monotonic() + COMPUTE_SECONDS
    graph_revision = ChangeGraphState.get_by_id(1).revision
    change = Change.get_or_none(Change.id == claim.entity_id)
    if change is None:
        return None
    integration = ChangeIntegration.get_by_id(change.integration_id)
    stamp = input_stamp(change, integration, graph_revision)
    impacts, candidates = [], {}
    interval, error = operation_interval(change, now)
    if not mapping_current(change, integration, stamp):
        error, interval = "mapping_pending", None
    elif error != "outside_history":
        try:
            impacts, candidates = compute_paths(change, deadline=deadline)
        except CorrelationLimitReached:
            error, interval = "limit_exceeded", None
            impacts, candidates = [], {}
    cursor = claim.cursor or {}
    if any(cursor.get(key) != value for key, value in stamp.items()):
        cursor = {}
    existing = ChangeAlertGroupCorrelation.select(
        ChangeAlertGroupCorrelation.episode
    ).where(ChangeAlertGroupCorrelation.change == change.id)
    eligible = (
        eligible_episode_query(now=now)
        .where(AlertGroupEpisode.correlation_service_id.in_(list(candidates)))
        .select(AlertGroupEpisode.id)
    )
    query = AlertGroupEpisode.select().where(
        AlertGroupEpisode.id.in_(eligible) | AlertGroupEpisode.id.in_(existing)
    )
    upper = cursor.get("upper_id")
    if upper is None:
        upper = query.select(fn.MAX(AlertGroupEpisode.id)).scalar() or 0
    episodes = list(
        query.where(
            AlertGroupEpisode.id > cursor.get("after_id", 0),
            AlertGroupEpisode.id <= upper,
        )
        .order_by(AlertGroupEpisode.id)
        .limit(Config.CHANGE_WORKER_BATCH_SIZE)
    )
    results = []
    for episode in episodes:
        if time.monotonic() > deadline:
            raise CorrelationLimitReached()
        results.append((episode, suggestion(change, episode, candidates, interval)))
    after = episodes[-1].id if episodes else upper
    return {
        "change": change,
        "stamp": stamp,
        "impacts": impacts,
        "results": results,
        "computed_at": now,
        "error": error,
        "upper_id": upper,
        "after_id": after,
        "complete": after >= upper or len(episodes) < Config.CHANGE_WORKER_BATCH_SIZE,
    }


def publish_correlation_batch(claim, plan):
    """Lock graph, principal, Change, episodes, then job; preserve human fields."""
    with incident_core_repo.write_transaction():
        if plan is None:
            changes_repo.lock_claim(claim)
            changes_repo.finish_claim(claim, error_class="entity_missing")
            return
        graph = lock_row(ChangeGraphState.select().where(ChangeGraphState.id == 1))
        integration = lock_row(
            ChangeIntegration.select().where(
                ChangeIntegration.id == plan["change"].integration_id
            )
        )
        change = lock_row(Change.select().where(Change.id == claim.entity_id))
        stamp = plan["stamp"]
        if change is None or stamp != input_stamp(change, integration, graph.revision):
            raise StaleChangeInputs()
        for previous, values in plan["results"]:
            current = lock_row(
                AlertGroupEpisode.select().where(AlertGroupEpisode.id == previous.id)
            )
            if current is None or current.context_revision != previous.context_revision:
                raise StaleChangeInputs()
            if values and episode_eligibility(current) != "eligible":
                raise StaleChangeInputs()
        changes_repo.lock_claim(claim)
        ChangeImpact.update(active=False).where(
            ChangeImpact.change == change.id
        ).execute()
        for path in plan["impacts"]:
            values = {
                "depth": path["depth"],
                "reason": path["relation"],
                "dependency_path_snapshot": path["path"],
                "input_stamp": stamp,
                "engine_version": ENGINE_VERSION,
                "computed_at": plan["computed_at"],
                "active": True,
            }
            row = ChangeImpact.get_or_none(
                ChangeImpact.change == change.id,
                ChangeImpact.origin_service == path["origin_service_id"],
                ChangeImpact.service == path["service_id"],
            )
            if row:
                ChangeImpact.update(**values).where(ChangeImpact.id == row.id).execute()
            else:
                ChangeImpact.create(
                    change=change.id,
                    service=path["service_id"],
                    origin_service=path["origin_service_id"],
                    **values,
                )
        for episode, values in plan["results"]:
            row = ChangeAlertGroupCorrelation.get_or_none(
                ChangeAlertGroupCorrelation.change == change.id,
                ChangeAlertGroupCorrelation.episode == episode.id,
            )
            if values is None and row is None:
                continue
            values = {
                **(values or {"active": False}),
                "input_stamp": {**stamp, "episode_revision": episode.context_revision},
                "engine_version": ENGINE_VERSION,
                "computed_at": plan["computed_at"],
                "updated_at": utc_now(),
            }
            if row:
                # Do not assign relation_type/review_status/review_evidence/row_version.
                ChangeAlertGroupCorrelation.update(**values).where(
                    ChangeAlertGroupCorrelation.id == row.id
                ).execute()
            else:
                ChangeAlertGroupCorrelation.create(
                    change=change.id, episode=episode.id, **values
                )
        cursor = (
            None
            if plan["complete"]
            else {**stamp, "upper_id": plan["upper_id"], "after_id": plan["after_id"]}
        )
        changes_repo.finish_claim(
            claim,
            cursor=cursor,
            delay=None if plan["complete"] else 0,
            stamp=stamp,
            error_class=plan["error"],
        )
        if plan["complete"] and any(path["depth"] > 0 for path in plan["impacts"]):
            from app.services.change_intelligence.timeline import request_publication

            request_publication(change)


def is_current_suggestion(row, *, episode=None, graph_revision=None):
    """Check one proposal without scanning every Change for the episode."""
    if not row.active or row.review_status != "suggested":
        return False
    episode = episode or AlertGroupEpisode.get_by_id(row.episode_id)
    if episode_eligibility(episode) != "eligible":
        return False
    if graph_revision is None:
        graph_revision = ChangeGraphState.get_by_id(1).revision
    change = row.change
    integration = change.integration
    stamp = input_stamp(change, integration, graph_revision)
    return (
        row.engine_version == ENGINE_VERSION
        and row.input_stamp == {**stamp, "episode_revision": episode.context_revision}
        and mapping_current(change, integration, stamp)
    )


def current_suggestions(episode):
    """Internal projection gate; callers must authorize the episode before use.

    Stage 9 will build reader-scoped Explain responses, including path redaction.
    Stored active flags alone are never an authorization or freshness guarantee.
    """
    episode = AlertGroupEpisode.get_by_id(episode.id)
    if episode_eligibility(episode) != "eligible":
        return []
    graph_revision = ChangeGraphState.get_by_id(1).revision
    rows = []
    query = ChangeAlertGroupCorrelation.select().where(
        ChangeAlertGroupCorrelation.episode == episode.id,
        ChangeAlertGroupCorrelation.active == True,
        ChangeAlertGroupCorrelation.review_status == "suggested",
    )
    for row in query:
        if is_current_suggestion(row, episode=episode, graph_revision=graph_revision):
            rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            -row.score,
            row.evidence.get("gap_seconds", 0),
            str(row.change.uid),
        ),
    )
