from app.services.routing.matcher.matchers import match_alert


TEAM_FIELDS = (
    "id",
    "name",
    "slug",
)

ROUTE_FIELDS = (
    "id",
    "name",
    "slug",
    "source",
)

SERVICE_FIELDS = (
    "id",
    "name",
    "slug",
    "service_type",
    "environment",
    "criticality",
    "tier",
    "status",
)


def _get_value(resource, *names, default=None):
    if resource is None:
        return default

    for name in names:
        if isinstance(resource, dict):
            value = resource.get(name)
        else:
            value = getattr(resource, name, None)

        if value is not None:
            return value

    return default


def _get_mapping(resource, *names):
    for name in names:
        value = _get_value(resource, name)

        if isinstance(value, dict) and value:
            return dict(value)

    return {}


def _resource_data(resource, fields):
    if not resource:
        return None

    return {
        field: _get_value(resource, field)
        for field in fields
    }


def build_alert_match_context(
    alert,
    *,
    team=None,
    route=None,
    service=None,
    priority=None,
):
    """Build one normalized context for all alert-based matchers."""
    labels = _get_mapping(alert, "labels", "common_labels")
    payload = _get_mapping(alert, "payload", "payload_summary")

    annotations = _get_mapping(alert, "annotations")
    if not annotations:
        raw_annotations = payload.get("annotations")
        annotations = (
            dict(raw_annotations)
            if isinstance(raw_annotations, dict)
            else {}
        )

    team = team or _get_value(alert, "team")
    route = route or _get_value(alert, "route")
    service = service or _get_value(alert, "service")

    severity = _get_value(alert, "severity")
    status = _get_value(alert, "status", default="firing")
    source = _get_value(alert, "source")

    derived_labels = {
        "severity": severity,
        "status": status,
        "source": source,
        "priority": priority,
        "team_id": _get_value(alert, "team_id")
        or _get_value(team, "id"),
        "route_id": _get_value(alert, "route_id")
        or _get_value(route, "id"),
        "service_id": _get_value(alert, "service_id")
        or _get_value(service, "id"),
    }

    for key, value in derived_labels.items():
        if value is not None:
            labels[key] = value

    return {
        "id": _get_value(alert, "id"),
        "source": source,
        "title": _get_value(alert, "title"),
        "message": _get_value(alert, "message"),
        "severity": severity,
        "priority": priority,
        "status": status,
        "labels": labels,
        "annotations": annotations,
        "payload": payload,
        "team": _resource_data(team, TEAM_FIELDS),
        "route": _resource_data(route, ROUTE_FIELDS),
        "service": _resource_data(service, SERVICE_FIELDS),
    }


def alert_rule_matches(
    alert,
    rule,
    *,
    team=None,
    route=None,
    service=None,
    priority=None,
):
    """Match preset and local rule conditions using AND semantics."""
    context = build_alert_match_context(
        alert,
        team=team,
        route=route,
        service=service,
        priority=priority,
    )

    preset_id = getattr(rule, "matcher_preset_id", None)

    if preset_id:
        preset = rule.matcher_preset

        if not preset or preset.deleted or not preset.enabled:
            return False

        if not match_alert(context, preset.matchers or {}):
            return False

    return match_alert(context, rule.matchers or {})
