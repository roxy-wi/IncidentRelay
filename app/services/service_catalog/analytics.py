from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import mean

from app.modules.db.models import Alert, AlertGroup, Service
from app.services.serializers import serialize_utc_datetime
from app.services.service_catalog.impact import build_single_service_impact_v2


OPEN_ALERT_GROUP_STATUSES = {"firing", "acknowledged"}


class AnalyticsImpactQuery:
    include_disabled = True
    include_explanation = True
    include_root_causes = True
    include_blast_radius = True
    include_paths = False
    max_depth = 5


def build_service_analytics_v2(query, *, team_ids=None):
    """Build Service Analytics v2 payload.

    Analytics answers historical questions for a selected time window:
    - grouped alert volume by service;
    - raw alert volume / noise;
    - response metrics;
    - maintenance suppression counters;
    - current impact snapshot per service.

    Current impact is included as a widget, but analytics remains
    period-based and should not replace /api/services/impact.
    """
    days = int(getattr(query, "days", 30) or 30)
    limit = int(getattr(query, "limit", 100) or 100)

    include_disabled = bool(getattr(query, "include_disabled", False))
    include_operational = bool(getattr(query, "include_operational", True))
    include_series = bool(getattr(query, "include_series", True))
    include_noise = bool(getattr(query, "include_noise", True))
    include_response = bool(getattr(query, "include_response", True))
    include_maintenance = bool(getattr(query, "include_maintenance", True))
    include_impact = bool(getattr(query, "include_impact", True))

    requested_team_id = getattr(query, "team_id", None)
    requested_service_id = getattr(query, "service_id", None)

    until = datetime.utcnow()
    since = until - timedelta(days=days)

    services = _load_services(
        team_ids=team_ids,
        requested_team_id=requested_team_id,
        requested_service_id=requested_service_id,
        include_disabled=include_disabled,
    )

    if not services:
        return _empty_payload(query, since=since, until=until)

    service_ids = list(services.keys())

    alert_groups = _load_alert_groups(
        service_ids,
        since=since,
        until=until,
    )
    raw_alerts = (
        _load_raw_alerts(service_ids, since=since, until=until)
        if include_noise or include_series
        else []
    )

    alert_groups_by_service = _group_by_service_id(alert_groups)
    raw_alerts_by_service = _group_by_service_id(raw_alerts)

    impact_by_service = {}

    if include_impact:
        for service_id, service in services.items():
            impact_by_service[service_id] = build_single_service_impact_v2(
                service_id,
                AnalyticsImpactQuery(),
                team_ids=[service.team_id],
            )

    items = []

    for service_id, service in services.items():
        item = _build_service_analytics_item(
            service,
            alert_groups_by_service.get(service_id, []),
            raw_alerts_by_service.get(service_id, []),
            since=since,
            until=until,
            days=days,
            include_noise=include_noise,
            include_response=include_response,
            include_maintenance=include_maintenance,
            impact=impact_by_service.get(service_id),
        )

        if not include_operational:
            impact = item.get("impact") or {}
            effective_status = impact.get("effective_status") or item["service_status"]

            if (
                effective_status == "operational"
                and item["alert_groups"]["open"] == 0
                and item["alert_groups"]["total"] == 0
            ):
                continue

        items.append(item)

    items = _sort_items(
        items,
        sort=getattr(query, "sort", "open_alert_groups"),
        order=getattr(query, "order", "desc"),
    )[:limit]

    series = (
        _build_series(
            alert_groups,
            raw_alerts,
            since=since,
            until=until,
        )
        if include_series
        else {
            "alert_groups_by_day": [],
            "raw_alerts_by_day": [],
            "impact_by_day": [],
        }
    )

    return {
        "version": 2,
        "window": {
            "days": days,
            "since": serialize_utc_datetime(since),
            "until": serialize_utc_datetime(until),
        },
        "items": items,
        "summary": _build_summary(items),
        "series": series,
        "filters": {
            "team_id": requested_team_id,
            "service_id": requested_service_id,
            "include_disabled": include_disabled,
            "include_operational": include_operational,
            "include_series": include_series,
            "include_noise": include_noise,
            "include_response": include_response,
            "include_maintenance": include_maintenance,
            "include_impact": include_impact,
            "days": days,
            "limit": limit,
            "sort": getattr(query, "sort", "open_alert_groups"),
            "order": getattr(query, "order", "desc"),
        },
    }


def _empty_payload(query, *, since, until):
    days = int(getattr(query, "days", 30) or 30)

    return {
        "version": 2,
        "window": {
            "days": days,
            "since": serialize_utc_datetime(since),
            "until": serialize_utc_datetime(until),
        },
        "items": [],
        "summary": {
            "services": 0,
            "affected_services": 0,
            "open_alert_groups": 0,
            "critical_open_alert_groups": 0,
            "raw_alerts": 0,
            "by_effective_status": {},
            "top_noisy_services": [],
        },
        "series": {
            "alert_groups_by_day": [],
            "raw_alerts_by_day": [],
            "impact_by_day": [],
        },
        "filters": {
            "team_id": getattr(query, "team_id", None),
            "service_id": getattr(query, "service_id", None),
            "days": days,
            "limit": getattr(query, "limit", 100),
            "sort": getattr(query, "sort", "open_alert_groups"),
            "order": getattr(query, "order", "desc"),
        },
    }


def _load_services(
    *,
    team_ids=None,
    requested_team_id=None,
    requested_service_id=None,
    include_disabled=False,
):
    query = Service.select().where(Service.deleted == False)  # noqa: E712

    if team_ids is not None:
        team_ids = list(team_ids)

        if not team_ids:
            return {}

        query = query.where(Service.team.in_(team_ids))

    if requested_team_id:
        query = query.where(Service.team == requested_team_id)

    if requested_service_id:
        query = query.where(Service.id == requested_service_id)

    if not include_disabled:
        query = query.where(Service.enabled == True)  # noqa: E712

    return {
        service.id: service
        for service in query
    }


def _load_alert_groups(service_ids, *, since, until):
    service_ids = list(service_ids)

    if not service_ids:
        return []

    query = AlertGroup.select().where(
        (AlertGroup.service.in_(service_ids))
        & (AlertGroup.last_seen_at >= since)
        & (AlertGroup.first_seen_at <= until)
    )

    if _has_field(AlertGroup, "merged_into"):
        query = query.where(AlertGroup.merged_into.is_null(True))

    return list(query)


def _load_raw_alerts(service_ids, *, since, until):
    if not _has_field(Alert, "service"):
        return []

    service_ids = list(service_ids)

    if not service_ids:
        return []

    query = Alert.select().where(Alert.service.in_(service_ids))

    if _has_field(Alert, "created_at"):
        query = query.where(
            (Alert.created_at >= since)
            & (Alert.created_at <= until)
        )

    return list(query)


def _group_by_service_id(rows):
    grouped = defaultdict(list)

    for row in rows:
        service_id = getattr(row, "service_id", None)

        if service_id:
            grouped[service_id].append(row)

    return grouped


def _build_service_analytics_item(
    service,
    alert_groups,
    raw_alerts,
    *,
    since,
    until,
    days,
    include_noise,
    include_response,
    include_maintenance,
    impact,
):
    alert_group_metrics = _alert_group_metrics(alert_groups)
    raw_alert_metrics = (
        _raw_alert_metrics(raw_alerts, alert_groups)
        if include_noise
        else _empty_noise_metrics()
    )
    response_metrics = (
        _response_metrics(alert_groups)
        if include_response
        else _empty_response_metrics()
    )
    maintenance_metrics = (
        _maintenance_metrics(alert_groups)
        if include_maintenance
        else _empty_maintenance_metrics()
    )

    impact_payload = impact or {}

    return {
        "service_id": service.id,
        "service_slug": service.slug,
        "service_name": service.name,
        "team_id": service.team_id,
        "team_slug": service.team.slug if service.team_id and service.team else None,
        "team_name": service.team.name if service.team_id and service.team else None,
        "service_status": service.status,
        "service_criticality": service.criticality,
        "service_environment": service.environment,
        "service_tier": service.tier,
        "enabled": service.enabled,
        "window": {
            "days": days,
            "since": serialize_utc_datetime(since),
            "until": serialize_utc_datetime(until),
        },
        "alert_groups": alert_group_metrics,
        "noise": raw_alert_metrics,
        "response": response_metrics,
        "maintenance": maintenance_metrics,
        "impact": _analytics_impact_widget(impact_payload, service),
        "last_alert_at": alert_group_metrics["last_seen_at"],
    }


def _alert_group_metrics(alert_groups):
    by_status = Counter()
    by_severity = Counter()

    open_count = 0
    critical_open_count = 0
    last_seen_at = None
    first_seen_at = None

    for group in alert_groups:
        status = str(group.status or "unknown")
        severity = str(group.severity or "unknown")

        by_status[status] += 1
        by_severity[severity] += 1

        if status in OPEN_ALERT_GROUP_STATUSES:
            open_count += 1

            if severity == "critical":
                critical_open_count += 1

        if group.last_seen_at and (last_seen_at is None or group.last_seen_at > last_seen_at):
            last_seen_at = group.last_seen_at

        if group.first_seen_at and (first_seen_at is None or group.first_seen_at < first_seen_at):
            first_seen_at = group.first_seen_at

    return {
        "total": len(alert_groups),
        "open": open_count,
        "firing": by_status.get("firing", 0),
        "acknowledged": by_status.get("acknowledged", 0),
        "resolved": by_status.get("resolved", 0),
        "silenced": by_status.get("silenced", 0),
        "critical_open": critical_open_count,
        "by_status": dict(by_status),
        "by_severity": dict(by_severity),
        "first_seen_at": serialize_utc_datetime(first_seen_at) if first_seen_at else None,
        "last_seen_at": serialize_utc_datetime(last_seen_at) if last_seen_at else None,
    }


def _raw_alert_metrics(raw_alerts, alert_groups):
    raw_count = len(raw_alerts)

    if raw_count == 0:
        raw_count = sum(
            int(getattr(group, "alert_count", 0) or 0)
            for group in alert_groups
        )

    group_count = len(alert_groups)
    top_alertnames = Counter()

    for alert in raw_alerts:
        alertname = _alertname_from_row(alert)

        if alertname:
            top_alertnames[alertname] += 1

    if not top_alertnames:
        for group in alert_groups:
            alertname = _alertname_from_row(group)

            if alertname:
                top_alertnames[alertname] += int(
                    getattr(group, "alert_count", 0) or 1
                )

    return {
        "raw_alerts": raw_count,
        "alert_groups": group_count,
        "dedup_ratio": round(raw_count / group_count, 2) if group_count else 0,
        "top_alertnames": [
            {
                "alertname": alertname,
                "count": count,
            }
            for alertname, count in top_alertnames.most_common(5)
        ],
    }


def _empty_noise_metrics():
    return {
        "raw_alerts": 0,
        "alert_groups": 0,
        "dedup_ratio": 0,
        "top_alertnames": [],
    }


def _response_metrics(alert_groups):
    acknowledged_groups = 0
    resolved_groups = 0
    mtta_values = []
    mttr_values = []

    has_ack_time = _has_field(AlertGroup, "acknowledged_at")
    has_resolved_time = _has_field(AlertGroup, "resolved_at")

    for group in alert_groups:
        status = str(group.status or "")

        if status == "acknowledged":
            acknowledged_groups += 1

        if status == "resolved":
            resolved_groups += 1

        if has_ack_time:
            acknowledged_at = getattr(group, "acknowledged_at", None)

            if acknowledged_at and group.first_seen_at:
                mtta_values.append(
                    max(
                        0,
                        int((acknowledged_at - group.first_seen_at).total_seconds()),
                    )
                )

        if has_resolved_time:
            resolved_at = getattr(group, "resolved_at", None)

            if resolved_at and group.first_seen_at:
                mttr_values.append(
                    max(
                        0,
                        int((resolved_at - group.first_seen_at).total_seconds()),
                    )
                )

    return {
        "acknowledged_groups": acknowledged_groups,
        "resolved_groups": resolved_groups,
        "mtta_seconds_avg": _mean_or_none(mtta_values),
        "mtta_seconds_p50": _percentile_or_none(mtta_values, 50),
        "mtta_seconds_p95": _percentile_or_none(mtta_values, 95),
        "mttr_seconds_avg": _mean_or_none(mttr_values),
        "mttr_seconds_p50": _percentile_or_none(mttr_values, 50),
        "mttr_seconds_p95": _percentile_or_none(mttr_values, 95),
    }


def _empty_response_metrics():
    return {
        "acknowledged_groups": 0,
        "resolved_groups": 0,
        "mtta_seconds_avg": None,
        "mtta_seconds_p50": None,
        "mtta_seconds_p95": None,
        "mttr_seconds_avg": None,
        "mttr_seconds_p50": None,
        "mttr_seconds_p95": None,
    }


def _maintenance_metrics(alert_groups):
    suppressed_groups = 0
    maintenance_window_ids = set()

    has_suppressed = _has_field(AlertGroup, "maintenance_suppressed")
    has_window = _has_field(AlertGroup, "maintenance_window")

    for group in alert_groups:
        if has_suppressed and getattr(group, "maintenance_suppressed", False):
            suppressed_groups += 1

        if has_window:
            window_id = getattr(group, "maintenance_window_id", None)

            if window_id:
                maintenance_window_ids.add(window_id)

    return {
        "windows": len(maintenance_window_ids),
        "suppressed_alert_groups": suppressed_groups,
    }


def _empty_maintenance_metrics():
    return {
        "windows": 0,
        "suppressed_alert_groups": 0,
    }


def _analytics_impact_widget(impact, service):
    blast_radius = impact.get("blast_radius") or {}

    return {
        "effective_status": impact.get("effective_status") or service.status,
        "primary_reason": impact.get("primary_reason"),
        "upstream_issues_count": impact.get("upstream_issues_count") or 0,
        "root_causes": len(impact.get("root_causes") or []),
        "blast_radius": {
            "direct_downstream": blast_radius.get("direct_downstream") or 0,
            "transitive_downstream": blast_radius.get("transitive_downstream") or 0,
            "critical_downstream": blast_radius.get("critical_downstream") or 0,
            "tier_1_downstream": blast_radius.get("tier_1_downstream") or 0,
        },
    }


def _build_series(alert_groups, raw_alerts, *, since, until):
    buckets = _day_buckets(since, until)

    alert_group_buckets = {
        day: {
            "bucket": day,
            "total": 0,
            "firing": 0,
            "acknowledged": 0,
            "resolved": 0,
            "silenced": 0,
            "critical": 0,
        }
        for day in buckets
    }

    raw_alert_buckets = {
        day: {
            "bucket": day,
            "raw_alerts": 0,
        }
        for day in buckets
    }

    for group in alert_groups:
        day = _bucket_day(group.last_seen_at or group.first_seen_at)

        if day not in alert_group_buckets:
            continue

        status = str(group.status or "unknown")
        severity = str(group.severity or "")

        alert_group_buckets[day]["total"] += 1

        if status in alert_group_buckets[day]:
            alert_group_buckets[day][status] += 1

        if severity == "critical":
            alert_group_buckets[day]["critical"] += 1

    raw_alerts_added = 0

    for alert in raw_alerts:
        created_at = getattr(alert, "created_at", None)
        day = _bucket_day(created_at)

        if day not in raw_alert_buckets:
            continue

        raw_alert_buckets[day]["raw_alerts"] += 1
        raw_alerts_added += 1

    if raw_alerts_added == 0:
        for group in alert_groups:
            day = _bucket_day(group.last_seen_at or group.first_seen_at)

            if day not in raw_alert_buckets:
                continue

            raw_alert_buckets[day]["raw_alerts"] += int(
                getattr(group, "alert_count", 0) or 1
            )

    return {
        "alert_groups_by_day": list(alert_group_buckets.values()),
        "raw_alerts_by_day": list(raw_alert_buckets.values()),
        "impact_by_day": [],
    }


def _build_summary(items):
    by_effective_status = Counter()
    affected_services = 0
    open_alert_groups = 0
    critical_open_alert_groups = 0
    raw_alerts = 0

    for item in items:
        impact = item.get("impact") or {}
        effective_status = impact.get("effective_status") or item.get("service_status") or "unknown"

        by_effective_status[effective_status] += 1

        if effective_status not in {"operational", "disabled"}:
            affected_services += 1

        open_alert_groups += item["alert_groups"]["open"]
        critical_open_alert_groups += item["alert_groups"]["critical_open"]
        raw_alerts += item["noise"]["raw_alerts"]

    top_noisy = sorted(
        items,
        key=lambda item: item["noise"]["raw_alerts"],
        reverse=True,
    )[:5]

    return {
        "services": len(items),
        "affected_services": affected_services,
        "open_alert_groups": open_alert_groups,
        "critical_open_alert_groups": critical_open_alert_groups,
        "raw_alerts": raw_alerts,
        "by_effective_status": dict(by_effective_status),
        "top_noisy_services": [
            {
                "service_id": item["service_id"],
                "service_slug": item["service_slug"],
                "service_name": item["service_name"],
                "raw_alerts": item["noise"]["raw_alerts"],
                "dedup_ratio": item["noise"]["dedup_ratio"],
            }
            for item in top_noisy
            if item["noise"]["raw_alerts"] > 0
        ],
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

    if sort == "open_alert_groups":
        return item["alert_groups"]["open"]

    if sort == "critical_open_alert_groups":
        return item["alert_groups"]["critical_open"]

    if sort == "raw_alerts":
        return item["noise"]["raw_alerts"]

    if sort == "dedup_ratio":
        return item["noise"]["dedup_ratio"]

    if sort == "mtta":
        return item["response"]["mtta_seconds_avg"] or 0

    if sort == "mttr":
        return item["response"]["mttr_seconds_avg"] or 0

    if sort == "blast_radius":
        return item["impact"]["blast_radius"]["transitive_downstream"]

    return item["alert_groups"]["open"]


def _alertname_from_row(row):
    labels = getattr(row, "labels", None)

    if isinstance(labels, dict) and labels.get("alertname"):
        return labels["alertname"]

    common_labels = getattr(row, "common_labels", None)

    if isinstance(common_labels, dict) and common_labels.get("alertname"):
        return common_labels["alertname"]

    payload_summary = getattr(row, "payload_summary", None)

    if isinstance(payload_summary, dict) and payload_summary.get("alertname"):
        return payload_summary["alertname"]

    title = getattr(row, "title", None)

    if title:
        return title

    return None


def _day_buckets(since, until):
    buckets = []
    current = datetime(since.year, since.month, since.day)
    end = datetime(until.year, until.month, until.day)

    while current <= end:
        buckets.append(current.date().isoformat())
        current += timedelta(days=1)

    return buckets


def _bucket_day(value):
    if not value:
        return None

    return value.date().isoformat()


def _mean_or_none(values):
    if not values:
        return None

    return int(mean(values))


def _percentile_or_none(values, percentile):
    if not values:
        return None

    values = sorted(values)

    if len(values) == 1:
        return values[0]

    index = round((percentile / 100) * (len(values) - 1))

    return values[index]


def _has_field(model, field_name):
    return field_name in model._meta.fields
