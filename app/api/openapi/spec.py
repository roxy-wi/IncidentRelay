from app.api.openapi.endpoints import (
    alerts,
    auth,
    browser_push,
    business_services,
    calendar,
    channels,
    escalation_policies,
    groups,
    heartbeats,
    incidents,
    integrations,
    notification_center,
    orchestrations,
    notification_rules,
    notification_policies,
    oncall_health,
    profile,
    rotations,
    routes,
    services,
    service_catalog,
    silences,
    sso,
    teams,
    users,
    version,
    maintenance_windows,
    matchers,
)
from app.version import get_service_version


ENDPOINT_MODULES = [
    version,
    auth,
    teams,
    users,
    rotations,
    oncall_health,
    calendar,
    channels,
    routes,
    heartbeats,
    matchers,
    escalation_policies,
    notification_policies,
    alerts,
    incidents,
    silences,
    integrations,
    profile,
    browser_push,
    notification_rules,
    notification_center,
    orchestrations,
    groups,
    sso,
    services,
    business_services,
    service_catalog,
    maintenance_windows,
]


def build_openapi_spec():
    """Build the OpenAPI specification from endpoint modules."""
    paths = {}
    tags = []
    schemas = {}

    for module in ENDPOINT_MODULES:
        paths.update(module.paths())
        tags.extend(module.tags())
        component_builder = getattr(module, "components", None)
        if component_builder is not None:
            schemas.update(component_builder())

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "IncidentRelay API",
            "version": get_service_version(),
            "description": (
                "API-first on-call management service. The API manages teams, "
                "users, rotations, alert routes, services, notification channels, "
                "profile notification rules, browser push subscriptions, silences, "
                "incoming webhooks and alert acknowledgement workflow."
            ),
        },
        "tags": tags,
        "paths": paths,
        "components": {
            "schemas": schemas,
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": (
                        "JWT access token, regular API token, or channel alert "
                        "intake token. Use: Authorization: Bearer <token>."
                    ),
                },
                "basicRouteAuth": {
                    "type": "http",
                    "scheme": "basic",
                    "description": (
                        "Provider-specific route authentication. Azure Monitor "
                        "webhooks use username incidentrelay and the route intake "
                        "token as the HTTP Basic password."
                    ),
                },
            }
        },
    }
