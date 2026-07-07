from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.modules.db.models import AlertGroup, Service, ServiceDependency, Team
from app.services.service_catalog.impact_scoring import (
    alert_group_impact_score,
    clamp_impact_score,
    combined_impact_score,
    max_severity,
    max_status,
    normalize_severity,
    normalize_status,
    priority_slug_for_alert_group,
    propagate_dependency_impact,
    status_from_impact_score,
    status_impact_score,
    status_rank,
)

OPEN_ALERT_GROUP_STATUSES = {"firing", "acknowledged"}

IMPACT_STATUSES = {
    "operational",
    "degraded",
    "partial_outage",
    "major_outage",
    "maintenance",
    "disabled",
    "unknown",
}

STATUS_RANK = {
    "disabled": -1,
    "operational": 0,
    "unknown": 0,
    "maintenance": 1,
    "degraded": 2,
    "partial_outage": 3,
    "major_outage": 4,
}

SEVERITY_RANK = {
    None: 0,
    "": 0,
    "info": 1,
    "warning": 2,
    "warn": 2,
    "high": 3,
    "critical": 4,
}

CRITICALITY_RANK = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

TIER_RANK = {
    "tier_4": 1,
    "tier_3": 2,
    "tier_2": 3,
    "tier_1": 4,
}

DEPENDENCY_CRITICALITY_RANK = {
    "optional": 1,
    "important": 2,
    "required": 3,
}

DEPENDENCY_TYPE_RANK = {
    "informational": 0,
    "external": 1,
    "soft": 2,
    "hard": 3,
}


@dataclass
class AlertImpactStats:
    open_alert_groups: int = 0
    critical_open_alert_groups: int = 0
    high_open_alert_groups: int = 0
    warning_open_alert_groups: int = 0
    priority_open_alert_groups: int = 0
    severity_open_alert_groups: int = 0
    worst_severity: str | None = None
    worst_priority_slug: str | None = None
    worst_priority_order: int | None = None
    impact_score: int = 0
    impact_source: str | None = None


@dataclass
class ImpactComputation:
    service_id: int
    own_status: str = "operational"
    alert_impact_status: str = "operational"
    dependency_impact_status: str = "operational"
    effective_status: str = "operational"
    own_impact_score: int = 0
    alert_impact_score: int = 0
    dependency_impact_score: int = 0
    effective_impact_score: int = 0
    primary_reason: str = "none"
    open_alert_groups: int = 0
    critical_open_alert_groups: int = 0
    upstream_issues_count: int = 0
    root_causes: list[dict[str, Any]] = field(default_factory=list)
    paths: list[list[dict[str, Any]]] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    cycle_detected: bool = False
    depth_limited: bool = False


def build_service_impact_v2(query, *, team_ids=None):
    """Build Service Impact v2 payload.

    The builder is intentionally read-only. It does not persist snapshots.
    """

    max_depth = int(getattr(query, "max_depth", 5) or 5)
    limit = int(getattr(query, "limit", 100) or 100)

    include_disabled = bool(getattr(query, "include_disabled", False))
    include_operational = bool(getattr(query, "include_operational", True))
    include_explanation = bool(getattr(query, "include_explanation", True))
    include_root_causes = bool(getattr(query, "include_root_causes", True))
    include_blast_radius = bool(getattr(query, "include_blast_radius", True))
    include_paths = bool(getattr(query, "include_paths", True))

    requested_team_id = getattr(query, "team_id", None)
    requested_service_id = getattr(query, "service_id", None)

    services = _load_services(
        team_ids=team_ids,
        requested_team_id=requested_team_id,
    )

    if not services:
        return _empty_payload(query)

    dependencies = _load_dependencies(services.keys())
    alert_stats = _load_alert_stats(services.keys())

    upstream_by_service, downstream_by_service = _build_dependency_maps(
        services,
        dependencies,
    )

    context = {
        "services": services,
        "alert_stats": alert_stats,
        "upstream_by_service": upstream_by_service,
        "downstream_by_service": downstream_by_service,
        "max_depth": max_depth,
        "include_paths": include_paths,
        "computed": {},
    }

    return_service_ids = _select_return_service_ids(
        services,
        requested_service_id=requested_service_id,
        include_disabled=include_disabled,
    )

    items = []

    for service_id in return_service_ids:
        computation = _compute_service_impact(
            service_id,
            context,
            path=[],
            depth=max_depth,
        )
        item = _impact_item_from_computation(
            computation,
            context,
            include_explanation=include_explanation,
            include_root_causes=include_root_causes,
            include_blast_radius=include_blast_radius,
            include_paths=include_paths,
        )

        if not include_operational and item["effective_status"] == "operational":
            continue

        items.append(item)

    items = _sort_items(
        items,
        sort=getattr(query, "sort", "effective_status"),
        order=getattr(query, "order", "desc"),
    )

    items = items[:limit]

    return {
        "version": 2,
        "items": items,
        "summary": _summary(items),
        "filters": {
            "team_id": requested_team_id,
            "service_id": requested_service_id,
            "include_disabled": include_disabled,
            "include_operational": include_operational,
            "include_explanation": include_explanation,
            "include_root_causes": include_root_causes,
            "include_blast_radius": include_blast_radius,
            "include_paths": include_paths,
            "max_depth": max_depth,
            "limit": limit,
            "sort": getattr(query, "sort", "effective_status"),
            "order": getattr(query, "order", "desc"),
        },
    }


def build_single_service_impact_v2(service_id, query, *, team_ids=None):
    """Build Service Impact v2 payload for one service.

    Single-service impact must calculate the full readable dependency graph first.
    The requested service id is only the returned item filter, not a graph filter.
    """

    max_depth = int(getattr(query, "max_depth", 5) or 5)

    include_disabled = bool(getattr(query, "include_disabled", False))
    include_explanation = bool(getattr(query, "include_explanation", True))
    include_root_causes = bool(getattr(query, "include_root_causes", True))
    include_blast_radius = bool(getattr(query, "include_blast_radius", True))
    include_paths = bool(getattr(query, "include_paths", True))

    services = _load_services(
        team_ids=team_ids,
        requested_team_id=None,
    )

    service = services.get(service_id)

    if not service:
        return None

    if not include_disabled and not service.enabled:
        return None

    dependencies = _load_dependencies(services.keys())
    alert_stats = _load_alert_stats(services.keys())

    upstream_by_service, downstream_by_service = _build_dependency_maps(
        services,
        dependencies,
    )

    context = {
        "services": services,
        "alert_stats": alert_stats,
        "upstream_by_service": upstream_by_service,
        "downstream_by_service": downstream_by_service,
        "max_depth": max_depth,
        "include_paths": include_paths,
        "computed": {},
    }

    computation = _compute_service_impact(
        service_id,
        context,
        path=[],
        depth=max_depth,
    )

    return _impact_item_from_computation(
        computation,
        context,
        include_explanation=include_explanation,
        include_root_causes=include_root_causes,
        include_blast_radius=include_blast_radius,
        include_paths=include_paths,
    )


def build_service_effective_impact_map(service_ids, *, max_depth=5):
    """Return Service Impact v2 items keyed by service id.

    This helper is intended for other backend features such as Business Services.
    It uses the same effective status logic as the Service Impact v2 API.
    """
    service_ids = {
        int(service_id)
        for service_id in (service_ids or [])
        if service_id
    }

    if not service_ids:
        return {}

    services = _load_services_for_effective_impact(service_ids)

    if not services:
        return {}

    dependencies = _load_dependencies(services.keys())
    alert_stats = _load_alert_stats(services.keys())

    upstream_by_service, downstream_by_service = _build_dependency_maps(
        services,
        dependencies,
    )

    context = {
        "services": services,
        "alert_stats": alert_stats,
        "upstream_by_service": upstream_by_service,
        "downstream_by_service": downstream_by_service,
        "max_depth": int(max_depth or 5),
        "include_paths": True,
        "computed": {},
    }

    result = {}

    for service_id in service_ids:
        if service_id not in services:
            continue

        computation = _compute_service_impact(
            service_id,
            context,
            path=[],
            depth=int(max_depth or 5),
        )

        result[service_id] = _impact_item_from_computation(
            computation,
            context,
            include_explanation=True,
            include_root_causes=True,
            include_blast_radius=False,
            include_paths=True,
        )

    return result


def _load_services_for_effective_impact(service_ids):
    """Load enough services to calculate dependencies for requested services.

    Business Services are group-scoped, so we calculate impact against all
    services in the same groups as the requested component services.
    """
    requested_services = list(
        Service
        .select()
        .where(
            (Service.id.in_(service_ids))
            & (Service.deleted == False)  # noqa: E712
        )
    )

    if not requested_services:
        return {}

    group_ids = {
        service.team.group_id
        for service in requested_services
        if service.team_id and service.team and service.team.group_id
    }

    if not group_ids:
        return {service.id: service for service in requested_services}

    query = (
        Service
        .select()
        .join(Team)
        .where(
            (Service.deleted == False)  # noqa: E712
            & (Team.group.in_(group_ids))
        )
    )

    return {service.id: service for service in query}


def _empty_payload(query):
    return {
        "version": 2,
        "items": [],
        "summary": {
            "total": 0,
            "affected": 0,
            "critical": 0,
            "by_effective_status": {},
            "cycle_detected": 0,
            "depth_limited": 0,
        },
        "filters": {
            "team_id": getattr(query, "team_id", None),
            "service_id": getattr(query, "service_id", None),
            "include_disabled": getattr(query, "include_disabled", False),
            "include_operational": getattr(query, "include_operational", True),
            "max_depth": getattr(query, "max_depth", 5),
            "limit": getattr(query, "limit", 100),
            "sort": getattr(query, "sort", "effective_status"),
            "order": getattr(query, "order", "desc"),
        },
    }


def _load_services(*, team_ids=None, requested_team_id=None):
    query = Service.select().where(Service.deleted == False)  # noqa: E712

    if team_ids is not None:
        team_ids = list(team_ids)
        if not team_ids:
            return {}
        query = query.where(Service.team.in_(team_ids))

    if requested_team_id:
        query = query.where(Service.team == requested_team_id)

    return {service.id: service for service in query}


def _load_dependencies(service_ids):
    service_ids = list(service_ids)

    if not service_ids:
        return []

    return list(
        ServiceDependency
        .select()
        .where(
            (ServiceDependency.deleted == False)  # noqa: E712
            & (ServiceDependency.enabled == True)  # noqa: E712
            & (ServiceDependency.service.in_(service_ids))
        )
        .order_by(
            ServiceDependency.service.asc(),
            ServiceDependency.criticality.asc(),
            ServiceDependency.id.asc(),
        )
    )


def _load_alert_stats(service_ids):
    service_ids = list(service_ids)
    stats = defaultdict(AlertImpactStats)

    if not service_ids:
        return stats

    query = (
        AlertGroup
        .select()
        .where(
            (AlertGroup.service.in_(service_ids))
            & (AlertGroup.status.in_(OPEN_ALERT_GROUP_STATUSES))
            & (AlertGroup.merged_into.is_null(True))
        )
    )

    for group in query:
        service_id = group.service_id

        if not service_id:
            continue

        severity = _normalize_severity(group.severity)
        score, source = alert_group_impact_score(group)
        priority_slug = priority_slug_for_alert_group(group)
        priority_order = getattr(group, "priority_order", None)
        item = stats[service_id]

        item.open_alert_groups += 1

        if source == "priority":
            item.priority_open_alert_groups += 1
        else:
            item.severity_open_alert_groups += 1

        if score >= 80:
            item.critical_open_alert_groups += 1
        elif score >= 55:
            item.high_open_alert_groups += 1
        elif score >= 25:
            item.warning_open_alert_groups += 1

        item.worst_severity = _max_severity(item.worst_severity, severity)

        if score > item.impact_score:
            item.impact_score = score
            item.impact_source = source
            item.worst_priority_slug = priority_slug
            try:
                item.worst_priority_order = int(priority_order) if priority_order is not None else None
            except (TypeError, ValueError):
                item.worst_priority_order = None

    return stats

def _build_dependency_maps(services, dependencies):
    upstream_by_service = defaultdict(list)
    downstream_by_service = defaultdict(list)

    for dependency in dependencies:
        source_id = dependency.service_id
        target_id = dependency.depends_on_service_id

        if source_id not in services:
            continue

        if target_id not in services:
            continue

        upstream_by_service[source_id].append(dependency)
        downstream_by_service[target_id].append(dependency)

    return upstream_by_service, downstream_by_service


def _select_return_service_ids(
    services,
    *,
    requested_service_id=None,
    include_disabled=False,
):
    if requested_service_id:
        service = services.get(requested_service_id)

        if not service:
            return []

        if not include_disabled and not service.enabled:
            return []

        return [requested_service_id]

    service_ids = []

    for service in services.values():
        if not include_disabled and not service.enabled:
            continue

        service_ids.append(service.id)

    return service_ids


def _compute_service_impact(service_id, context, *, path, depth):
    computed = context["computed"]
    services = context["services"]

    if service_id in path:
        return ImpactComputation(
            service_id=service_id,
            own_status="unknown",
            effective_status="unknown",
            own_impact_score=status_impact_score("unknown"),
            effective_impact_score=status_impact_score("unknown"),
            primary_reason="unknown",
            cycle_detected=True,
            paths=[_path_for_ids(path + [service_id], context)],
            rules=["Dependency cycle detected."],
        )

    cache_key = (
        service_id,
        depth,
        tuple(path),
    )

    if cache_key in computed:
        return computed[cache_key]

    service = services.get(service_id)

    if not service:
        return ImpactComputation(
            service_id=service_id,
            own_status="unknown",
            effective_status="unknown",
            own_impact_score=status_impact_score("unknown"),
            effective_impact_score=status_impact_score("unknown"),
            primary_reason="unknown",
        )

    own_status = _own_status(service)
    own_score = _own_impact_score(own_status)
    alert_stats = context["alert_stats"][service_id]
    alert_score = clamp_impact_score(alert_stats.impact_score)
    alert_status = _alert_impact_status(alert_stats)

    if not service.enabled:
        result = ImpactComputation(
            service_id=service_id,
            own_status="disabled",
            alert_impact_status="operational",
            dependency_impact_status="operational",
            effective_status="disabled",
            own_impact_score=0,
            alert_impact_score=0,
            dependency_impact_score=0,
            effective_impact_score=0,
            primary_reason="disabled",
            open_alert_groups=0,
            critical_open_alert_groups=0,
            root_causes=[
                _root_cause(
                    service,
                    reason="disabled",
                    status="disabled",
                    impact_score=0,
                    alert_stats=AlertImpactStats(),
                    path=[_path_node(service, effective_status="disabled", impact_score=0)],
                )
            ],
            paths=[[_path_node(service, effective_status="disabled", impact_score=0)]],
            rules=[f"{service.name} is disabled."],
        )

        computed[cache_key] = result
        return result

    base_reason = _primary_base_reason(
        service,
        own_status,
        own_score,
        alert_status,
        alert_score,
    )
    base_score = max(own_score, alert_score)
    base_status = _status_for_reason(
        base_reason,
        own_status=own_status,
        alert_status=alert_status,
        dependency_status="operational",
        score=base_score,
    )

    result = ImpactComputation(
        service_id=service_id,
        own_status=own_status,
        alert_impact_status=alert_status,
        dependency_impact_status="operational",
        effective_status=base_status,
        own_impact_score=own_score,
        alert_impact_score=alert_score,
        dependency_impact_score=0,
        effective_impact_score=base_score,
        primary_reason=base_reason,
        open_alert_groups=alert_stats.open_alert_groups,
        critical_open_alert_groups=alert_stats.critical_open_alert_groups,
    )

    if _is_root_cause_status(result.effective_status) and result.primary_reason != "upstream_dependency":
        result.root_causes.append(
            _root_cause(
                service,
                reason=result.primary_reason,
                status=result.effective_status,
                impact_score=result.effective_impact_score,
                alert_stats=alert_stats,
                path=[_path_node(service, effective_status=result.effective_status, impact_score=result.effective_impact_score)],
            )
        )

        result.paths.append([
            _path_node(service, effective_status=result.effective_status, impact_score=result.effective_impact_score)
        ])
        result.rules.extend(_base_rules(service, result.primary_reason, alert_stats, result.effective_impact_score))

    if depth <= 0:
        result.depth_limited = True
        result.rules.append("Dependency traversal depth limit reached.")
        computed[cache_key] = result
        return result

    dependency_status = "operational"
    dependency_score = 0
    dependency_root_causes = []
    dependency_paths = []
    upstream_issues_count = 0
    cycle_detected = False
    depth_limited = False

    for dependency in context["upstream_by_service"].get(service_id, []):
        upstream_id = dependency.depends_on_service_id

        if upstream_id in path:
            cycle_detected = True
            cycle_path = _dependency_cycle_path(
                service,
                dependency,
                upstream_id,
                context,
                path,
            )
            dependency_paths.append(cycle_path)
            continue

        upstream = _compute_service_impact(
            upstream_id,
            context,
            path=path + [service_id],
            depth=depth - 1,
        )

        propagated = _propagate_dependency_impact(dependency, upstream)
        propagated_status = propagated["status"]
        propagated_score = propagated["score"]

        if _is_impactful_status(propagated_status) or propagated_score > 0:
            upstream_issues_count += 1

            if propagated_score > dependency_score:
                dependency_score = propagated_score
                dependency_status = propagated_status
            elif propagated_score == dependency_score:
                dependency_status = _max_status(dependency_status, propagated_status)

            if upstream.root_causes:
                for cause in upstream.root_causes:
                    dependency_root_causes.append(
                        _root_cause_with_prefixed_path(
                            cause,
                            service,
                            dependency,
                            propagated=propagated,
                        )
                    )
            else:
                upstream_service = context["services"].get(upstream_id)
                if upstream_service:
                    dependency_root_causes.append(
                        _root_cause(
                            upstream_service,
                            reason=upstream.primary_reason,
                            status=upstream.effective_status,
                            impact_score=upstream.effective_impact_score,
                            alert_stats=context["alert_stats"][upstream_id],
                            path=[
                                _path_node(service, effective_status=result.effective_status, impact_score=result.effective_impact_score),
                                _path_node(
                                    upstream_service,
                                    dependency,
                                    effective_status=upstream.effective_status,
                                    impact_score=upstream.effective_impact_score,
                                    propagated_impact_score=propagated_score,
                                    dependency_multiplier=propagated["multiplier"],
                                ),
                            ],
                        )
                    )

            for upstream_path in upstream.paths:
                dependency_paths.append(
                    _prefix_path(
                        service,
                        dependency,
                        upstream_path,
                        service_effective_status=result.effective_status,
                        service_impact_score=result.effective_impact_score,
                        dependency_multiplier=propagated["multiplier"],
                        propagated_impact_score=propagated_score,
                    )
                )

            if not upstream.paths:
                upstream_service = context["services"].get(upstream_id)
                if upstream_service:
                    dependency_paths.append([
                        _path_node(service, effective_status=result.effective_status, impact_score=result.effective_impact_score),
                        _path_node(
                            upstream_service,
                            dependency,
                            effective_status=upstream.effective_status,
                            impact_score=upstream.effective_impact_score,
                            propagated_impact_score=propagated_score,
                            dependency_multiplier=propagated["multiplier"],
                        ),
                    ])

        cycle_detected = cycle_detected or upstream.cycle_detected
        depth_limited = depth_limited or upstream.depth_limited

    result.dependency_impact_status = dependency_status
    result.dependency_impact_score = clamp_impact_score(dependency_score)
    result.effective_impact_score = max(
        result.own_impact_score,
        result.alert_impact_score,
        result.dependency_impact_score,
    )
    result.upstream_issues_count = upstream_issues_count
    result.cycle_detected = result.cycle_detected or cycle_detected
    result.depth_limited = result.depth_limited or depth_limited
    result.primary_reason = _primary_reason_from_scores(result)
    result.effective_status = _status_for_reason(
        result.primary_reason,
        own_status=result.own_status,
        alert_status=result.alert_impact_status,
        dependency_status=result.dependency_impact_status,
        score=result.effective_impact_score,
    )

    if result.primary_reason == "upstream_dependency":
        result.root_causes = _deduplicate_root_causes(dependency_root_causes)
        result.paths = _deduplicate_paths(dependency_paths)
        result.rules.append(
            (
                f"{service.name} is impacted by {upstream_issues_count} upstream dependency issue(s); "
                f"dependency impact score={result.dependency_impact_score}."
            )
        )

    computed[cache_key] = result
    return result

def _own_status(service):
    if not service.enabled:
        return "disabled"

    status = _normalize_status(service.status)

    if status == "disabled" and service.enabled:
        return "unknown"

    return status


def _own_impact_score(own_status):
    return status_impact_score(own_status)


def _alert_impact_status(stats):
    if not stats or clamp_impact_score(stats.impact_score) <= 0:
        return "operational"

    return status_from_impact_score(stats.impact_score)


def _primary_base_reason(service, own_status, own_score, alert_status, alert_score):
    if not service.enabled:
        return "disabled"

    own_score = clamp_impact_score(own_score)
    alert_score = clamp_impact_score(alert_score)

    if own_status == "maintenance" and own_score >= alert_score:
        return "maintenance"

    if _is_impactful_status(own_status) and own_score >= alert_score:
        return "own_status"

    if alert_score > 0 or _is_impactful_status(alert_status):
        return "alert_group"

    if own_status == "unknown" and own_score > 0:
        return "own_status"

    return "none"


def _primary_reason_from_scores(computation):
    dependency_score = clamp_impact_score(computation.dependency_impact_score)
    own_score = clamp_impact_score(computation.own_impact_score)
    alert_score = clamp_impact_score(computation.alert_impact_score)

    if dependency_score > 0 and dependency_score >= own_score and dependency_score >= alert_score:
        return "upstream_dependency"

    if computation.own_status == "maintenance" and own_score >= alert_score:
        return "maintenance"

    if _is_impactful_status(computation.own_status) and own_score >= alert_score:
        return "own_status"

    if alert_score > 0 or _is_impactful_status(computation.alert_impact_status):
        return "alert_group"

    if computation.own_status == "unknown" and own_score > 0:
        return "own_status"

    return "none"


def _status_for_reason(reason, *, own_status, alert_status, dependency_status, score):
    score = clamp_impact_score(score)

    if reason == "disabled":
        return "disabled"

    if reason == "maintenance":
        return "maintenance"

    if reason == "own_status":
        own_status = _normalize_status(own_status)
        if own_status in {"unknown", "degraded", "partial_outage", "major_outage"}:
            return own_status
        return status_from_impact_score(score)

    if reason == "upstream_dependency":
        dependency_status = _normalize_status(dependency_status)
        if dependency_status in {"unknown", "degraded", "partial_outage", "major_outage"}:
            return dependency_status
        return status_from_impact_score(score)

    if reason == "alert_group":
        alert_status = _normalize_status(alert_status)
        if alert_status in {"degraded", "partial_outage", "major_outage"}:
            return alert_status
        return status_from_impact_score(score)

    return "operational"


def _base_rules(service, reason, stats, impact_score=0):
    impact_score = clamp_impact_score(impact_score)

    if reason == "disabled":
        return [f"{service.name} is disabled."]

    if reason == "maintenance":
        return [f"{service.name} is in maintenance status; impact score={impact_score}."]

    if reason == "own_status":
        return [f"{service.name} own status is {service.status}; impact score={impact_score}."]

    if reason == "alert_group":
        source = stats.impact_source or "severity"
        priority_part = (
            f", worst priority={stats.worst_priority_slug.upper()}"
            if stats.worst_priority_slug
            else ""
        )
        return [
            (
                f"{service.name} has {stats.open_alert_groups} open alert group(s), "
                f"{stats.critical_open_alert_groups} critical-impact; "
                f"alert impact score={impact_score} from {source}{priority_part}."
            )
        ]

    return []


def _propagate_dependency_impact(dependency, upstream):
    return propagate_dependency_impact(
        dependency,
        upstream.effective_status,
        upstream.effective_impact_score,
    )

def _impact_item_from_computation(
    computation,
    context,
    *,
    include_explanation,
    include_root_causes,
    include_blast_radius,
    include_paths,
):
    service = context["services"][computation.service_id]

    item = {
        "service_id": service.id,
        "service_slug": service.slug,
        "service_name": service.name,
        "team_id": service.team_id,
        "team_slug": service.team.slug if service.team_id and service.team else None,
        "team_name": service.team.name if service.team_id and service.team else None,
        "criticality": service.criticality,
        "tier": service.tier,
        "own_status": computation.own_status,
        "alert_impact_status": computation.alert_impact_status,
        "dependency_impact_status": computation.dependency_impact_status,
        "effective_status": computation.effective_status,
        "own_impact_score": computation.own_impact_score,
        "alert_impact_score": computation.alert_impact_score,
        "dependency_impact_score": computation.dependency_impact_score,
        "effective_impact_score": computation.effective_impact_score,
        "impact_score": computation.effective_impact_score,
        "primary_reason": computation.primary_reason,
        "open_alert_groups": computation.open_alert_groups,
        "critical_open_alert_groups": computation.critical_open_alert_groups,
        "upstream_issues_count": computation.upstream_issues_count,
        "root_causes": computation.root_causes if include_root_causes else [],
        "explanation": (
            _explanation(service, computation, include_paths=include_paths)
            if include_explanation
            else None
        ),
        "blast_radius": (
            _blast_radius(service.id, context, include_paths=include_paths)
            if include_blast_radius
            else None
        ),
        "cycle_detected": computation.cycle_detected,
        "depth_limited": computation.depth_limited,
    }

    return item


def _explanation(service, computation, *, include_paths):
    primary_root = computation.root_causes[0] if computation.root_causes else None

    if computation.primary_reason == "none":
        title = f"{service.name} is operational"
        message = "No open alert groups, own status impact or upstream dependency impact was detected."
    elif computation.primary_reason == "alert_group":
        title = f"{service.name} is impacted by open alert groups"
        message = (
            f"{service.name} has {computation.open_alert_groups} open alert group(s), "
            f"{computation.critical_open_alert_groups} critical-impact, "
            f"alert impact score {computation.alert_impact_score}."
        )
    elif computation.primary_reason == "upstream_dependency":
        source_name = primary_root["service_name"] if primary_root else "an upstream dependency"
        title = f"{service.name} is impacted by {source_name}"
        message = (
            f"The effective status is {computation.effective_status} because an upstream dependency is unhealthy; "
            f"dependency impact score {computation.dependency_impact_score}."
        )
    elif computation.primary_reason == "maintenance":
        title = f"{service.name} is in maintenance"
        message = "The service own status is maintenance."
    elif computation.primary_reason == "disabled":
        title = f"{service.name} is disabled"
        message = "The service is disabled and excluded from default impact views."
    elif computation.primary_reason == "own_status":
        title = f"{service.name} own status is {computation.own_status}"
        message = "The service manually or systematically reports an unhealthy own status."
    else:
        title = f"{service.name} impact is unknown"
        message = "Impact reason could not be fully determined."

    return {
        "primary_reason": computation.primary_reason,
        "primary_source_service_id": primary_root["service_id"] if primary_root else None,
        "primary_source_service_slug": primary_root["service_slug"] if primary_root else None,
        "primary_source_service_name": primary_root["service_name"] if primary_root else None,
        "title": title,
        "message": message,
        "own_impact_score": computation.own_impact_score,
        "alert_impact_score": computation.alert_impact_score,
        "dependency_impact_score": computation.dependency_impact_score,
        "effective_impact_score": computation.effective_impact_score,
        "rules": computation.rules,
        "paths": computation.paths if include_paths else [],
    }


def _blast_radius(service_id, context, *, include_paths):
    max_depth = context["max_depth"]
    downstream_by_service = context["downstream_by_service"]

    direct_dependencies = downstream_by_service.get(service_id, [])
    direct_downstream_ids = {
        dependency.service_id
        for dependency in direct_dependencies
        if dependency.service_id in context["services"]
    }

    visited = set()
    paths = []
    cycle_detected = False
    depth_limited = False

    def visit(current_service_id, path, depth):
        nonlocal cycle_detected, depth_limited

        if depth <= 0:
            depth_limited = True
            return

        for dependency in downstream_by_service.get(current_service_id, []):
            downstream_id = dependency.service_id

            if downstream_id not in context["services"]:
                continue

            if downstream_id in path:
                cycle_detected = True
                if include_paths:
                    paths.append(
                        _downstream_cycle_path(
                            path,
                            downstream_id,
                            dependency,
                            context,
                        )
                    )
                continue

            visited.add(downstream_id)

            if include_paths:
                paths.append(
                    _downstream_path(
                        path,
                        downstream_id,
                        dependency,
                        context,
                    )
                )

            visit(
                downstream_id,
                path + [downstream_id],
                depth - 1,
            )

    visit(service_id, [service_id], max_depth)

    critical_downstream = 0
    tier_1_downstream = 0

    for downstream_id in visited:
        downstream = context["services"].get(downstream_id)

        if not downstream:
            continue

        if downstream.criticality in {"high", "critical"}:
            critical_downstream += 1

        if downstream.tier == "tier_1":
            tier_1_downstream += 1

    return {
        "direct_downstream": len(direct_downstream_ids),
        "transitive_downstream": len(visited),
        "critical_downstream": critical_downstream,
        "tier_1_downstream": tier_1_downstream,
        "affected_downstream": len(visited),
        "paths": paths if include_paths else [],
        "cycle_detected": cycle_detected,
        "depth_limited": depth_limited,
    }


def _root_cause(service, *, reason, status, impact_score, alert_stats, path):
    return {
        "service_id": service.id,
        "service_slug": service.slug,
        "service_name": service.name,
        "reason": reason or "unknown",
        "status": _normalize_status(service.status),
        "effective_status": _normalize_status(status),
        "impact_score": clamp_impact_score(impact_score),
        "severity": alert_stats.worst_severity,
        "priority_slug": alert_stats.worst_priority_slug,
        "priority_order": alert_stats.worst_priority_order,
        "open_alert_groups": alert_stats.open_alert_groups,
        "critical_open_alert_groups": alert_stats.critical_open_alert_groups,
        "path": path,
    }


def _root_cause_with_prefixed_path(cause, service, dependency, propagated=None):
    prefixed = dict(cause)
    prefixed["path"] = _prefix_path(
        service,
        dependency,
        cause.get("path") or [],
        dependency_multiplier=(propagated or {}).get("multiplier"),
        propagated_impact_score=(propagated or {}).get("score"),
    )
    return prefixed


def _path_node(
    service,
    dependency=None,
    *,
    effective_status=None,
    impact_score=None,
    propagated_impact_score=None,
    dependency_multiplier=None,
):
    return {
        "service_id": service.id,
        "service_slug": service.slug,
        "service_name": service.name,
        "status": _normalize_status(service.status),
        "effective_status": _normalize_status(effective_status or service.status),
        "impact_score": clamp_impact_score(
            status_impact_score(effective_status or service.status)
            if impact_score is None
            else impact_score
        ),
        "propagated_impact_score": (
            clamp_impact_score(propagated_impact_score)
            if propagated_impact_score is not None
            else None
        ),
        "dependency_multiplier": dependency_multiplier,
        "dependency_type": dependency.dependency_type if dependency else None,
        "dependency_criticality": dependency.criticality if dependency else None,
    }


def _prefix_path(
    service,
    dependency,
    upstream_path,
    *,
    service_effective_status=None,
    service_impact_score=None,
    dependency_multiplier=None,
    propagated_impact_score=None,
):
    path = [
        _path_node(
            service,
            effective_status=service_effective_status,
            impact_score=service_impact_score,
        )
    ]

    if not upstream_path:
        depends_on = dependency.depends_on_service
        return path + [
            _path_node(
                depends_on,
                dependency,
                dependency_multiplier=dependency_multiplier,
                propagated_impact_score=propagated_impact_score,
            )
        ]

    for index, node in enumerate(upstream_path):
        node = dict(node)

        if index == 0:
            node["dependency_type"] = dependency.dependency_type
            node["dependency_criticality"] = dependency.criticality
            node["dependency_multiplier"] = dependency_multiplier
            node["propagated_impact_score"] = (
                clamp_impact_score(propagated_impact_score)
                if propagated_impact_score is not None
                else node.get("propagated_impact_score")
            )

        path.append(node)

    return path


def _path_for_ids(service_ids, context):
    path = []

    for service_id in service_ids:
        service = context["services"].get(service_id)

        if service:
            path.append(_path_node(service))

    return path


def _dependency_cycle_path(service, dependency, upstream_id, context, path):
    ids = path + [service.id, upstream_id]
    return _path_for_ids(ids, context)


def _downstream_path(path_ids, downstream_id, dependency, context):
    nodes = _path_for_ids(path_ids, context)
    downstream = context["services"].get(downstream_id)

    if downstream:
        nodes.append(_path_node(downstream, dependency))

    return nodes


def _downstream_cycle_path(path_ids, downstream_id, dependency, context):
    return _downstream_path(path_ids, downstream_id, dependency, context)

def _deduplicate_root_causes(root_causes):
    seen = set()
    result = []

    for cause in root_causes:
        key = (
            cause.get("service_id"),
            cause.get("reason"),
            cause.get("effective_status"),
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(cause)

    result.sort(
        key=lambda item: (
            -_status_rank(item.get("effective_status")),
            item.get("service_name") or "",
        )
    )

    return result


def _deduplicate_paths(paths):
    seen = set()
    result = []

    for path in paths:
        key = tuple(node.get("service_id") for node in path)

        if key in seen:
            continue

        seen.add(key)
        result.append(path)

    return result


def _summary(items):
    by_status = Counter(item["effective_status"] for item in items)

    return {
        "total": len(items),
        "affected": sum(
            1
            for item in items
            if item["effective_status"] not in {"operational", "disabled"}
        ),
        "critical": sum(
            1
            for item in items
            if item["effective_status"] == "major_outage"
        ),
        "by_effective_status": dict(by_status),
        "max_impact_score": max((item.get("effective_impact_score") or 0) for item in items) if items else 0,
        "average_impact_score": (
            int(round(sum((item.get("effective_impact_score") or 0) for item in items) / len(items)))
            if items
            else 0
        ),
        "cycle_detected": sum(1 for item in items if item.get("cycle_detected")),
        "depth_limited": sum(1 for item in items if item.get("depth_limited")),
    }


def _sort_items(items, *, sort, order):
    reverse = order != "asc"

    return sorted(
        items,
        key=lambda item: _sort_value(item, sort),
        reverse=reverse,
    )


def _sort_value(item, sort):
    if sort == "service":
        return (item.get("service_name") or item.get("service_slug") or "").lower()

    if sort == "status":
        return _status_rank(item.get("own_status"))

    if sort in {"effective_status", "impact_score"}:
        return (
            item.get("effective_impact_score") or item.get("impact_score") or 0,
            _status_rank(item.get("effective_status")),
        )

    if sort == "blast_radius":
        blast_radius = item.get("blast_radius") or {}
        return blast_radius.get("transitive_downstream") or 0

    if sort == "criticality":
        return CRITICALITY_RANK.get(item.get("criticality"), 0)

    if sort == "tier":
        return TIER_RANK.get(item.get("tier"), 0)

    return (
        item.get("effective_impact_score") or item.get("impact_score") or 0,
        _status_rank(item.get("effective_status")),
    )


def _normalize_status(status):
    return normalize_status(status)


def _normalize_severity(severity):
    return normalize_severity(severity)


def _max_status(*statuses):
    return max_status(*statuses)


def _status_rank(status):
    return status_rank(status)


def _max_severity(left, right):
    return max_severity(left, right)


def _is_impactful_status(status):
    return _normalize_status(status) in {
        "degraded",
        "partial_outage",
        "major_outage",
        "unknown",
    }


def _is_root_cause_status(status):
    return _normalize_status(status) in {
        "degraded",
        "partial_outage",
        "major_outage",
        "maintenance",
        "disabled",
        "unknown",
    }
