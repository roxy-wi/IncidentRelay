"""Global, database-backed system settings."""

from app.api.openapi.common import json_body, response
from app.api.schemas.system_settings import settings_properties

TAG = "System settings"


def tags():
    return [{"name": TAG, "description": "Installation-wide settings managed by global administrators."}]


def paths():
    properties = settings_properties()
    settings = {"type": "object", "additionalProperties": False, "properties": properties}
    read = {
        "tags": [TAG],
        "summary": "Read system settings",
        "description": (
            "Requires a global administrator JWT or a personal API token with system-settings:read (or *). "
            "Group- and Team-bound tokens and machine credentials are rejected. "
            "Legacy resources:* scopes do not grant access. Authentication remains mandatory when global API auth is disabled. "
            "No query parameters are accepted."
        ),
        "security": [{"bearerAuth": []}],
        "responses": {
            "200": response("Current settings", {**settings, "required": list(properties)}),
            "400": response("Invalid request"),
            "401": response("Authenticated administrator required"),
            "403": response("Access denied"),
        },
    }
    return {
        "/api/admin/system-settings": {
            "get": read,
            "patch": {
                **read,
                "summary": "Update the supplied settings and audit the changes",
                "description": (
                    "Requires a global administrator JWT or a personal API token with system-settings:write (or *). "
                    "Group- and Team-bound tokens and machine credentials are rejected; resources:* is insufficient. "
                    "Authentication remains mandatory when global API auth is disabled. Send only changed fields. "
                    "The audit records both user and API-token identity. "
                    "The base retry delay must not exceed the maximum after the edit. "
                    "Each scheduler checks for a new worker interval every five seconds."
                ),
                "requestBody": json_body("Settings to change", {**settings, "minProperties": 1}),
            },
        }
    }
