from app.modules.db import routes_repo, teams_repo
from app.services.matchers import match_alert


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

    Route intake token has priority. When a request is authenticated by a route
    token, the alert is forced into that route. Labels cannot move it to another
    route.
    """

    forced_route_id = alert_data.get("forced_route_id")

    if forced_route_id:
        route = routes_repo.get_route(forced_route_id)

        if not is_route_active(route):
            alert_data["routing_error"] = "route from intake token is disabled or inactive"
            return None

        if route.source != alert_data["source"]:
            alert_data["routing_error"] = f"route source '{route.source}' does not match alert source '{alert_data['source']}'"
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
                alert_data["routing_error"] = f"team '{team_slug}' was not found or is inactive"
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
        if match_alert(alert_data, route.matchers or {}):
            return route

    alert_data["routing_error"] = "no enabled route matched alert labels"
    return None


def build_group_key(route, alert_data):
    """
    Build alert group key from route group_by labels.
    """

    group_by = route.group_by if route and route.group_by else []

    if not group_by:
        return alert_data["dedup_key"]

    labels = alert_data.get("labels") or {}
    return "|".join(f"{name}={labels.get(name, '')}" for name in group_by)
