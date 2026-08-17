from peewee import JOIN

from app.modules.db.models import Alert, AlertRoute, Service, Team
from app.services.routing.matcher.match_context import build_alert_match_context
from app.services.routing.matcher.matchers import (
    match_alert,
    validate_matcher_regexes,
)


DEFAULT_SCAN_LIMIT = 200
MAX_SCAN_LIMIT = 500
DEFAULT_RESULT_LIMIT = 20
MAX_RESULT_LIMIT = 100


def _serialize_preview_alert(alert):
    route = alert.route if getattr(alert, "route_id", None) else None
    service = alert.service if getattr(alert, "service_id", None) else None

    return {
        "id": alert.id,
        "group_id": alert.group_id,
        "title": alert.title,
        "source": alert.source,
        "severity": alert.severity,
        "status": alert.status,
        "priority": alert.priority_slug,
        "labels": alert.labels or {},
        "route_id": route.id if route else None,
        "route_name": route.name if route else None,
        "service_id": service.id if service else None,
        "service_name": service.name if service else None,
        "last_seen_at": alert.last_seen_at.isoformat() if alert.last_seen_at else None,
    }


def build_matcher_preview(
    *,
    team_id,
    matchers,
    route_id=None,
    service_id=None,
    preset=None,
    scan_limit=DEFAULT_SCAN_LIMIT,
    result_limit=DEFAULT_RESULT_LIMIT,
):
    """Return recent alerts matching preset and local matcher conditions."""
    scan_limit = max(1, min(int(scan_limit), MAX_SCAN_LIMIT))
    result_limit = max(1, min(int(result_limit), MAX_RESULT_LIMIT))

    query = (
        Alert
        .select(Alert, Team, AlertRoute, Service)
        .join(Team, JOIN.LEFT_OUTER)
        .switch(Alert)
        .join(AlertRoute, JOIN.LEFT_OUTER)
        .switch(Alert)
        .join(Service, JOIN.LEFT_OUTER)
        .where(Alert.team == team_id)
    )

    if route_id:
        query = query.where(Alert.route == route_id)

    if service_id:
        query = query.where(Alert.service == service_id)

    alerts = list(
        query
        .order_by(Alert.last_seen_at.desc(), Alert.id.desc())
        .limit(scan_limit)
    )

    preset_matchers = (preset.matchers or {}) if preset else {}
    validate_matcher_regexes(preset_matchers)
    validate_matcher_regexes(matchers or {})
    matched_count = 0
    items = []

    for alert in alerts:
        context = build_alert_match_context(alert, priority=alert.priority_slug)

        if preset and not match_alert(context, preset_matchers):
            continue

        if not match_alert(context, matchers or {}):
            continue

        matched_count += 1

        if len(items) < result_limit:
            items.append(_serialize_preview_alert(alert))

    return {
        "team_id": team_id,
        "route_id": route_id,
        "service_id": service_id,
        "matcher_preset_id": preset.id if preset else None,
        "sample_size": len(alerts),
        "scan_limit": scan_limit,
        "result_limit": result_limit,
        "matched_count": matched_count,
        "truncated": matched_count > len(items),
        "items": items,
    }
