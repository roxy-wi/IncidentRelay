from datetime import datetime, timedelta, timezone

from flask import jsonify, request
from peewee import DoesNotExist

from app.views.services.blueprint import services_bp
from app.modules.db import maintenance_repo, services_repo
from app.modules.db.models import AlertGroup
from app.services.rbac import require_team_read, current_user
from app.services.serializers import serialize_utc_datetime, serialize_maintenance_window, serialize_service, \
    serialize_service_readiness_state, serialize_service_link, serialize_service_runbook, serialize_service_dependency, \
    serialize_service_readiness, serialize_service_slo
from app.services.service_catalog import readiness as service_readiness
from app.services.service_catalog.impact import build_single_service_impact_v2
from app.services.service_catalog.objectives import evaluate_service_objectives
from app.services.service_catalog.timeline import list_service_events, serialize_service_event, build_next_cursor
from app.services.validation import make_error_response


class ServiceDetailsImpactQuery:
    include_disabled = True
    include_explanation = True
    include_root_causes = True
    include_blast_radius = True
    include_paths = True
    max_depth = 5


def _service_open_statuses():
    return ("firing", "acknowledged")


def _service_alert_group_query(service_id):
    return AlertGroup.select().where(AlertGroup.service == service_id)


def _count_alert_groups(service_id, *conditions):
    query = _service_alert_group_query(service_id)

    for condition in conditions:
        query = query.where(condition)

    return query.count()


def _service_alert_summary(service_id, *, days):
    since = datetime.utcnow() - timedelta(days=days)

    base_query = _service_alert_group_query(service_id)
    recent_query = base_query.where(AlertGroup.last_seen_at >= since)

    last_group = (
        base_query
        .order_by(AlertGroup.last_seen_at.desc(), AlertGroup.id.desc())
        .first()
    )

    open_statuses = _service_open_statuses()

    by_status = {
        "firing": _count_alert_groups(service_id, AlertGroup.status == "firing"),
        "acknowledged": _count_alert_groups(service_id, AlertGroup.status == "acknowledged"),
        "resolved": _count_alert_groups(service_id, AlertGroup.status == "resolved"),
    }

    by_severity = {}

    for severity in ("critical", "high", "warning", "info", "unknown"):
        if severity == "unknown":
            by_severity[severity] = _count_alert_groups(
                service_id,
                AlertGroup.severity.is_null(True),
            )
        else:
            by_severity[severity] = _count_alert_groups(
                service_id,
                AlertGroup.severity == severity,
            )

    return {
        "window_days": days,
        "total": base_query.count(),
        "recent": recent_query.count(),
        "open": _count_alert_groups(
            service_id,
            AlertGroup.status.in_(open_statuses),
        ),
        "firing": by_status["firing"],
        "acknowledged": by_status["acknowledged"],
        "resolved": by_status["resolved"],
        "critical_open": _count_alert_groups(
            service_id,
            AlertGroup.status.in_(open_statuses),
            AlertGroup.severity == "critical",
        ),
        "last_seen_at": serialize_utc_datetime(last_group.last_seen_at) if last_group else None,
        "by_status": by_status,
        "by_severity": by_severity,
    }


def _readable_dependency_rows(dependencies, *, target_side):
    """Filter cross-team dependency rows by read permission.

    target_side=True checks depends_on_service team.
    target_side=False checks source service team.
    """
    rows = []

    for dependency in dependencies:
        target_service = (
            dependency.depends_on_service
            if target_side
            else dependency.service
        )

        if not target_service:
            continue

        error = require_team_read(target_service.team_id)

        if not error:
            rows.append(dependency)

    return rows


def _service_maintenance_windows(service):
    windows = maintenance_repo.list_maintenance_windows(
        group_id=service.group_id,
        team_id=service.team_id,
        service_id=service.id,
        include_deleted=False,
        include_finished=False,
    )

    return [
        serialize_maintenance_window(window)
        for window in windows
    ]


def _service_analytics_payload(
    service,
    *,
    days,
    alert_summary,
    timeline,
    impact=None,
):
    until = datetime.utcnow()
    since = until - timedelta(days=days)

    impact = impact or {}
    blast_radius = impact.get("blast_radius") or {}

    return {
        "version": 1,
        "window": {
            "days": days,
            "since": serialize_utc_datetime(since),
            "until": serialize_utc_datetime(until),
        },
        "widgets": {
            "alert_volume": {
                "total": alert_summary["total"],
                "recent": alert_summary["recent"],
                "open": alert_summary["open"],
                "critical_open": alert_summary["critical_open"],
            },
            "status": {
                "current": service.status,
                "source": service.status_source,
                "updated_at": serialize_utc_datetime(service.status_updated_at),
                "changes": sum(1 for event in timeline if event.category == "status"),
            },
            "impact": {
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
            },
        },
        "breakdowns": {
            "alerts_by_status": alert_summary["by_status"],
            "alerts_by_severity": alert_summary["by_severity"],
        },
        "series": [],
        "extensions": {},
    }


def _service_details_payload(service, *, days):
    alert_summary = _service_alert_summary(service.id, days=days)
    timeline = list_service_events(service.id, limit=50)
    readiness_state, readiness_evaluations, readiness_results = (
        service_readiness.load_service_readiness_batch(service.id)
    )

    upstream_dependencies = _readable_dependency_rows(
        services_repo.list_service_dependencies(service_id=service.id),
        target_side=True,
    )
    downstream_dependencies = _readable_dependency_rows(
        services_repo.list_downstream_service_dependencies(service_id=service.id),
        target_side=False,
    )

    links = services_repo.list_service_links(service_id=service.id)
    runbooks = services_repo.list_service_runbooks(service_id=service.id)
    objectives = services_repo.list_service_slos(
        service_id=service.id,
        include_disabled=True,
    )
    objective_evaluations = evaluate_service_objectives(objectives, days=days)

    impact = build_single_service_impact_v2(
        service.id,
        ServiceDetailsImpactQuery(),
        team_ids=[service.team_id],
    )

    return {
        "service": serialize_service(
            service,
            current_user(),
            readiness_state=readiness_state,
        ),
        "summary": {
            "alerts": alert_summary,
            "maintenance_windows": len(_service_maintenance_windows(service)),
            "links": len(links),
            "runbooks": len(runbooks),
            "upstream_dependencies": len(upstream_dependencies),
            "downstream_dependencies": len(downstream_dependencies),
            "timeline_events": len(timeline),
            "objectives": len(objectives),
            "readiness": serialize_service_readiness_state(readiness_state),
        },
        "maintenance_windows": _service_maintenance_windows(service),
        "links": [
            serialize_service_link(link, current_user())
            for link in links
        ],
        "runbooks": [
            serialize_service_runbook(runbook, current_user())
            for runbook in runbooks
        ],
        "objectives": [
            serialize_service_slo(
                objective,
                current_user(),
                evaluation=objective_evaluations.get(objective.id),
            )
            for objective in objectives
        ],
        "dependencies": {
            "upstream": [
                serialize_service_dependency(dependency, current_user())
                for dependency in upstream_dependencies
            ],
            "downstream": [
                serialize_service_dependency(dependency, current_user())
                for dependency in downstream_dependencies
            ],
        },
        "timeline": [serialize_service_event(event) for event in timeline],
        "analytics": _service_analytics_payload(
            service,
            days=days,
            alert_summary=alert_summary,
            timeline=timeline,
            impact=impact,
        ),
        "impact": impact,
        "readiness": serialize_service_readiness(
            readiness_state,
            evaluations=readiness_evaluations,
            results_by_evaluation=readiness_results,
        ),
    }


@services_bp.route("/<int:service_id>/details", methods=["GET"])
def get_service_details(service_id):
    """Return expanded service details for the service details panel."""
    try:
        service = services_repo.get_service(service_id)
    except DoesNotExist:
        return make_error_response(
            "service_not_found",
            "Service was not found",
            404,
            service_id=service_id,
        )

    error = require_team_read(service.team_id)
    if error:
        return error

    days = _service_details_days_from_request()

    return jsonify(
        _service_details_payload(
            service,
            days=days,
        )
    )


@services_bp.route("/<int:service_id>/timeline", methods=["GET"])
def get_service_timeline(service_id):
    try:
        service = services_repo.get_service(service_id)
    except DoesNotExist:
        return make_error_response(
            "service_not_found",
            "Service was not found",
            404,
            service_id=service_id,
        )

    error = require_team_read(service.team_id)

    if error:
        return error

    limit = max(1, min(request.args.get("limit", default=50, type=int), 200))
    category = request.args.get("category")
    event_type = request.args.get("event_type")
    before_id = request.args.get("before_id", type=int)
    before, error = _parse_service_timeline_datetime(request.args.get("before"))

    if error:
        return error

    events = list_service_events(service.id, category=category, event_type=event_type, limit=limit, before=before, before_id=before_id)

    return jsonify({
        "items": [serialize_service_event(event) for event in events],
        "next_cursor": build_next_cursor(events, limit),
    })


def _parse_service_timeline_datetime(value):
    if not value:
        return None, None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None, make_error_response("timeline_before_invalid", "Timeline before must be a valid ISO 8601 datetime", 400)

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

    return parsed, None


def _service_details_days_from_request():
    days = request.args.get("days", default=SERVICE_DETAILS_DEFAULT_DAYS, type=int)
    return max(1, min(days or SERVICE_DETAILS_DEFAULT_DAYS, SERVICE_DETAILS_MAX_DAYS))


SERVICE_DETAILS_DEFAULT_DAYS = 30
SERVICE_DETAILS_MAX_DAYS = 365
