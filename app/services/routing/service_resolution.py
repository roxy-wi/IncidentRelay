from app.modules.db import services_repo
from app.services.routing.matcher.match_context import alert_rule_matches


def resolve_alert_service(route, alert_data):
    """Resolve affected service for an alert after route matched.

    Priority:
    1. route-specific ServiceMatchRule
    2. team-level ServiceMatchRule
    3. route.service fallback
    4. None
    """
    if not route or not route.team_id:
        return None

    rules = services_repo.list_enabled_match_rules(
        team_id=route.team_id,
        route_id=route.id,
    )

    for rule in rules:
        if alert_rule_matches(alert_data, rule, team=route.team, route=route, service=rule.service):
            return rule.service

    if getattr(route, "service_id", None):
        service = route.service
        if services_repo.is_service_active(service):
            return service

    return None


def get_effective_route_rotation(route, service=None):
    """Return route rotation with service default fallback."""
    if route and getattr(route, "rotation_id", None):
        return route.rotation

    if service and getattr(service, "default_rotation_id", None):
        return service.default_rotation

    return None


def get_effective_escalation_policy(route, service=None):
    """Return route escalation policy with service default fallback."""
    if route and getattr(route, "escalation_policy_id", None):
        return route.escalation_policy

    if service and getattr(service, "default_escalation_policy_id", None):
        return service.default_escalation_policy

    return None
