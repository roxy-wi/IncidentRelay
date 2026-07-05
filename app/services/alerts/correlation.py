import logging
from dataclasses import dataclass
from datetime import datetime

from app.db import database_proxy
from app.modules.db.models import AlertGroup, AlertGroupCorrelation, ServiceDependency
from app.modules.db import alerts_repo


logger = logging.getLogger("oncall.alerts")


ACTIVE_ALERT_GROUP_STATUSES = {"firing", "acknowledged"}
MAX_CORRELATION_DEPTH = 5
MAX_CORRELATED_GROUPS_PER_DIRECTION = 5
MIN_CORRELATION_SCORE = 60


SEVERITY_RANK = {
    "info": 10,
    "low": 20,
    "warning": 30,
    "medium": 40,
    "high": 50,
    "critical": 60,
}


@dataclass
class DependencyPath:
    service_id: int
    dependency_id: int
    direction: str
    depth: int
    dependency_type: str
    criticality: str
    propagation_delay_seconds: int


def _service_label(service):
    if not service:
        return "-"

    return (
        getattr(service, "name", None)
        or getattr(service, "slug", None)
        or f"Service #{getattr(service, 'id', '-')}"
    )


def _seen_at(group):
    return (
        getattr(group, "last_seen_at", None)
        or getattr(group, "first_seen_at", None)
        or getattr(group, "created_at", None)
        or datetime.utcnow()
    )


def _severity_rank(group):
    return SEVERITY_RANK.get(
        str(getattr(group, "severity", "") or "").lower(),
        0,
    )


def _seconds_between(left, right):
    if not left or not right:
        return None

    try:
        return abs((left - right).total_seconds())
    except Exception:
        return None


def _same_environment(left_service, right_service):
    left = getattr(left_service, "environment", None)
    right = getattr(right_service, "environment", None)

    if not left or not right:
        return None

    return left == right


def _dependency_score(current_group, related_group, path):
    current_service = current_group.service
    related_service = related_group.service

    score = 50

    if path.direction == "upstream":
        score += 20
    else:
        score += 10

    if path.depth == 1:
        score += 15
    elif path.depth == 2:
        score += 8
    else:
        score += max(0, 6 - path.depth)

    if path.dependency_type == "hard":
        score += 10

    if path.criticality in {"critical", "important"}:
        score += 10
    elif path.criticality == "optional":
        score -= 10

    environment_match = _same_environment(
        current_service,
        related_service,
    )

    if environment_match is True:
        score += 10
    elif environment_match is False:
        score -= 20

    delta = _seconds_between(
        _seen_at(current_group),
        _seen_at(related_group),
    )

    if delta is not None:
        allowed_delay = max(
            int(path.propagation_delay_seconds or 0),
            300,
        )

        if delta <= allowed_delay:
            score += 15
        elif delta <= allowed_delay * 2:
            score += 5
        else:
            score -= 20

    current_severity = _severity_rank(current_group)
    related_severity = _severity_rank(related_group)

    if path.direction == "upstream" and related_severity >= current_severity:
        score += 5

    if path.direction == "downstream" and current_severity >= related_severity:
        score += 5

    return max(0, min(score, 100))


def _enabled_dependencies_for_service(service_id):
    return (
        ServiceDependency
        .select(ServiceDependency)
        .where(
            (ServiceDependency.service == service_id)
            & (ServiceDependency.enabled == True)  # noqa: E712
            & (ServiceDependency.deleted == False)  # noqa: E712
            & (ServiceDependency.correlation_enabled == True)  # noqa: E712
        )
    )


def _enabled_dependents_for_service(service_id):
    return (
        ServiceDependency
        .select(ServiceDependency)
        .where(
            (ServiceDependency.depends_on_service == service_id)
            & (ServiceDependency.enabled == True)  # noqa: E712
            & (ServiceDependency.deleted == False)  # noqa: E712
            & (ServiceDependency.correlation_enabled == True)  # noqa: E712
        )
    )


def _collect_dependency_paths(service_id, *, direction):
    visited = set()
    paths = []

    def walk(current_service_id, depth):
        if depth > MAX_CORRELATION_DEPTH:
            return

        if direction == "upstream":
            dependencies = _enabled_dependencies_for_service(
                current_service_id,
            )
        else:
            dependencies = _enabled_dependents_for_service(
                current_service_id,
            )

        for dependency in dependencies:
            if direction == "upstream":
                target_service_id = dependency.depends_on_service_id
            else:
                target_service_id = dependency.service_id

            if not target_service_id:
                continue

            if target_service_id in visited:
                continue

            visited.add(target_service_id)

            paths.append(
                DependencyPath(
                    service_id=target_service_id,
                    dependency_id=dependency.id,
                    direction=direction,
                    depth=depth,
                    dependency_type=dependency.dependency_type,
                    criticality=dependency.criticality,
                    propagation_delay_seconds=(
                        dependency.propagation_delay_seconds or 300
                    ),
                )
            )

            walk(target_service_id, depth + 1)

    walk(service_id, 1)

    return paths


def _active_groups_for_services(service_ids, current_group):
    service_ids = list(service_ids)

    if not service_ids:
        return []

    query = (
        AlertGroup
        .select()
        .where(
            (AlertGroup.service.in_(service_ids))
            & (AlertGroup.status.in_(list(ACTIVE_ALERT_GROUP_STATUSES)))
            & (AlertGroup.id != current_group.id)
        )
        .order_by(AlertGroup.id.desc())
        .limit(100)
    )

    team_id = getattr(current_group, "team_id", None)

    if team_id:
        query = query.where(AlertGroup.team == team_id)

    return list(query)


def _reason_for(path, related_group):
    service = getattr(related_group, "service", None)
    service_name = _service_label(service)

    if path.direction == "upstream":
        return (
            f"Current service depends on {service_name}; "
            f"dependency_type={path.dependency_type}; "
            f"criticality={path.criticality}; "
            f"depth={path.depth}"
        )

    return (
        f"{service_name} depends on current service; "
        f"dependency_type={path.dependency_type}; "
        f"criticality={path.criticality}; "
        f"depth={path.depth}"
    )


def _relation_type_for_direction(direction):
    if direction == "upstream":
        return "possible_root_cause"

    return "possible_downstream_impact"


def _root_and_related_groups(current_group, related_group, path):
    if path.direction == "upstream":
        return related_group, current_group

    return current_group, related_group


def _build_context(current_group, related_group, path, score):
    current_service = getattr(current_group, "service", None)
    related_service = getattr(related_group, "service", None)

    return {
        "current_group_id": current_group.id,
        "related_group_id": related_group.id,
        "current_service_id": getattr(current_service, "id", None),
        "current_service_slug": getattr(current_service, "slug", None),
        "related_service_id": getattr(related_service, "id", None),
        "related_service_slug": getattr(related_service, "slug", None),
        "direction": path.direction,
        "depth": path.depth,
        "score": score,
    }


def _upsert_correlation(current_group, related_group, path, now):
    score = _dependency_score(
        current_group,
        related_group,
        path,
    )

    if score < MIN_CORRELATION_SCORE:
        return None

    root_group, related_alert_group = _root_and_related_groups(
        current_group,
        related_group,
        path,
    )

    relation_type = _relation_type_for_direction(path.direction)

    root_service_id = getattr(root_group, "service_id", None)
    related_service_id = getattr(related_alert_group, "service_id", None)

    create_defaults = {
        "team": getattr(current_group, "team_id", None),
        "root_service": root_service_id,
        "related_service": related_service_id,
        "dependency": path.dependency_id,
        "direction": path.direction,
        "score": score,
        "depth": path.depth,
        "dependency_type": path.dependency_type,
        "criticality": path.criticality,
        "reason": _reason_for(path, related_group),
        "active": True,
        "first_seen_at": now,
        "last_seen_at": now,
        "updated_at": now,
        "context": _build_context(
            current_group,
            related_group,
            path,
            score,
        ),
    }

    correlation, created = AlertGroupCorrelation.get_or_create(
        root_group=root_group.id,
        related_group=related_alert_group.id,
        relation_type=relation_type,
        defaults=create_defaults,
    )

    if created:
        _record_correlation_detected_events(correlation)
        return correlation

    was_active = bool(correlation.active)

    update_values = dict(create_defaults)
    update_values.pop("first_seen_at", None)

    (
        AlertGroupCorrelation
        .update(**update_values)
        .where(AlertGroupCorrelation.id == correlation.id)
        .execute()
    )

    correlation = AlertGroupCorrelation.get_by_id(correlation.id)

    if not was_active and correlation.active:
        _record_correlation_detected_events(correlation)

    return correlation


def _deactivate_stale_correlations(group, now, keep_ids=None):
    """Deactivate correlations that are no longer matched."""
    keep_ids = set(keep_ids or [])

    query = AlertGroupCorrelation.select().where(
        (
            (AlertGroupCorrelation.root_group == group.id)
            | (AlertGroupCorrelation.related_group == group.id)
        )
        & (AlertGroupCorrelation.active == True)  # noqa: E712
    )

    if keep_ids:
        query = query.where(AlertGroupCorrelation.id.not_in(keep_ids))

    stale_correlations = list(query)

    if not stale_correlations:
        return []

    stale_ids = [
        item.id
        for item in stale_correlations
    ]

    (
        AlertGroupCorrelation
        .update(
            active=False,
            updated_at=now,
            last_seen_at=now,
        )
        .where(AlertGroupCorrelation.id.in_(stale_ids))
        .execute()
    )

    for correlation in stale_correlations:
        correlation.active = False
        correlation.updated_at = now
        correlation.last_seen_at = now

        _record_correlation_deactivated_events(correlation)

    return stale_correlations


def refresh_alert_group_correlations(group):
    """Recalculate and persist dependency-aware correlations for a group."""
    now = datetime.utcnow()

    with database_proxy.atomic():
        if getattr(group, "status", None) not in ACTIVE_ALERT_GROUP_STATUSES:
            _deactivate_stale_correlations(
                group,
                now,
                keep_ids=set(),
            )
            return []

        if not getattr(group, "service_id", None):
            _deactivate_stale_correlations(
                group,
                now,
                keep_ids=set(),
            )
            return []

        upstream_paths = _collect_dependency_paths(
            group.service_id,
            direction="upstream",
        )
        downstream_paths = _collect_dependency_paths(
            group.service_id,
            direction="downstream",
        )

        paths_by_service_id = {}

        for path in upstream_paths + downstream_paths:
            current = paths_by_service_id.get(path.service_id)

            if not current or path.depth < current.depth:
                paths_by_service_id[path.service_id] = path

        related_groups = _active_groups_for_services(
            paths_by_service_id.keys(),
            group,
        )

        created_or_updated = []
        active_correlation_ids = set()

        for related_group in related_groups:
            path = paths_by_service_id.get(related_group.service_id)

            if not path:
                continue

            correlation = _upsert_correlation(
                group,
                related_group,
                path,
                now,
            )

            if correlation:
                created_or_updated.append(correlation)
                active_correlation_ids.add(correlation.id)

        _deactivate_stale_correlations(
            group,
            now,
            keep_ids=active_correlation_ids,
        )

        if created_or_updated:
            logger.info(
                "alert group correlations refreshed",
                extra={
                    "extra": {
                        "alert_group_id": group.id,
                        "service_id": group.service_id,
                        "correlations": len(created_or_updated),
                    }
                },
            )

        return created_or_updated


def refresh_alert_group_correlations_safely(group, reason=None):
    """Refresh saved correlations without breaking alert lifecycle."""
    try:
        return refresh_alert_group_correlations(group)
    except Exception:
        logger.exception(
            "alert group correlation refresh failed",
            extra={
                "extra": {
                    "alert_group_id": getattr(group, "id", None),
                    "service_id": getattr(group, "service_id", None),
                    "status": getattr(group, "status", None),
                    "reason": reason,
                }
            },
        )

    return []


def _active_correlations_for_group(group):
    return (
        AlertGroupCorrelation
        .select()
        .where(
            (
                (AlertGroupCorrelation.root_group == group.id)
                | (AlertGroupCorrelation.related_group == group.id)
            )
            & (AlertGroupCorrelation.active == True)  # noqa: E712
        )
        .order_by(AlertGroupCorrelation.score.desc())
        .limit(10)
    )


def get_saved_alert_group_correlation_summary(group):
    """Return saved active correlation records grouped for rendering."""
    root_candidates = []
    downstream_impacts = []

    for correlation in _active_correlations_for_group(group):
        root_group = correlation.root_group
        related_group = correlation.related_group

        if (
            root_group.status not in ACTIVE_ALERT_GROUP_STATUSES
            or related_group.status not in ACTIVE_ALERT_GROUP_STATUSES
        ):
            continue

        if related_group.id == group.id:
            root_candidates.append(correlation)
            continue

        if root_group.id == group.id:
            downstream_impacts.append(correlation)

    return {
        "root_candidates": root_candidates,
        "downstream_impacts": downstream_impacts,
    }


def _group_label(group):
    service = getattr(group, "service", None)
    service_name = _service_label(service)

    return (
        f"#{group.id} {service_name}: {group.title} "
        f"({group.status}, {group.severity or '-'})"
    )


def _correlation_group_event_label(group):
    """Return compact alert group label for timeline events."""
    service = getattr(group, "service", None)

    service_name = (
        getattr(service, "name", None)
        or getattr(service, "slug", None)
        or "-"
    )

    return f"#{group.id} {service_name}: {group.title}"


def _correlation_event_message(correlation, action):
    """Return timeline event message for correlation lifecycle."""
    root_group = correlation.root_group
    related_group = correlation.related_group

    return (
        f"Correlation {action}: "
        f"{_correlation_group_event_label(root_group)} -> "
        f"{_correlation_group_event_label(related_group)} "
        f"({correlation.relation_type}, score={correlation.score})"
    )


def _record_correlation_group_event(group_id, event_type, message):
    """Record one alert group timeline event."""
    alerts_repo.create_alert_event(
        group_id=group_id,
        event_type=event_type,
        message=message,
        user_id=None,
    )


def _record_correlation_events(correlation, event_type, message):
    """Record correlation event on both related alert group timelines."""
    group_ids = {
        correlation.root_group_id,
        correlation.related_group_id,
    }

    for group_id in group_ids:
        if not group_id:
            continue

        _record_correlation_group_event(
            group_id,
            event_type,
            message,
        )


def _record_correlation_detected_events(correlation):
    """Record correlation detected timeline events."""
    message = _correlation_event_message(correlation, "detected")

    _record_correlation_events(
        correlation,
        "correlation_detected",
        message,
    )


def _record_correlation_deactivated_events(correlation):
    """Record correlation deactivated timeline events."""
    message = _correlation_event_message(correlation, "deactivated")

    _record_correlation_events(
        correlation,
        "correlation_deactivated",
        message,
    )


def format_correlation_plain(group):
    """Return plain-text saved correlation block for notifications."""
    summary = get_saved_alert_group_correlation_summary(group)

    root_candidates = summary["root_candidates"]
    downstream_impacts = summary["downstream_impacts"]

    if not root_candidates and not downstream_impacts:
        return []

    lines = ["Correlation:"]

    if root_candidates:
        best_score = max(item.score for item in root_candidates)
        lines.append(f"Role: possible_symptom")
        lines.append(f"Score: {best_score}")
        lines.append("Possible root cause:")

        for item in root_candidates[:MAX_CORRELATED_GROUPS_PER_DIRECTION]:
            lines.append(
                "- "
                f"{_group_label(item.root_group)} "
                f"(score={item.score})"
            )

    if downstream_impacts:
        best_score = max(item.score for item in downstream_impacts)

        if not root_candidates:
            lines.append("Role: possible_root_cause")
            lines.append(f"Score: {best_score}")

        lines.append("Possible downstream impact:")

        for item in downstream_impacts[:MAX_CORRELATED_GROUPS_PER_DIRECTION]:
            lines.append(
                "- "
                f"{_group_label(item.related_group)} "
                f"(score={item.score})"
            )

    return lines


def format_correlation_markdown(group):
    """Return Markdown saved correlation block for rich notifications."""
    summary = get_saved_alert_group_correlation_summary(group)

    root_candidates = summary["root_candidates"]
    downstream_impacts = summary["downstream_impacts"]

    if not root_candidates and not downstream_impacts:
        return None

    lines = []

    if root_candidates:
        best_score = max(item.score for item in root_candidates)
        lines.append("**Role:** possible_symptom")
        lines.append(f"**Score:** {best_score}")
        lines.append("")
        lines.append("**Possible root cause:**")

        for item in root_candidates[:MAX_CORRELATED_GROUPS_PER_DIRECTION]:
            lines.append(
                "- "
                f"{_group_label(item.root_group)} "
                f"(score={item.score})"
            )

    if downstream_impacts:
        best_score = max(item.score for item in downstream_impacts)

        if not root_candidates:
            lines.append("**Role:** possible_root_cause")
            lines.append(f"**Score:** {best_score}")
            lines.append("")

        lines.append("**Possible downstream impact:**")

        for item in downstream_impacts[:MAX_CORRELATED_GROUPS_PER_DIRECTION]:
            lines.append(
                "- "
                f"{_group_label(item.related_group)} "
                f"(score={item.score})"
            )

    return "\n".join(lines)
