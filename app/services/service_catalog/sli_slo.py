from datetime import datetime, timedelta

from app.modules.db import maintenance_repo, services_repo
from app.modules.db.models import AlertGroup
from app.services.serializers import serialize_utc_datetime


SLI_TYPE_ACK_LATENCY = "alert_ack_latency"
SLI_TYPE_RESOLVE_LATENCY = "alert_resolve_latency"
SLI_TYPE_INCIDENT_AVAILABILITY = "incident_availability"
SLI_TYPE_INCIDENT_COUNT = "incident_count"

STATUS_MET = "met"
STATUS_AT_RISK = "at_risk"
STATUS_BREACHED = "breached"
STATUS_NO_DATA = "no_data"

DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 365

PRIORITY_VALUES = ("p1", "p2", "p3", "p4")
DEFAULT_IMPACT_PRIORITY_SCOPE = ("p1", "p2")
SLO_COMPARISON_PERCENT_GOOD_GTE = "percent_good_gte"
SLO_COMPARISON_VALUE_LTE = "value_lte"

SLI_TYPE_LABELS = {
    SLI_TYPE_ACK_LATENCY: "Alert acknowledgement latency",
    SLI_TYPE_RESOLVE_LATENCY: "Alert resolution latency",
    SLI_TYPE_INCIDENT_AVAILABILITY: "Incident-based availability",
    SLI_TYPE_INCIDENT_COUNT: "Impact incident count",
}


def default_slo_comparison_for_sli_type(sli_type):
    if sli_type in (
        SLI_TYPE_ACK_LATENCY,
        SLI_TYPE_RESOLVE_LATENCY,
        SLI_TYPE_INCIDENT_AVAILABILITY,
    ):
        return SLO_COMPARISON_PERCENT_GOOD_GTE

    if sli_type == SLI_TYPE_INCIDENT_COUNT:
        return SLO_COMPARISON_VALUE_LTE

    return SLO_COMPARISON_PERCENT_GOOD_GTE


def normalize_slo_window_days(days):
    return max(1, min(int(days or DEFAULT_WINDOW_DAYS), MAX_WINDOW_DAYS))


def evaluate_service_slos(slos, *, now=None, persist=True):
    """Evaluate a list of SLOs and return a dict keyed by SLO id."""
    now = now or datetime.utcnow()
    evaluations = {}

    for slo in slos:
        evaluations[slo.id] = evaluate_service_slo(slo, now=now, persist=persist)

    return evaluations


def evaluate_service_slo(slo, *, now=None, persist=True):
    """Evaluate one Service Level Objective."""
    now = now or datetime.utcnow()
    window_days = normalize_slo_window_days(slo.window_days)
    since = now - timedelta(days=window_days)
    sli = slo.sli

    if sli.sli_type == SLI_TYPE_ACK_LATENCY:
        evaluation = _evaluate_latency_slo(slo, since=since, now=now, field="acknowledged_at")
    elif sli.sli_type == SLI_TYPE_RESOLVE_LATENCY:
        evaluation = _evaluate_latency_slo(slo, since=since, now=now, field="resolved_at")
    elif sli.sli_type == SLI_TYPE_INCIDENT_AVAILABILITY:
        evaluation = _evaluate_availability_slo(slo, since=since, now=now)
    elif sli.sli_type == SLI_TYPE_INCIDENT_COUNT:
        evaluation = _evaluate_incident_count_slo(slo, since=since, now=now)
    else:
        evaluation = _base_evaluation(slo, since=since, now=now)
        evaluation.update({
            "status": STATUS_NO_DATA,
            "message": "Unsupported SLI type",
        })

    if persist:
        measurement = _persist_measurement(slo, evaluation)
        evaluation["measurement_id"] = measurement.id if measurement else None

    return evaluation


def validate_slo_for_sli(sli, data):
    """Return a validation error string if an SLO payload does not match its SLI."""
    expected_comparison = default_slo_comparison_for_sli_type(sli.sli_type)
    comparison = data.get("comparison") or expected_comparison

    if sli.sli_type in (SLI_TYPE_ACK_LATENCY, SLI_TYPE_RESOLVE_LATENCY):
        if comparison != SLO_COMPARISON_PERCENT_GOOD_GTE:
            return "Latency SLOs must use percent_good_gte comparison"

        if data.get("target_percent_basis_points") is None:
            return "Latency SLOs require target_percent_basis_points"

        if data.get("threshold_seconds") is None:
            return "Latency SLOs require threshold_seconds"

        return None

    if sli.sli_type == SLI_TYPE_INCIDENT_AVAILABILITY:
        if comparison != SLO_COMPARISON_PERCENT_GOOD_GTE:
            return "Availability SLOs must use percent_good_gte comparison"

        if data.get("target_percent_basis_points") is None:
            return "Availability SLOs require target_percent_basis_points"

        return None

    if sli.sli_type == SLI_TYPE_INCIDENT_COUNT:
        if comparison != SLO_COMPARISON_VALUE_LTE:
            return "Incident count SLOs must use value_lte comparison"

        if data.get("threshold_count") is None:
            return "Incident count SLOs require threshold_count"

        return None

    return f"Unsupported SLI type: {sli.sli_type}"


def _base_evaluation(slo, *, since, now):
    return {
        "slo_id": slo.id,
        "sli_id": slo.sli_id,
        "sli_type": slo.sli.sli_type,
        "status": STATUS_NO_DATA,
        "window": {
            "days": normalize_slo_window_days(slo.window_days),
            "since": serialize_utc_datetime(since),
            "until": serialize_utc_datetime(now),
        },
        "comparison": slo.comparison,
        "target_percent_basis_points": slo.target_percent_basis_points,
        "target_percent": _basis_points_to_percent(slo.target_percent_basis_points),
        "threshold_seconds": slo.threshold_seconds,
        "threshold_count": slo.threshold_count,
        "value_basis_points": None,
        "value_percent": None,
        "value_count": None,
        "good_count": 0,
        "total_count": 0,
        "bad_count": 0,
        "pending_count": 0,
        "downtime_seconds": None,
        "budget_seconds": None,
        "budget_consumed_seconds": None,
        "budget_remaining_seconds": None,
        "message": "No data",
        "details": {},
    }


def _alert_query_for_sli(sli, *, since):
    query = AlertGroup.select().where(
        (AlertGroup.service == sli.service_id)
        & (AlertGroup.first_seen_at >= since)
    )

    priority_scope = priority_scope_for_sli(sli)

    if priority_scope:
        query = query.where(AlertGroup.priority_slug.in_(priority_scope))

    if sli.severity:
        query = query.where(AlertGroup.severity == sli.severity)

    return query.order_by(AlertGroup.first_seen_at.asc(), AlertGroup.id.asc())


def priority_scope_for_sli(sli):
    configuration = sli.configuration or {}
    scope = configuration.get("priority_scope")

    if scope is None and sli.priority:
        scope = [sli.priority]

    if scope is None and sli.sli_type in (SLI_TYPE_INCIDENT_AVAILABILITY, SLI_TYPE_INCIDENT_COUNT):
        scope = DEFAULT_IMPACT_PRIORITY_SCOPE

    if isinstance(scope, str):
        scope = [scope]

    if not isinstance(scope, (list, tuple, set)):
        return []

    normalized = []

    for value in scope:
        value = str(value or "").strip().lower()

        if value in PRIORITY_VALUES and value not in normalized:
            normalized.append(value)

    return normalized


def _evaluate_latency_slo(slo, *, since, now, field):
    evaluation = _base_evaluation(slo, since=since, now=now)
    threshold = int(slo.threshold_seconds or 0)

    if threshold <= 0:
        evaluation.update({
            "status": STATUS_NO_DATA,
            "message": "Latency threshold is not configured",
        })
        return evaluation

    good = bad = pending = 0
    measured_seconds = []

    for group in _alert_query_for_sli(slo.sli, since=since):
        started_at = group.first_seen_at
        completed_at = getattr(group, field)

        if completed_at:
            elapsed = max(0, int((completed_at - started_at).total_seconds()))
            measured_seconds.append(elapsed)

            if elapsed <= threshold:
                good += 1
            else:
                bad += 1
        else:
            elapsed = max(0, int((now - started_at).total_seconds()))

            if elapsed > threshold:
                bad += 1
            elif slo.include_open_alerts:
                pending += 1

    total = good + bad
    value_basis_points = _ratio_basis_points(good, total) if total else None
    status = _percent_status(value_basis_points, slo.target_percent_basis_points, pending)
    label = "acknowledged" if field == "acknowledged_at" else "resolved"

    evaluation.update({
        "status": status,
        "value_basis_points": value_basis_points,
        "value_percent": _basis_points_to_percent(value_basis_points),
        "good_count": good,
        "total_count": total,
        "bad_count": bad,
        "pending_count": pending,
        "message": _latency_message(label, good, total, bad, pending, value_basis_points),
        "details": {
            "measured_seconds": measured_seconds[:100],
            "p95_seconds": _percentile(measured_seconds, 95),
            "max_seconds": max(measured_seconds) if measured_seconds else None,
        },
    })

    return evaluation


def _evaluate_availability_slo(slo, *, since, now):
    evaluation = _base_evaluation(slo, since=since, now=now)
    intervals = []

    for group in _alert_query_for_sli(slo.sli, since=since):
        start = max(group.first_seen_at, since)
        end = group.resolved_at or now

        if end <= since or start >= now:
            continue

        intervals.append((start, min(end, now)))

    merged = _merge_intervals(intervals)
    maintenance = _maintenance_intervals(slo.service, since=since, now=now) if slo.exclude_maintenance else []
    effective_downtime_intervals = merged

    if maintenance:
        effective_downtime_intervals = _subtract_intervals(merged, maintenance)

    downtime_seconds = _intervals_seconds(effective_downtime_intervals)
    downtime_windows = len(effective_downtime_intervals)

    window_seconds = max(1, int((now - since).total_seconds()))
    value_basis_points = max(0, min(10000, _ratio_basis_points(window_seconds - downtime_seconds, window_seconds)))
    budget_seconds = None
    budget_consumed_seconds = downtime_seconds
    budget_remaining_seconds = None

    if slo.target_percent_basis_points is not None:
        allowed_bad_ratio = max(0, 10000 - int(slo.target_percent_basis_points))
        budget_seconds = int(window_seconds * allowed_bad_ratio / 10000)
        budget_remaining_seconds = budget_seconds - budget_consumed_seconds

    status = _percent_status(value_basis_points, slo.target_percent_basis_points, 0)

    evaluation.update({
        "status": status,
        "value_basis_points": value_basis_points,
        "value_percent": _basis_points_to_percent(value_basis_points),
        "good_count": window_seconds - downtime_seconds,
        "total_count": window_seconds,
        "bad_count": downtime_windows,
        "downtime_seconds": downtime_seconds,
        "budget_seconds": budget_seconds,
        "budget_consumed_seconds": budget_consumed_seconds,
        "budget_remaining_seconds": budget_remaining_seconds,
        "message": f"{_basis_points_to_percent(value_basis_points)}% availability over {slo.window_days} days",
        "details": {
            "downtime_intervals": downtime_windows,
            "maintenance_excluded": bool(maintenance),
            "maintenance_intervals": len(maintenance),
        },
    })

    return evaluation


def _evaluate_incident_count_slo(slo, *, since, now):
    evaluation = _base_evaluation(slo, since=since, now=now)
    count = _alert_query_for_sli(slo.sli, since=since).count()
    target = int(slo.threshold_count or 0)
    status = STATUS_MET if count <= target else STATUS_BREACHED

    evaluation.update({
        "status": status,
        "value_count": count,
        "good_count": 1 if count <= target else 0,
        "total_count": 1,
        "bad_count": 0 if count <= target else 1,
        "message": f"{count} matching incidents over {slo.window_days} days",
    })

    return evaluation


def _persist_measurement(slo, evaluation):
    try:
        return services_repo.create_service_slo_measurement({
            "service": slo.service_id,
            "sli": slo.sli_id,
            "slo": slo.id,
            "window_start": datetime.fromisoformat(evaluation["window"]["since"].replace("Z", "+00:00")).replace(tzinfo=None),
            "window_end": datetime.fromisoformat(evaluation["window"]["until"].replace("Z", "+00:00")).replace(tzinfo=None),
            "status": evaluation["status"],
            "value_basis_points": evaluation.get("value_basis_points"),
            "value_count": evaluation.get("value_count"),
            "target_basis_points": evaluation.get("target_percent_basis_points"),
            "threshold_seconds": evaluation.get("threshold_seconds"),
            "threshold_count": evaluation.get("threshold_count"),
            "good_count": int(evaluation.get("good_count") or 0),
            "total_count": int(evaluation.get("total_count") or 0),
            "bad_count": int(evaluation.get("bad_count") or 0),
            "pending_count": int(evaluation.get("pending_count") or 0),
            "downtime_seconds": evaluation.get("downtime_seconds"),
            "budget_seconds": evaluation.get("budget_seconds"),
            "budget_consumed_seconds": evaluation.get("budget_consumed_seconds"),
            "budget_remaining_seconds": evaluation.get("budget_remaining_seconds"),
            "details": evaluation.get("details") or {},
        })
    except Exception:
        return None


def _maintenance_intervals(service, *, since, now):
    intervals = []
    windows = maintenance_repo.list_maintenance_windows(
        group_id=service.group_id,
        team_id=service.team_id,
        service_id=service.id,
        include_deleted=False,
        include_finished=True,
    )

    for window in windows:
        if not window.enabled or window.status == "cancelled":
            continue

        start = max(window.starts_at, since)
        end = min(window.ends_at, now)

        if start < end:
            intervals.append((start, end))

    return _merge_intervals(intervals)


def _merge_intervals(intervals):
    if not intervals:
        return []

    intervals = sorted(intervals, key=lambda item: item[0])
    merged = [intervals[0]]

    for start, end in intervals[1:]:
        last_start, last_end = merged[-1]

        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    return merged


def _subtract_intervals(intervals, exclusions):
    result = []

    for start, end in intervals:
        parts = [(start, end)]

        for ex_start, ex_end in exclusions:
            next_parts = []

            for part_start, part_end in parts:
                if ex_end <= part_start or ex_start >= part_end:
                    next_parts.append((part_start, part_end))
                    continue

                if ex_start > part_start:
                    next_parts.append((part_start, ex_start))

                if ex_end < part_end:
                    next_parts.append((ex_end, part_end))

            parts = next_parts

        result.extend(parts)

    return _merge_intervals(result)


def _intervals_seconds(intervals):
    return sum(max(0, int((end - start).total_seconds())) for start, end in intervals)


def _percent_status(value_basis_points, target_basis_points, pending):
    if value_basis_points is None or target_basis_points is None:
        return STATUS_NO_DATA

    if value_basis_points >= target_basis_points:
        return STATUS_AT_RISK if pending else STATUS_MET

    return STATUS_BREACHED


def _latency_message(label, good, total, bad, pending, value_basis_points):
    if total <= 0:
        if pending:
            return f"No completed {label} measurements yet; {pending} pending"
        return f"No {label} measurements"

    value = _basis_points_to_percent(value_basis_points)
    return f"{good}/{total} {label} within target ({value}%), {bad} breached, {pending} pending"


def _ratio_basis_points(numerator, denominator):
    if not denominator:
        return None

    return int(round((numerator / denominator) * 10000))


def _basis_points_to_percent(value):
    if value is None:
        return None

    return round(value / 100, 2)


def _percentile(values, percentile):
    if not values:
        return None

    values = sorted(values)
    index = int(round((percentile / 100) * (len(values) - 1)))
    return values[index]
