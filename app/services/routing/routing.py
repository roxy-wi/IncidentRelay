from app.modules.db import routes_repo, teams_repo
from app.services.routing.matcher.match_context import alert_rule_matches


def get_active_team_by_slug(team_slug):
    """
    Return an active team by slug only if its group is active too.
    """

    if not team_slug:
        return None

    team = teams_repo.get_team_by_slug(team_slug)

    if not team:
        return None

    if not team.active:
        return None

    if team.group and not team.group.active:
        return None

    return team


def is_route_active(route):
    """
    Return True when the route, team and group are active.
    """

    if not route or not route.enabled:
        return False

    if not route.team or not route.team.active:
        return False

    if route.team.group and not route.team.group.active:
        return False

    return True


def find_route_for_alert(alert_data):
    """
    Find the route that should receive an alert.

    Route intake token has priority for selecting a route, but route matchers
    still work as an allow-list filter. This prevents unwanted alerts from
    being accepted into a route even when the request uses this route token.
    """
    forced_route_id = alert_data.get("forced_route_id")

    if forced_route_id:
        route = routes_repo.get_route(forced_route_id)

        if not is_route_active(route):
            alert_data["routing_error"] = "route from intake token is disabled or inactive"
            return None

        if route.source != alert_data["source"]:
            alert_data["routing_error"] = (
                f"route source '{route.source}' does not match alert source "
                f"'{alert_data['source']}'"
            )
            return None

        if not alert_rule_matches(alert_data, route, team=route.team, route=route):
            alert_data["routing_error"] = "alert does not match route matchers"
            return None

        return route

    forced_team_id = alert_data.get("forced_team_id")

    if forced_team_id:
        routes = routes_repo.list_routes(
            team_id=forced_team_id,
            enabled_only=True,
            source=alert_data["source"],
            active_only=True,
        )
    else:
        team_slug = alert_data.get("team_slug")

        if team_slug:
            team = get_active_team_by_slug(team_slug)

            if not team:
                alert_data["routing_error"] = (
                    f"team '{team_slug}' was not found or is inactive"
                )
                return None

            routes = routes_repo.list_routes(
                team_id=team.id,
                enabled_only=True,
                source=alert_data["source"],
                active_only=True,
            )
        else:
            routes = routes_repo.list_routes(
                enabled_only=True,
                source=alert_data["source"],
                active_only=True,
            )

    for route in routes:
        if alert_rule_matches(alert_data, route, team=route.team, route=route):
            return route

    alert_data["routing_error"] = "no enabled route matched alert labels"
    return None


DEFAULT_ALERT_GROUP_BY = ()


def _normalize_group_by(value):
    """Return a clean list of configured grouping fields.

    Empty, null and legacy non-array values mean that explicit grouping is
    disabled. This avoids accidentally merging unrelated alerts when the route
    stores an empty object such as {}.
    """

    if not isinstance(value, list):
        return []

    result = []

    for item in value:
        name = str(item or "").strip()

        if name:
            result.append(name)

    return result


def _fallback_group_key_value(alert_data):
    """Return a per-alert fallback value used when grouping is incomplete."""

    return (
        alert_data.get("dedup_key")
        or alert_data.get("external_id")
        or alert_data.get("fingerprint")
        or alert_data.get("title")
        or alert_data.get("message")
        or ""
    )


def _normalize_group_key_value(value):
    if value is None:
        return ""

    if isinstance(value, bool):
        return "true" if value else "false"

    return str(value).strip()


def _get_nested_value(data, path):
    current = data

    for part in path.split("."):
        if not isinstance(current, dict):
            return None

        current = current.get(part)

        if current is None:
            return None

    return current


def get_alert_group_field_value(name, alert_data, route=None, service=None):
    """Return a value used for alert grouping.

    Supported forms:
    - alertname
    - severity
    - instance
    - labels.instance
    - annotations.summary
    - payload.commonLabels.alertname
    - source
    - team_id
    - route_id
    - service_id
    """

    labels = alert_data.get("labels") or {}
    annotations = alert_data.get("annotations") or {}
    payload = alert_data.get("payload") or {}

    if name.startswith("labels."):
        return _get_nested_value(labels, name[len("labels."):])

    if name.startswith("annotations."):
        return _get_nested_value(annotations, name[len("annotations."):])

    if name.startswith("payload."):
        return _get_nested_value(payload, name[len("payload."):])

    if name == "source":
        return alert_data.get("source")

    if name == "team_id":
        return getattr(route, "team_id", None) or alert_data.get("team_id")

    if name == "team":
        team = getattr(route, "team", None)
        return getattr(team, "slug", None) or getattr(route, "team_id", None)

    if name == "route_id":
        return getattr(route, "id", None) or alert_data.get("forced_route_id")

    if name == "route":
        return getattr(route, "name", None) or getattr(route, "id", None)

    if name == "service_id":
        return (
            getattr(service, "id", None)
            or getattr(route, "service_id", None)
            or alert_data.get("service_id")
        )

    if name == "service":
        return (
            getattr(service, "slug", None)
            or getattr(service, "name", None)
            or getattr(service, "id", None)
        )

    # Backward-compatible short syntax:
    # "alertname" means labels.alertname first.
    if name in labels:
        return labels.get(name)

    if name in annotations:
        return annotations.get(name)

    if name in alert_data:
        return alert_data.get(name)

    return None


def get_effective_group_by(route):
    """Return explicitly configured grouping fields.

    An empty configuration intentionally disables cross-alert grouping. Repeated
    occurrences of the same alert still share a group through dedup_key fallback
    in build_group_key().
    """

    group_by = _normalize_group_by(getattr(route, "group_by", None))

    if group_by:
        return group_by

    return list(DEFAULT_ALERT_GROUP_BY)


def build_group_key(route, alert_data, service=None):
    """Build stable alert group key.

    The key always includes routing scope, so different routes/services do not
    accidentally merge alerts with the same labels.
    """

    scope_parts = [
        ("source", alert_data.get("source")),
        ("team_id", getattr(route, "team_id", None) or alert_data.get("team_id")),
        ("route_id", getattr(route, "id", None) or alert_data.get("forced_route_id")),
        (
            "service_id",
            getattr(service, "id", None)
            or getattr(route, "service_id", None)
            or alert_data.get("service_id"),
        ),
    ]

    group_parts = []
    group_by = get_effective_group_by(route)
    has_missing_group_value = False

    for name in group_by:
        value = get_alert_group_field_value(
            name,
            alert_data,
            route=route,
            service=service,
        )

        if not _normalize_group_key_value(value):
            has_missing_group_value = True

        group_parts.append((name, value))

    if not group_by:
        group_parts.append(("dedup_key", _fallback_group_key_value(alert_data)))
    elif has_missing_group_value:
        group_parts.append(("fallback_dedup_key", _fallback_group_key_value(alert_data)))

    parts = scope_parts + group_parts

    return "|".join(
        f"{name}={_normalize_group_key_value(value)}"
        for name, value in parts
    )
