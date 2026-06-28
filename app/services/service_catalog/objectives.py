from datetime import datetime, timedelta

from app.modules.db.models import AlertGroup
from app.services.serializers import serialize_utc_datetime


DEFAULT_DAYS = 30
MAX_DAYS = 365


def normalize_objective_window_days(days):
    return max(1, min(int(days or DEFAULT_DAYS), MAX_DAYS))


def evaluate_service_objectives(slos, *, days=DEFAULT_DAYS, now=None):
    """Evaluate service objectives against alert-group history.

    This is intentionally SLO-lite: ack/resolve targets are measured from
    AlertGroup.first_seen_at to acknowledged_at/resolved_at. Availability
    targets are returned as configured but not measured yet; they will become
    measurable once we introduce status-window accounting.
    """
    now = now or datetime.utcnow()
    days = normalize_objective_window_days(days)
    since = now - timedelta(days=days)

    return {
        slo.id: evaluate_service_objective(slo, since=since, now=now, days=days)
        for slo in slos
    }


def evaluate_service_objective(slo, *, since, now, days):
    query = _objective_alert_query(slo, since=since)
    groups = list(query)

    ack = _latency_target_result(
        groups,
        target_seconds=slo.ack_target_seconds,
        end_field="acknowledged_at",
        now=now,
    )
    resolve = _latency_target_result(
        groups,
        target_seconds=slo.resolve_target_seconds,
        end_field="resolved_at",
        now=now,
    )
    availability = _availability_target_result(slo)
    status = _combined_status([ack, resolve, availability])

    return {
        "status": status,
        "window": {
            "days": days,
            "since": serialize_utc_datetime(since),
            "until": serialize_utc_datetime(now),
        },
        "scope": {
            "severity": slo.severity,
        },
        "alerts_count": len(groups),
        "ack": ack,
        "resolve": resolve,
        "availability": availability,
    }


def _objective_alert_query(slo, *, since):
    query = AlertGroup.select().where(
        AlertGroup.service == slo.service_id,
        AlertGroup.first_seen_at >= since,
    )

    if slo.severity:
        query = query.where(AlertGroup.severity == slo.severity)

    return query.order_by(AlertGroup.first_seen_at.asc(), AlertGroup.id.asc())


def _latency_target_result(groups, *, target_seconds, end_field, now):
    if not target_seconds:
        return None

    total = len(groups)
    met = 0
    breached = 0
    pending = 0
    durations = []

    for group in groups:
        started_at = group.first_seen_at
        ended_at = getattr(group, end_field)

        if not started_at:
            continue

        if ended_at:
            duration = max(0, int((ended_at - started_at).total_seconds()))
            durations.append(duration)

            if duration <= target_seconds:
                met += 1
            else:
                breached += 1

            continue

        elapsed = max(0, int((now - started_at).total_seconds()))

        if elapsed > target_seconds:
            breached += 1
        else:
            pending += 1

    measured = met + breached
    met_percentage = round((met / measured) * 100, 2) if measured else None

    return {
        "target_seconds": target_seconds,
        "total": total,
        "measured": measured,
        "met": met,
        "breached": breached,
        "pending": pending,
        "met_percentage": met_percentage,
        "avg_seconds": _average(durations),
        "p95_seconds": _percentile(durations, 95),
        "status": _latency_status(met=met, breached=breached, pending=pending),
    }


def _availability_target_result(slo):
    if slo.availability_target_basis_points is None:
        return None

    return {
        "target_basis_points": slo.availability_target_basis_points,
        "target_percentage": round(slo.availability_target_basis_points / 100, 2),
        "measured_percentage": None,
        "status": "unknown",
        "message": "Availability measurement is not available yet.",
    }


def _latency_status(*, met, breached, pending):
    if breached:
        return "breached"

    if pending:
        return "at_risk"

    if met:
        return "met"

    return "unknown"


def _combined_status(results):
    statuses = [result["status"] for result in results if result]

    if not statuses:
        return "unknown"

    if "breached" in statuses:
        return "breached"

    if "at_risk" in statuses:
        return "at_risk"

    if all(status == "met" for status in statuses):
        return "met"

    return "unknown"


def _average(values):
    if not values:
        return None

    return int(sum(values) / len(values))


def _percentile(values, percentile):
    if not values:
        return None

    values = sorted(values)
    index = int(round((percentile / 100) * (len(values) - 1)))
    return values[index]
