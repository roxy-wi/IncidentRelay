from app.api.openapi.common import ERROR_SCHEMA, query_param, response
from app.api.openapi.endpoints.incidents import (
    INCIDENT_RESPONDER_SCHEMA,
    INCIDENT_SUMMARY_SCHEMA,
    date_time_schema,
)


NOTIFICATION_CENTER_ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {
            "type": "string",
            "example": "accept",
        },
        "label": {
            "type": "string",
            "example": "Accept",
        },
        "status": {
            "type": "string",
            "enum": ["accepted", "declined"],
            "example": "accepted",
        },
        "method": {
            "type": "string",
            "example": "PUT",
        },
        "url": {
            "type": "string",
            "example": "/api/incidents/14784/responders/15",
        },
    },
}

NOTIFICATION_CENTER_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {
            "type": "string",
            "example": "responder-request-15",
        },
        "type": {
            "type": "string",
            "enum": ["responder_request"],
            "example": "responder_request",
        },
        "title": {
            "type": "string",
            "example": "Responder requested",
        },
        "body": {
            "type": "string",
            "example": "Admin: Please help with database checks.",
        },
        "created_at": date_time_schema("Notification creation timestamp in UTC."),
        "expires_at": date_time_schema("Notification expiration timestamp in UTC."),
        "url": {
            "type": "string",
            "nullable": True,
            "example": "/alerts/14784",
        },
        "incident_id": {
            "type": "integer",
            "nullable": True,
            "example": 14784,
        },
        "incident": INCIDENT_SUMMARY_SCHEMA,
        "responder": INCIDENT_RESPONDER_SCHEMA,
        "actions": {
            "type": "array",
            "items": NOTIFICATION_CENTER_ACTION_SCHEMA,
        },
    },
}

NOTIFICATION_CENTER_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "unread_count": {
            "type": "integer",
            "description": (
                "Current number of actionable notification center items. "
                "For the first implementation this is the number of pending "
                "responder requests visible to the current user."
            ),
            "example": 1,
        },
        "items": {
            "type": "array",
            "items": NOTIFICATION_CENTER_ITEM_SCHEMA,
        },
    },
}


def tags():
    """Return OpenAPI tags."""
    return [
        {
            "name": "notification-center",
            "description": (
                "Current user's in-app notification center. "
                "The first implementation exposes actionable pending "
                "incident responder requests."
            ),
        }
    ]


def paths():
    """Return OpenAPI paths for notification center endpoints."""
    return {
        "/api/notification-center": {
            "get": {
                "tags": ["notification-center"],
                "summary": "List notification center items",
                "description": (
                    "Returns actionable notification center items for the "
                    "current user. Pending incident responder requests are "
                    "shown until they are accepted, declined, resolved or expired."
                ),
                "operationId": "listNotificationCenterItems",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    query_param(
                        "limit",
                        "Maximum number of items to return.",
                        {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 20,
                        },
                    ),
                ],
                "responses": {
                    "200": response(
                        "Notification center items returned.",
                        NOTIFICATION_CENTER_RESPONSE_SCHEMA,
                    ),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                },
            },
        },
    }
