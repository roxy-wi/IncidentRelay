from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from app.modules.common import utc_now
from app.modules.db.models import Alert, AlertGroup, Service, Team
from app.services.serializers.common import serialize_utc_datetime


OPEN_ALERT_GROUP_STATUSES = {"firing", "acknowledged"}


def build_alert_analytics_v1(query, *, team_ids=None):
    """Build period-based alert quality and response analytics.

    Child Alert rows provide persisted alert occurrence counts for the selected window.
    AlertGroup rows provide lifecycle timing and current unresolved state.
    Current unresolved lists intentionally include old open groups even when they
    started before the selected analytics window so forgotten alerts remain
    visible.
    """

    days = int(getattr(query, "days", 30) or 30)
    limit = int(getattr(query, "limit", 10) or 10)
    requested_team_id = getattr(query, "team_id", None)

    until = utc_now()
    since = until - timedelta(days=days)

    scoped_team_ids = [requested_team_id] if requested_team_id else team_ids
    if scoped_team_ids is not None:
        scoped_team_ids = sorted({int(team_id) for team_id in scoped_team_ids if team_id})
        if not scoped_team_ids:
            return _empty_payload(days=days, limit=limit, since=since, until=until, team_id=requested_team_id)

    groups = _load_relevant_groups(
        team_ids=scoped_team_ids,
        since=since,
        until=until,
    )
    raw_alerts = _load_raw_alerts(
        team_ids=scoped_team_ids,
        since=since,
        until=until,
    )

    groups_by_id = {group.id: group for group in groups}
    missing_group_ids = {
        alert.group_id
        for alert in raw_alerts
        if alert.group_id and alert.group_id not in groups_by_id
    }
    if missing_group_ids:
        for group in _load_groups_by_ids(missing_group_ids, team_ids=scoped_team_ids):
            groups_by_id[group.id] = group

    metadata = _load_group_metadata(groups_by_id.values())
    created_groups = [
        group
        for group in groups_by_id.values()
        if _in_window(group.first_seen_at, since, until)
        and not _is_merged(group)
    ]
    current_open_groups = [
        group
        for group in groups_by_id.values()
        if _is_current_open(group)
    ]
    actionable_created_groups = [
        group
        for group in created_groups
        if not _is_suppressed(group)
    ]
    actionable_open_groups = [
        group
        for group in current_open_groups
        if not _is_suppressed(group)
    ]

    resolved_groups = [
        group
        for group in groups_by_id.values()
        if not _is_merged(group)
        and not _is_suppressed(group)
        and _in_window(group.resolved_at, since, until)
    ]
    resolved_without_ack_groups = [
        group
        for group in resolved_groups
        if group.acknowledged_at is None
    ]

    mtta_values = []
    mttr_values = []
    acknowledged_created = 0

    for group in actionable_created_groups:
        if group.acknowledged_at and group.first_seen_at:
            acknowledged_created += 1
            mtta_values.append(_duration_seconds(group.first_seen_at, group.acknowledged_at))

        if group.resolved_at and group.first_seen_at:
            mttr_values.append(_duration_seconds(group.first_seen_at, group.resolved_at))

    summary = {
        "alert_groups": len(created_groups),
        "occurrences": len(raw_alerts),
        "open_now": len(current_open_groups),
        "unacknowledged": sum(
            1
            for group in actionable_open_groups
            if group.status == "firing" and group.acknowledged_at is None
        ),
        "ack_rate": _ratio(acknowledged_created, len(actionable_created_groups)),
        "resolved_without_ack": len(resolved_without_ack_groups),
        "mtta_seconds_p50": _percentile_or_none(mtta_values, 50),
        "mtta_seconds_p95": _percentile_or_none(mtta_values, 95),
        "mttr_seconds_p50": _percentile_or_none(mttr_values, 50),
        "mttr_seconds_p95": _percentile_or_none(mttr_values, 95),
    }

    oldest_unresolved = sorted(
        actionable_open_groups,
        key=lambda group: (group.first_seen_at or until, group.id),
    )[:limit]

    unacknowledged = [
        group
        for group in actionable_open_groups
        if group.status == "firing" and group.acknowledged_at is None
    ]
    unacknowledged = sorted(
        unacknowledged,
        key=lambda group: (
            _group_priority_order(group),
            group.first_seen_at or until,
            group.id,
        ),
    )[:limit]

    resolved_without_ack = sorted(
        resolved_without_ack_groups,
        key=lambda group: (group.resolved_at or group.last_seen_at or group.first_seen_at, group.id),
        reverse=True,
    )[:limit]

    return {
        "version": 1,
        "window": {
            "days": days,
            "since": serialize_utc_datetime(since),
            "until": serialize_utc_datetime(until),
        },
        "summary": summary,
        "top_noisy": _build_top_noisy(raw_alerts, groups_by_id, limit=limit),
        "oldest_unresolved": [
            _serialize_group_row(group, until, metadata)
            for group in oldest_unresolved
        ],
        "attention": {
            "unacknowledged": [
                _serialize_group_row(group, until, metadata, problem="unacknowledged")
                for group in unacknowledged
            ],
            "resolved_without_ack": [
                _serialize_group_row(group, until, metadata, problem="resolved_without_ack")
                for group in resolved_without_ack
            ],
            "resolved_without_ack_by_alert": _build_resolved_without_ack_by_alert(
                resolved_groups,
                limit=limit,
            ),
        },
        "series": {
            "lifecycle_by_day": _build_lifecycle_series(
                groups_by_id.values(),
                since=since,
                until=until,
            ),
        },
        "filters": {
            "team_id": requested_team_id,
            "days": days,
            "limit": limit,
        },
    }


def _empty_payload(*, days, limit, since, until, team_id):
    return {
        "version": 1,
        "window": {
            "days": days,
            "since": serialize_utc_datetime(since),
            "until": serialize_utc_datetime(until),
        },
        "summary": {
            "alert_groups": 0,
            "occurrences": 0,
            "open_now": 0,
            "unacknowledged": 0,
            "ack_rate": None,
            "resolved_without_ack": 0,
            "mtta_seconds_p50": None,
            "mtta_seconds_p95": None,
            "mttr_seconds_p50": None,
            "mttr_seconds_p95": None,
        },
        "top_noisy": [],
        "oldest_unresolved": [],
        "attention": {
            "unacknowledged": [],
            "resolved_without_ack": [],
            "resolved_without_ack_by_alert": [],
        },
        "series": {"lifecycle_by_day": []},
        "filters": {
            "team_id": team_id,
            "days": days,
            "limit": limit,
        },
    }


def _load_relevant_groups(*, team_ids, since, until):
    query = AlertGroup.select().where(
        (AlertGroup.merged_into.is_null(True))
        & (AlertGroup.status != "merged")
        & (
            _window_condition(AlertGroup.first_seen_at, since, until)
            | _window_condition(AlertGroup.acknowledged_at, since, until)
            | _window_condition(AlertGroup.resolved_at, since, until)
            | AlertGroup.status.in_(tuple(OPEN_ALERT_GROUP_STATUSES))
        )
    )

    query = _apply_team_scope(query, AlertGroup.team, team_ids)
    if query is None:
        return []

    return list(query)


def _load_groups_by_ids(group_ids, *, team_ids):
    group_ids = list(group_ids)
    if not group_ids:
        return []

    query = AlertGroup.select().where(AlertGroup.id.in_(group_ids))
    query = _apply_team_scope(query, AlertGroup.team, team_ids)
    if query is None:
        return []

    return list(query)


def _load_raw_alerts(*, team_ids, since, until):
    query = Alert.select().where(
        _window_condition(Alert.first_seen_at, since, until)
    )
    query = _apply_team_scope(query, Alert.team, team_ids)
    if query is None:
        return []

    return list(query)


def _apply_team_scope(query, field, team_ids):
    if team_ids is None:
        return query
    if not team_ids:
        return None
    return query.where(field.in_(team_ids))


def _load_group_metadata(groups):
    team_ids = {group.team_id for group in groups if group.team_id}
    service_ids = {group.service_id for group in groups if group.service_id}

    teams = {
        team.id: team
        for team in Team.select().where(Team.id.in_(team_ids))
    } if team_ids else {}
    services = {
        service.id: service
        for service in Service.select().where(Service.id.in_(service_ids))
    } if service_ids else {}

    return {"teams": teams, "services": services}


def _build_top_noisy(raw_alerts, groups_by_id, *, limit):
    buckets = defaultdict(lambda: {"occurrences": 0, "group_ids": set()})

    for alert in raw_alerts:
        alertname = _alert_name(alert)
        if not alertname:
            continue

        bucket = buckets[alertname]
        bucket["occurrences"] += 1
        if alert.group_id:
            bucket["group_ids"].add(alert.group_id)

    rows = []
    for alertname, bucket in buckets.items():
        group_ids = bucket["group_ids"]
        groups = [groups_by_id[group_id] for group_id in group_ids if group_id in groups_by_id]
        actionable_groups = [group for group in groups if not _is_suppressed(group)]
        acknowledged = sum(1 for group in actionable_groups if group.acknowledged_at)
        group_count = len(group_ids)

        rows.append({
            "alertname": alertname,
            "occurrences": bucket["occurrences"],
            "groups": group_count,
            "dedup_ratio": round(bucket["occurrences"] / group_count, 2) if group_count else None,
            "open": sum(1 for group in groups if _is_current_open(group)),
            "ack_rate": _ratio(acknowledged, len(actionable_groups)),
        })

    rows.sort(
        key=lambda row: (
            row["occurrences"],
            row["groups"],
            row["alertname"].lower(),
        ),
        reverse=True,
    )
    return rows[:limit]


def _build_resolved_without_ack_by_alert(resolved_groups, *, limit):
    """Aggregate resolved-without-ACK quality signals by alert name."""

    buckets = defaultdict(lambda: {
        "resolved_groups": 0,
        "resolved_without_ack": 0,
        "without_ack_lifetimes": [],
    })

    for group in resolved_groups:
        alertname = _group_alert_name(group)
        if not alertname:
            continue

        bucket = buckets[alertname]
        bucket["resolved_groups"] += 1

        if group.acknowledged_at is not None:
            continue

        bucket["resolved_without_ack"] += 1
        if group.first_seen_at and group.resolved_at:
            bucket["without_ack_lifetimes"].append(
                _duration_seconds(group.first_seen_at, group.resolved_at)
            )

    rows = []
    for alertname, bucket in buckets.items():
        without_ack = bucket["resolved_without_ack"]
        if not without_ack:
            continue

        resolved_groups_count = bucket["resolved_groups"]
        rows.append({
            "alertname": alertname,
            "resolved_groups": resolved_groups_count,
            "resolved_without_ack": without_ack,
            "rate": _ratio(without_ack, resolved_groups_count),
            "median_lifetime_seconds": _percentile_or_none(
                bucket["without_ack_lifetimes"],
                50,
            ),
        })

    rows.sort(
        key=lambda row: (
            -row["resolved_without_ack"],
            -(row["rate"] or 0),
            -row["resolved_groups"],
            row["alertname"].lower(),
        )
    )
    return rows[:limit]


def _build_lifecycle_series(groups, *, since, until):
    buckets = {
        day: {
            "bucket": day,
            "created": 0,
            "acknowledged": 0,
            "resolved": 0,
        }
        for day in _day_buckets(since, until)
    }

    for group in groups:
        if _is_merged(group):
            continue

        for field_name, key in (
            ("first_seen_at", "created"),
            ("acknowledged_at", "acknowledged"),
            ("resolved_at", "resolved"),
        ):
            value = getattr(group, field_name, None)
            if not _in_window(value, since, until):
                continue
            day = value.date().isoformat()
            if day in buckets:
                buckets[day][key] += 1

    return list(buckets.values())


def _serialize_group_row(group, now, metadata, *, problem=None):
    team = metadata["teams"].get(group.team_id)
    service = metadata["services"].get(group.service_id)
    age_seconds = _duration_seconds(group.first_seen_at, now) if group.first_seen_at else None

    return {
        "id": group.id,
        "title": group.title,
        "status": group.status,
        "severity": group.severity,
        "priority": group.priority_slug or "p3",
        "team_id": group.team_id,
        "team_slug": team.slug if team else None,
        "team_name": team.name if team else None,
        "service_id": group.service_id,
        "service_slug": service.slug if service else None,
        "service_name": service.name if service else None,
        "first_seen_at": serialize_utc_datetime(group.first_seen_at),
        "last_seen_at": serialize_utc_datetime(group.last_seen_at),
        "acknowledged_at": serialize_utc_datetime(group.acknowledged_at),
        "resolved_at": serialize_utc_datetime(group.resolved_at),
        "age_seconds": age_seconds,
        "problem": problem,
    }


def _group_alert_name(group):
    common_labels = group.common_labels or {}
    if isinstance(common_labels, dict) and common_labels.get("alertname"):
        return str(common_labels["alertname"])

    payload_summary = group.payload_summary or {}
    if isinstance(payload_summary, dict) and payload_summary.get("alertname"):
        return str(payload_summary["alertname"])

    return str(group.title or "").strip() or None


def _group_priority_order(group):
    try:
        return int(group.priority_order or 3)
    except (TypeError, ValueError):
        return 3


def _alert_name(alert):
    labels = alert.labels or {}
    if isinstance(labels, dict) and labels.get("alertname"):
        return str(labels["alertname"])
    return str(alert.title or "").strip() or None


def _is_current_open(group):
    return (
        not _is_merged(group)
        and group.status in OPEN_ALERT_GROUP_STATUSES
        and group.resolved_at is None
    )


def _is_merged(group):
    return bool(group.merged_into_id or group.status == "merged")


def _is_suppressed(group):
    return bool(
        getattr(group, "maintenance_suppressed", False)
        or getattr(group, "orchestration_suppressed", False)
    )


def _window_condition(field, since, until):
    return (field >= since) & (field <= until)


def _in_window(value, since, until):
    return bool(value and since <= value <= until)


def _duration_seconds(start, end):
    return max(0, int((end - start).total_seconds()))


def _ratio(numerator, denominator):
    if not denominator:
        return None
    return round(numerator / denominator, 4)


def _percentile_or_none(values, percentile):
    if not values:
        return None

    values = sorted(values)
    if len(values) == 1:
        return values[0]

    index = round((percentile / 100) * (len(values) - 1))
    return values[index]


def _day_buckets(since, until):
    buckets = []
    current = datetime(since.year, since.month, since.day)
    end = datetime(until.year, until.month, until.day)

    while current <= end:
        buckets.append(current.date().isoformat())
        current += timedelta(days=1)

    return buckets
