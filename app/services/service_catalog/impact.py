from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.modules.db.models import AlertGroup, Service, ServiceDependency


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
    worst_severity: str | None = None


@dataclass
class ImpactComputation:
    service_id: int
    own_status: str = "operational"
    alert_impact_status: str = "operational"
    dependency_impact_status: str = "operational"
    effective_status: str = "operational"
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
        item = stats[service_id]

        item.open_alert_groups += 1

        if severity == "critical":
            item.critical_open_alert_groups += 1
        elif severity == "high":
            item.high_open_alert_groups += 1
        elif severity in {"warning", "warn"}:
            item.warning_open_alert_groups += 1

        item.worst_severity = _max_severity(item.worst_severity, severity)

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
            primary_reason="unknown",
        )

    own_status = _own_status(service)
    alert_stats = context["alert_stats"][service_id]
    alert_status = _alert_impact_status(alert_stats)

    if not service.enabled:
        result = ImpactComputation(
            service_id=service_id,
            own_status="disabled",
            alert_impact_status="operational",
            dependency_impact_status="operational",
            effective_status="disabled",
            primary_reason="disabled",
            open_alert_groups=0,
            critical_open_alert_groups=0,
            root_causes=[
                _root_cause(
                    service,
                    reason="disabled",
                    status="disabled",
                    alert_stats=AlertImpactStats(),
                    path=[_path_node(service)],
                )
            ],
            paths=[[_path_node(service)]],
            rules=[f"{service.name} is disabled."],
        )

        computed[cache_key] = result
        return result

    result = ImpactComputation(
        service_id=service_id,
        own_status=own_status,
        alert_impact_status=alert_status,
        dependency_impact_status="operational",
        effective_status=_max_status(own_status, alert_status),
        primary_reason=_primary_base_reason(service, own_status, alert_status),
        open_alert_groups=alert_stats.open_alert_groups,
        critical_open_alert_groups=alert_stats.critical_open_alert_groups,
    )

    if _is_root_cause_status(result.effective_status) and result.primary_reason != "upstream_dependency":
        result.root_causes.append(
            _root_cause(
                service,
                reason=result.primary_reason,
                status=result.effective_status,
                alert_stats=alert_stats,
                path=[_path_node(service)],
            )
        )

        result.paths.append([_path_node(service)])
        result.rules.extend(_base_rules(service, result.primary_reason, alert_stats))

    if depth <= 0:
        result.depth_limited = True
        result.rules.append("Dependency traversal depth limit reached.")
        computed[cache_key] = result
        return result

    dependency_status = "operational"
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

        propagated_status = _propagate_dependency_status(
            dependency,
            upstream.effective_status,
        )

        if _is_impactful_status(propagated_status):
            upstream_issues_count += 1
            dependency_status = _max_status(dependency_status, propagated_status)

            if upstream.root_causes:
                for cause in upstream.root_causes:
                    dependency_root_causes.append(
                        _root_cause_with_prefixed_path(
                            cause,
                            service,
                            dependency,
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
                            alert_stats=context["alert_stats"][upstream_id],
                            path=[
                                _path_node(service),
                                _path_node(upstream_service, dependency),
                            ],
                        )
                    )

            for upstream_path in upstream.paths:
                dependency_paths.append(
                    _prefix_path(service, dependency, upstream_path)
                )

            if not upstream.paths:
                upstream_service = context["services"].get(upstream_id)
                if upstream_service:
                    dependency_paths.append([
                        _path_node(service),
                        _path_node(upstream_service, dependency),
                    ])

        cycle_detected = cycle_detected or upstream.cycle_detected
        depth_limited = depth_limited or upstream.depth_limited

    result.dependency_impact_status = dependency_status
    result.effective_status = _max_status(
        result.own_status,
        result.alert_impact_status,
        result.dependency_impact_status,
    )
    result.upstream_issues_count = upstream_issues_count
    result.cycle_detected = result.cycle_detected or cycle_detected
    result.depth_limited = result.depth_limited or depth_limited

    if (
        _status_rank(result.dependency_impact_status) >= _status_rank(result.own_status)
        and _status_rank(result.dependency_impact_status) >= _status_rank(result.alert_impact_status)
        and _is_impactful_status(result.dependency_impact_status)
    ):
        result.primary_reason = "upstream_dependency"

    if result.primary_reason == "upstream_dependency":
        result.root_causes = _deduplicate_root_causes(dependency_root_causes)
        result.paths = _deduplicate_paths(dependency_paths)
        result.rules.append(
            f"{service.name} is impacted by {upstream_issues_count} upstream dependency issue(s)."
        )

    computed[service_id] = result
    return result


def _own_status(service):
    if not service.enabled:
        return "disabled"

    status = _normalize_status(service.status)

    if status == "disabled" and service.enabled:
        return "unknown"

    return status


def _alert_impact_status(stats):
    if stats.critical_open_alert_groups > 0:
        return "major_outage"

    if stats.high_open_alert_groups > 0:
        return "partial_outage"

    if stats.warning_open_alert_groups > 0:
        return "degraded"

    if stats.open_alert_groups > 0:
        return "degraded"

    return "operational"


def _primary_base_reason(service, own_status, alert_status):
    if not service.enabled:
        return "disabled"

    if own_status == "maintenance":
        return "maintenance"

    if _is_impactful_status(own_status) and _status_rank(own_status) >= _status_rank(alert_status):
        return "own_status"

    if _is_impactful_status(alert_status):
        return "alert_group"

    return "none"


def _base_rules(service, reason, stats):
    if reason == "disabled":
        return [f"{service.name} is disabled."]

    if reason == "maintenance":
        return [f"{service.name} is in maintenance status."]

    if reason == "own_status":
        return [f"{service.name} own status is {service.status}."]

    if reason == "alert_group":
        return [
            (
                f"{service.name} has {stats.open_alert_groups} open alert group(s), "
                f"{stats.critical_open_alert_groups} critical."
            )
        ]

    return []


def _propagate_dependency_status(dependency, upstream_status):
    upstream_status = _normalize_status(upstream_status)

    if upstream_status in {"operational", "maintenance", "disabled"}:
        return "operational"

    if upstream_status == "unknown":
        return "unknown"

    dependency_type = dependency.dependency_type or "hard"
    criticality = dependency.criticality or "important"

    type_rank = DEPENDENCY_TYPE_RANK.get(dependency_type, 1)
    criticality_rank = DEPENDENCY_CRITICALITY_RANK.get(criticality, 2)

    if type_rank <= DEPENDENCY_TYPE_RANK["informational"]:
        return "operational"

    if upstream_status == "major_outage":
        if dependency_type == "hard" or criticality == "required":
            return "major_outage"
        if dependency_type == "soft" or criticality == "important":
            return "partial_outage"
        return "degraded"

    if upstream_status == "partial_outage":
        if dependency_type == "hard" or criticality_rank >= DEPENDENCY_CRITICALITY_RANK["important"]:
            return "partial_outage"
        return "degraded"

    if upstream_status == "degraded":
        if criticality_rank >= DEPENDENCY_CRITICALITY_RANK["important"]:
            return "degraded"
        return "operational"

    return "operational"


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
            f"{computation.critical_open_alert_groups} critical."
        )
    elif computation.primary_reason == "upstream_dependency":
        source_name = primary_root["service_name"] if primary_root else "an upstream dependency"
        title = f"{service.name} is impacted by {source_name}"
        message = f"The effective status is {computation.effective_status} because an upstream dependency is unhealthy."
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


def _root_cause(service, *, reason, status, alert_stats, path):
    return {
        "service_id": service.id,
        "service_slug": service.slug,
        "service_name": service.name,
        "reason": reason or "unknown",
        "status": _normalize_status(service.status),
        "effective_status": _normalize_status(status),
        "severity": alert_stats.worst_severity,
        "open_alert_groups": alert_stats.open_alert_groups,
        "critical_open_alert_groups": alert_stats.critical_open_alert_groups,
        "path": path,
    }


def _root_cause_with_prefixed_path(cause, service, dependency):
    prefixed = dict(cause)
    prefixed["path"] = _prefix_path(service, dependency, cause.get("path") or [])
    return prefixed


def _path_node(service, dependency=None):
    return {
        "service_id": service.id,
        "service_slug": service.slug,
        "service_name": service.name,
        "status": _normalize_status(service.status),
        "effective_status": _normalize_status(service.status),
        "dependency_type": dependency.dependency_type if dependency else None,
        "dependency_criticality": dependency.criticality if dependency else None,
    }


def _prefix_path(service, dependency, upstream_path):
    path = [_path_node(service)]

    if not upstream_path:
        depends_on = dependency.depends_on_service
        return path + [_path_node(depends_on, dependency)]

    for index, node in enumerate(upstream_path):
        node = dict(node)

        if index == 0:
            node["dependency_type"] = dependency.dependency_type
            node["dependency_criticality"] = dependency.criticality

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

    if sort == "effective_status":
        return _status_rank(item.get("effective_status"))

    if sort == "blast_radius":
        blast_radius = item.get("blast_radius") or {}
        return blast_radius.get("transitive_downstream") or 0

    if sort == "criticality":
        return CRITICALITY_RANK.get(item.get("criticality"), 0)

    if sort == "tier":
        return TIER_RANK.get(item.get("tier"), 0)

    return _status_rank(item.get("effective_status"))


def _normalize_status(status):
    status = str(status or "unknown").strip()

    if status not in IMPACT_STATUSES:
        return "unknown"

    return status


def _normalize_severity(severity):
    severity = str(severity or "").strip().lower()

    if not severity:
        return None

    if severity == "warn":
        return "warning"

    return severity


def _max_status(*statuses):
    normalized = [_normalize_status(status) for status in statuses]
    return max(normalized, key=_status_rank)


def _status_rank(status):
    return STATUS_RANK.get(_normalize_status(status), 0)


def _max_severity(left, right):
    left = _normalize_severity(left)
    right = _normalize_severity(right)

    if SEVERITY_RANK.get(right, 0) > SEVERITY_RANK.get(left, 0):
        return right

    return left


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
