from app.api.openapi.endpoints import (
    alerts,
    auth,
    calendar,
    channels,
    integrations,
    profile,
    rotations,
    routes,
    silences,
    teams,
    users,
    version,
)
from app.version import get_service_version


ENDPOINT_MODULES = [
    version,
    auth,
    teams,
    users,
    rotations,
    calendar,
    channels,
    routes,
    alerts,
    silences,
    integrations,
    profile
]


def build_openapi_spec():
    """
    Build the OpenAPI specification from endpoint modules.
    """

    paths = {}
    tags = []

    for module in ENDPOINT_MODULES:
        paths.update(module.paths())
        tags.extend(module.tags())

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "IncidentRelay API",
            "version": get_service_version(),
            "description": (
                "API-first on-call management service. The API manages teams, users, "
                "rotations, alert routes, notification channels, silences, "
                "incoming webhooks and alert acknowledgement workflow."
            ),
        },
        "tags": tags,
        "paths": paths,
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "JWT access token, regular API token, or channel alert intake token. Use: Authorization: Bearer <token>.",
                }
            }
        },
    }
