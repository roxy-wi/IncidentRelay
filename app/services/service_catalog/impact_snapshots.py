from collections import Counter, defaultdict
from datetime import timedelta
from types import SimpleNamespace

from app.db import database_proxy
from app.modules.db.models import (
    Service,
    ServiceImpactSnapshot,
    ServiceImpactSnapshotItem,
)
from app.services.serializers.services import serialize_utc_datetime
from app.services.service_catalog.impact import build_service_impact_v2
from app.modules.common import utc_now

IMPACTFUL_STATUSES = {"degraded", "partial_outage", "major_outage", "maintenance", "unknown"}
STATUS_RANK = {
    "disabled": -1,
    "operational": 0,
    "unknown": 1,
    "maintenance": 2,
    "degraded": 3,
    "partial_outage": 4,
    "major_outage": 5,
}


class SnapshotImpactQuery:
    """Query object used by scheduler-created impact snapshots."""

    team_id = None
    service_id = None
    include_disabled = True
    include_operational = True
    include_explanation = True
    include_root_causes = True
    include_blast_radius = True
    include_paths = True
    max_depth = 5
    limit = 100000
    sort = "effective_status"
    order = "desc"


def capture_service_impact_snapshot(query=None, *, team_ids=None, source="manual"):
    """Persist a point-in-time Service Impact v2 snapshot and its service rows."""
    query = _normalize_snapshot_query(query)
    payload = build_service_impact_v2(query, team_ids=team_ids)
    items = list(payload.get("items") or [])
    captured_at = utc_now()
    summary = _build_snapshot_summary(items, payload.get("summary") or {})
    scope = _snapshot_scope(query, team_ids=team_ids)

    service_ids = [item.get("service_id") for item in items if item.get("service_id")]
    services = _load_services(service_ids)

    with database_proxy.atomic():
        snapshot = ServiceImpactSnapshot.create(
            group_id=_single_group_id(services),
            team_id=getattr(query, "team_id", None),
            service_id=getattr(query, "service_id", None),
            source=source,
            scope=scope,
            captured_at=captured_at,
            max_depth=int(getattr(query, "max_depth", 5) or 5),
            include_disabled=bool(getattr(query, "include_disabled", False)),
            include_operational=bool(getattr(query, "include_operational", True)),
            services_count=summary["services"],
            affected_services=summary["affected_services"],
            critical_services=summary["critical_services"],
            major_outage_services=summary["major_outage_services"],
            partial_outage_services=summary["partial_outage_services"],
            degraded_services=summary["degraded_services"],
            maintenance_services=summary["maintenance_services"],
            unknown_services=summary["unknown_services"],
            alert_group_impacted_services=summary["alert_group_impacted_services"],
            dependency_impacted_services=summary["dependency_impacted_services"],
            own_status_impacted_services=summary["own_status_impacted_services"],
            open_alert_groups_total=summary["open_alert_groups_total"],
            critical_open_alert_groups_total=summary["critical_open_alert_groups_total"],
            upstream_issues_total=summary["upstream_issues_total"],
            cycle_detected_count=summary["cycle_detected_count"],
            depth_limited_count=summary["depth_limited_count"],
            summary=summary,
            filters=payload.get("filters") or {},
            payload=payload,
        )

        for item in items:
            _create_snapshot_item(snapshot, item, services, captured_at)

    return serialize_service_impact_snapshot(snapshot, include_items=True)


def capture_scheduled_service_impact_snapshot(*, retention_days=None):
    """Capture the global scheduler snapshot and optionally prune old snapshots."""
    snapshot = capture_service_impact_snapshot(
        SnapshotImpactQuery(),
        team_ids=None,
        source="scheduler",
    )

    deleted = 0

    if retention_days:
        deleted = cleanup_service_impact_snapshots(retention_days=retention_days)

    return {
        "snapshot": snapshot,
        "items": len(snapshot.get("items") or []),
        "deleted_old_snapshots": deleted,
    }


def list_service_impact_snapshots(query, *, team_ids=None):
    """Return recent snapshots visible in the requested scope."""
    days = int(getattr(query, "days", 7) or 7)
    limit = int(getattr(query, "limit", 50) or 50)
    since = utc_now() - timedelta(days=days)

    snapshots = _snapshot_query(
        since=since,
        team_ids=team_ids,
        requested_team_id=getattr(query, "team_id", None),
        requested_service_id=getattr(query, "service_id", None),
    ).order_by(ServiceImpactSnapshot.captured_at.desc()).limit(limit)

    return {
        "version": 1,
        "items": [serialize_service_impact_snapshot(snapshot) for snapshot in snapshots],
        "window": {
            "days": days,
            "since": serialize_utc_datetime(since),
            "until": serialize_utc_datetime(utc_now()),
        },
        "filters": {
            "team_id": getattr(query, "team_id", None),
            "service_id": getattr(query, "service_id", None),
            "limit": limit,
        },
    }


def build_service_impact_history(query, *, team_ids=None):
    """Build historical impact analytics from persisted snapshot rows."""
    days = int(getattr(query, "days", 30) or 30)
    limit = int(getattr(query, "limit", 25) or 25)
    bucket = getattr(query, "bucket", "day") or "day"
    since = utc_now() - timedelta(days=days)
    until = utc_now()

    snapshots = list(_snapshot_query(
        since=since,
        team_ids=team_ids,
        requested_team_id=getattr(query, "team_id", None),
        requested_service_id=getattr(query, "service_id", None),
    ).order_by(ServiceImpactSnapshot.captured_at.asc()))

    snapshot_ids = [snapshot.id for snapshot in snapshots]
    items = _load_snapshot_items(
        snapshot_ids,
        team_ids=team_ids,
        requested_team_id=getattr(query, "team_id", None),
        requested_service_id=getattr(query, "service_id", None),
    )

    latest_snapshot = snapshots[-1] if snapshots else None

    return {
        "version": 1,
        "window": {
            "days": days,
            "since": serialize_utc_datetime(since),
            "until": serialize_utc_datetime(until),
            "bucket": bucket,
        },
        "summary": _history_summary(snapshots, items),
        "series": {
            "impact_by_bucket": _impact_series(snapshots, bucket=bucket),
            "status_by_bucket": _status_series(items, bucket=bucket),
            "reason_by_bucket": _reason_series(items, bucket=bucket),
        },
        "top_services": _top_historically_affected_services(items, limit=limit),
        "latest_snapshot": serialize_service_impact_snapshot(latest_snapshot) if latest_snapshot else None,
        "filters": {
            "team_id": getattr(query, "team_id", None),
            "service_id": getattr(query, "service_id", None),
            "days": days,
            "bucket": bucket,
            "limit": limit,
        },
    }


def cleanup_service_impact_snapshots(*, retention_days):
    cutoff = utc_now() - timedelta(days=int(retention_days))
    old_ids = [
        snapshot.id
        for snapshot in ServiceImpactSnapshot
        .select(ServiceImpactSnapshot.id)
        .where(ServiceImpactSnapshot.captured_at < cutoff)
    ]

    if not old_ids:
        return 0

    with database_proxy.atomic():
        ServiceImpactSnapshotItem.delete().where(
            ServiceImpactSnapshotItem.snapshot.in_(old_ids)
        ).execute()
        deleted = ServiceImpactSnapshot.delete().where(
            ServiceImpactSnapshot.id.in_(old_ids)
        ).execute()

    return deleted


def serialize_service_impact_snapshot(snapshot, *, include_items=False):
    if not snapshot:
        return None

    data = {
        "id": snapshot.id,
        "uid": str(snapshot.uid),
        "group_id": snapshot.group_id,
        "team_id": snapshot.team_id,
        "service_id": snapshot.service_id,
        "source": snapshot.source,
        "scope": snapshot.scope,
        "captured_at": serialize_utc_datetime(snapshot.captured_at),
        "max_depth": snapshot.max_depth,
        "include_disabled": snapshot.include_disabled,
        "include_operational": snapshot.include_operational,
        "services_count": snapshot.services_count,
        "affected_services": snapshot.affected_services,
        "critical_services": snapshot.critical_services,
        "major_outage_services": snapshot.major_outage_services,
        "partial_outage_services": snapshot.partial_outage_services,
        "degraded_services": snapshot.degraded_services,
        "maintenance_services": snapshot.maintenance_services,
        "unknown_services": snapshot.unknown_services,
        "alert_group_impacted_services": snapshot.alert_group_impacted_services,
        "dependency_impacted_services": snapshot.dependency_impacted_services,
        "own_status_impacted_services": snapshot.own_status_impacted_services,
        "open_alert_groups_total": snapshot.open_alert_groups_total,
        "critical_open_alert_groups_total": snapshot.critical_open_alert_groups_total,
        "upstream_issues_total": snapshot.upstream_issues_total,
        "cycle_detected_count": snapshot.cycle_detected_count,
        "depth_limited_count": snapshot.depth_limited_count,
        "summary": snapshot.summary or {},
        "filters": snapshot.filters or {},
    }

    if include_items:
        data["items"] = [
            serialize_service_impact_snapshot_item(item)
            for item in snapshot.items.order_by(ServiceImpactSnapshotItem.service_name.asc())
        ]

    return data


def serialize_service_impact_snapshot_item(item):
    return {
        "id": item.id,
        "snapshot_id": item.snapshot_id,
        "group_id": item.group_id,
        "team_id": item.team_id,
        "service_id": item.service_id,
        "captured_at": serialize_utc_datetime(item.captured_at),
        "service_slug": item.service_slug,
        "service_name": item.service_name,
        "team_slug": item.team_slug,
        "team_name": item.team_name,
        "criticality": item.criticality,
        "tier": item.tier,
        "own_status": item.own_status,
        "alert_impact_status": item.alert_impact_status,
        "dependency_impact_status": item.dependency_impact_status,
        "effective_status": item.effective_status,
        "primary_reason": item.primary_reason,
        "open_alert_groups": item.open_alert_groups,
        "critical_open_alert_groups": item.critical_open_alert_groups,
        "upstream_issues_count": item.upstream_issues_count,
        "blast_radius_direct": item.blast_radius_direct,
        "blast_radius_total": item.blast_radius_total,
        "blast_radius_critical": item.blast_radius_critical,
        "blast_radius_tier_1": item.blast_radius_tier_1,
        "cycle_detected": item.cycle_detected,
        "depth_limited": item.depth_limited,
        "root_causes": item.root_causes or [],
        "explanation": item.explanation,
        "blast_radius": item.blast_radius,
        "payload": item.payload or {},
    }


def _normalize_snapshot_query(query):
    if query is None:
        return SnapshotImpactQuery()

    if isinstance(query, dict):
        return SimpleNamespace(**query)

    return query


def _snapshot_scope(query, *, team_ids=None):
    if getattr(query, "service_id", None):
        return "service"
    if getattr(query, "team_id", None):
        return "team"
    if team_ids is not None:
        return "allowed_teams"
    return "all"


def _load_services(service_ids):
    service_ids = [service_id for service_id in service_ids if service_id]

    if not service_ids:
        return {}

    return {service.id: service for service in Service.select().where(Service.id.in_(service_ids))}


def _single_group_id(services):
    group_ids = {service.group_id for service in services.values() if service.group_id}
    return next(iter(group_ids)) if len(group_ids) == 1 else None


def _create_snapshot_item(snapshot, item, services, captured_at):
    service_id = item.get("service_id")
    service = services.get(service_id)
    blast_radius = item.get("blast_radius") or {}

    ServiceImpactSnapshotItem.create(
        snapshot=snapshot,
        group_id=service.group_id if service else None,
        team_id=item.get("team_id") or (service.team_id if service else None),
        service_id=service_id,
        captured_at=captured_at,
        service_slug=item.get("service_slug"),
        service_name=item.get("service_name"),
        team_slug=item.get("team_slug"),
        team_name=item.get("team_name"),
        criticality=item.get("criticality"),
        tier=item.get("tier"),
        own_status=item.get("own_status") or "unknown",
        alert_impact_status=item.get("alert_impact_status") or "operational",
        dependency_impact_status=item.get("dependency_impact_status") or "operational",
        effective_status=item.get("effective_status") or "unknown",
        primary_reason=item.get("primary_reason") or "unknown",
        open_alert_groups=int(item.get("open_alert_groups") or 0),
        critical_open_alert_groups=int(item.get("critical_open_alert_groups") or 0),
        upstream_issues_count=int(item.get("upstream_issues_count") or 0),
        blast_radius_direct=int(blast_radius.get("direct_downstream") or 0),
        blast_radius_total=int(blast_radius.get("transitive_downstream") or 0),
        blast_radius_critical=int(blast_radius.get("critical_downstream") or 0),
        blast_radius_tier_1=int(blast_radius.get("tier_1_downstream") or 0),
        cycle_detected=bool(item.get("cycle_detected")),
        depth_limited=bool(item.get("depth_limited")),
        root_causes=item.get("root_causes") or [],
        explanation=item.get("explanation"),
        blast_radius=blast_radius,
        payload=item,
    )


def _build_snapshot_summary(items, impact_summary):
    status_counter = Counter(item.get("effective_status") or "unknown" for item in items)
    reason_counter = Counter(item.get("primary_reason") or "unknown" for item in items)

    return {
        "services": len(items),
        "affected_services": sum(1 for item in items if _is_affected(item.get("effective_status"))),
        "critical_services": status_counter.get("major_outage", 0),
        "major_outage_services": status_counter.get("major_outage", 0),
        "partial_outage_services": status_counter.get("partial_outage", 0),
        "degraded_services": status_counter.get("degraded", 0),
        "maintenance_services": status_counter.get("maintenance", 0),
        "unknown_services": status_counter.get("unknown", 0),
        "alert_group_impacted_services": reason_counter.get("alert_group", 0),
        "dependency_impacted_services": reason_counter.get("upstream_dependency", 0),
        "own_status_impacted_services": reason_counter.get("own_status", 0),
        "open_alert_groups_total": sum(int(item.get("open_alert_groups") or 0) for item in items),
        "critical_open_alert_groups_total": sum(int(item.get("critical_open_alert_groups") or 0) for item in items),
        "upstream_issues_total": sum(int(item.get("upstream_issues_count") or 0) for item in items),
        "cycle_detected_count": sum(1 for item in items if item.get("cycle_detected")),
        "depth_limited_count": sum(1 for item in items if item.get("depth_limited")),
        "by_effective_status": dict(status_counter),
        "by_primary_reason": dict(reason_counter),
        "impact_summary": impact_summary,
    }


def _snapshot_query(*, since, team_ids=None, requested_team_id=None, requested_service_id=None):
    query = ServiceImpactSnapshot.select().where(ServiceImpactSnapshot.captured_at >= since)

    if requested_service_id:
        matching_snapshot_ids = ServiceImpactSnapshotItem.select(ServiceImpactSnapshotItem.snapshot_id).where(
            ServiceImpactSnapshotItem.service == requested_service_id
        )
        query = query.where(ServiceImpactSnapshot.id.in_(matching_snapshot_ids))
    elif requested_team_id:
        matching_snapshot_ids = ServiceImpactSnapshotItem.select(ServiceImpactSnapshotItem.snapshot_id).where(
            ServiceImpactSnapshotItem.team == requested_team_id
        )
        query = query.where(ServiceImpactSnapshot.id.in_(matching_snapshot_ids))
    elif team_ids is not None:
        team_ids = list(team_ids)
        if not team_ids:
            return ServiceImpactSnapshot.select().where(False)
        matching_snapshot_ids = ServiceImpactSnapshotItem.select(ServiceImpactSnapshotItem.snapshot_id).where(
            ServiceImpactSnapshotItem.team.in_(team_ids)
        )
        query = query.where(ServiceImpactSnapshot.id.in_(matching_snapshot_ids))

    return query


def _load_snapshot_items(snapshot_ids, *, team_ids=None, requested_team_id=None, requested_service_id=None):
    if not snapshot_ids:
        return []

    query = ServiceImpactSnapshotItem.select().where(ServiceImpactSnapshotItem.snapshot.in_(snapshot_ids))

    if requested_service_id:
        query = query.where(ServiceImpactSnapshotItem.service == requested_service_id)
    elif requested_team_id:
        query = query.where(ServiceImpactSnapshotItem.team == requested_team_id)
    elif team_ids is not None:
        team_ids = list(team_ids)
        if not team_ids:
            return []
        query = query.where(ServiceImpactSnapshotItem.team.in_(team_ids))

    return list(query.order_by(ServiceImpactSnapshotItem.captured_at.asc()))


def _history_summary(snapshots, items):
    latest = snapshots[-1] if snapshots else None
    affected_samples = sum(1 for item in items if _is_affected(item.effective_status))
    service_ids = {item.service_id for item in items if item.service_id}

    return {
        "snapshots": len(snapshots),
        "services_observed": len(service_ids),
        "affected_service_samples": affected_samples,
        "affected_sample_ratio": round(affected_samples / len(items), 4) if items else 0,
        "latest_snapshot_at": serialize_utc_datetime(latest.captured_at) if latest else None,
        "latest_services": latest.services_count if latest else 0,
        "latest_affected_services": latest.affected_services if latest else 0,
        "latest_critical_services": latest.critical_services if latest else 0,
        "max_affected_services": max((snapshot.affected_services for snapshot in snapshots), default=0),
        "max_critical_services": max((snapshot.critical_services for snapshot in snapshots), default=0),
        "avg_affected_services": round(_avg(snapshot.affected_services for snapshot in snapshots), 2),
        "latest_by_effective_status": latest.summary.get("by_effective_status", {}) if latest and latest.summary else {},
        "latest_by_primary_reason": latest.summary.get("by_primary_reason", {}) if latest and latest.summary else {},
    }


def _impact_series(snapshots, *, bucket):
    grouped = defaultdict(list)

    for snapshot in snapshots:
        grouped[_bucket(snapshot.captured_at, bucket)].append(snapshot)

    result = []

    for bucket_key in sorted(grouped):
        rows = grouped[bucket_key]
        result.append({
            "bucket": bucket_key,
            "snapshots": len(rows),
            "services_avg": round(_avg(row.services_count for row in rows), 2),
            "affected_avg": round(_avg(row.affected_services for row in rows), 2),
            "affected_max": max(row.affected_services for row in rows),
            "critical_max": max(row.critical_services for row in rows),
            "alert_group_avg": round(_avg(row.alert_group_impacted_services for row in rows), 2),
            "dependency_avg": round(_avg(row.dependency_impacted_services for row in rows), 2),
            "own_status_avg": round(_avg(row.own_status_impacted_services for row in rows), 2),
            "open_alert_groups_max": max(row.open_alert_groups_total for row in rows),
        })

    return result


def _status_series(items, *, bucket):
    grouped = defaultdict(Counter)

    for item in items:
        grouped[_bucket(item.captured_at, bucket)][item.effective_status or "unknown"] += 1

    return [
        {
            "bucket": bucket_key,
            "operational": counter.get("operational", 0),
            "degraded": counter.get("degraded", 0),
            "partial_outage": counter.get("partial_outage", 0),
            "major_outage": counter.get("major_outage", 0),
            "maintenance": counter.get("maintenance", 0),
            "unknown": counter.get("unknown", 0),
            "disabled": counter.get("disabled", 0),
        }
        for bucket_key, counter in sorted(grouped.items())
    ]


def _reason_series(items, *, bucket):
    grouped = defaultdict(Counter)

    for item in items:
        grouped[_bucket(item.captured_at, bucket)][item.primary_reason or "unknown"] += 1

    return [
        {
            "bucket": bucket_key,
            "alert_group": counter.get("alert_group", 0),
            "upstream_dependency": counter.get("upstream_dependency", 0),
            "own_status": counter.get("own_status", 0),
            "maintenance": counter.get("maintenance", 0),
            "unknown": counter.get("unknown", 0),
        }
        for bucket_key, counter in sorted(grouped.items())
    ]


def _top_historically_affected_services(items, *, limit):
    grouped = defaultdict(list)

    for item in items:
        if item.service_id:
            grouped[item.service_id].append(item)

    rows = []

    for service_id, service_items in grouped.items():
        service_items.sort(key=lambda item: item.captured_at)
        affected_items = [item for item in service_items if _is_affected(item.effective_status)]
        last = service_items[-1]
        worst = max(service_items, key=lambda item: _status_rank(item.effective_status))
        reason_counts = Counter(item.primary_reason or "unknown" for item in affected_items)

        rows.append({
            "service_id": service_id,
            "service_slug": last.service_slug,
            "service_name": last.service_name,
            "team_id": last.team_id,
            "team_slug": last.team_slug,
            "team_name": last.team_name,
            "samples": len(service_items),
            "affected_samples": len(affected_items),
            "affected_percent": round((len(affected_items) / len(service_items)) * 100, 2) if service_items else 0,
            "first_affected_at": serialize_utc_datetime(affected_items[0].captured_at) if affected_items else None,
            "last_affected_at": serialize_utc_datetime(affected_items[-1].captured_at) if affected_items else None,
            "last_seen_at": serialize_utc_datetime(last.captured_at),
            "last_effective_status": last.effective_status,
            "last_primary_reason": last.primary_reason,
            "worst_effective_status": worst.effective_status,
            "max_open_alert_groups": max(item.open_alert_groups for item in service_items),
            "max_critical_open_alert_groups": max(item.critical_open_alert_groups for item in service_items),
            "max_upstream_issues": max(item.upstream_issues_count for item in service_items),
            "max_blast_radius_total": max(item.blast_radius_total for item in service_items),
            "primary_reasons": dict(reason_counts),
        })

    rows.sort(
        key=lambda row: (
            row["affected_samples"],
            _status_rank(row["worst_effective_status"]),
            row["max_open_alert_groups"],
            row["max_upstream_issues"],
        ),
        reverse=True,
    )

    return rows[:limit]


def _bucket(value, bucket):
    if bucket == "hour":
        return value.strftime("%Y-%m-%dT%H:00:00Z")
    return value.strftime("%Y-%m-%d")


def _avg(values):
    values = list(values)
    if not values:
        return 0
    return sum(values) / len(values)


def _is_affected(status):
    return status in IMPACTFUL_STATUSES


def _status_rank(status):
    return STATUS_RANK.get(status or "unknown", 0)
