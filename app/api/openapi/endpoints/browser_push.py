from app.api.openapi.common import ERROR_SCHEMA, json_body, path_param, response


BROWSER_PUSH_PUBLIC_CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "enabled": {
            "type": "boolean",
            "description": "Whether browser push is enabled on this IncidentRelay instance.",
            "example": True,
        },
        "public_key": {
            "type": "string",
            "nullable": True,
            "description": "VAPID public key for PushManager.subscribe().",
            "example": "BExampleVapidPublicKeyBase64Url...",
        },
    },
}


BROWSER_PUSH_SUBSCRIPTION_KEYS_SCHEMA = {
    "type": "object",
    "required": ["p256dh", "auth"],
    "properties": {
        "p256dh": {
            "type": "string",
            "description": "Browser push subscription p256dh key.",
            "example": "BNYExampleP256dhKey...",
        },
        "auth": {
            "type": "string",
            "description": "Browser push subscription auth secret.",
            "example": "example-auth-secret",
        },
    },
}


BROWSER_PUSH_SUBSCRIPTION_CREATE_SCHEMA = {
    "type": "object",
    "required": ["endpoint", "keys"],
    "properties": {
        "endpoint": {
            "type": "string",
            "format": "uri",
            "description": "Push service endpoint returned by subscription.toJSON().",
            "example": "https://fcm.googleapis.com/fcm/send/example-subscription-id",
        },
        "keys": BROWSER_PUSH_SUBSCRIPTION_KEYS_SCHEMA,
        "device_name": {
            "type": "string",
            "nullable": True,
            "description": "Human-readable device name shown in the profile.",
            "example": "Work laptop",
        },
        "user_agent": {
            "type": "string",
            "nullable": True,
            "description": (
                "Optional browser user agent. If omitted, the server uses the "
                "request User-Agent header."
            ),
            "example": "Mozilla/5.0 ...",
        },
    },
}


BROWSER_PUSH_SUBSCRIPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "readOnly": True, "example": 42},
        "device_name": {"type": "string", "nullable": True, "example": "Work laptop"},
        "user_agent": {"type": "string", "nullable": True, "example": "Mozilla/5.0 ..."},
        "enabled": {"type": "boolean", "example": True},
        "created_at": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
            "example": "2026-06-01T10:00:00",
        },
        "last_seen_at": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
            "example": "2026-06-01T10:05:00",
        },
    },
}


BROWSER_PUSH_DISABLE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "disabled": {"type": "boolean", "example": True},
        "id": {"type": "integer", "example": 42},
    },
}


BROWSER_PUSH_TEST_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "example": "sent"},
        "sent": {
            "type": "integer",
            "description": "Number of browser push devices that accepted the test notification.",
            "example": 1,
        },
    },
}


BROWSER_PUSH_ACTION_REQUEST_SCHEMA = {
    "type": "object",
    "required": ["token", "action"],
    "properties": {
        "token": {
            "type": "string",
            "description": (
                "One-time action token embedded into the browser push notification "
                "payload. This is not a JWT or personal API token."
            ),
            "example": "one-time-browser-push-action-token",
        },
        "action": {
            "type": "string",
            "enum": ["ack", "resolve", "shelve", "unshelve"],
            "description": "Alert action requested from the notification button. Shelve uses the one-hour preset.",
            "example": "ack",
        },
    },
}


BROWSER_PUSH_ACTION_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean", "example": True},
        "action": {
            "type": "string",
            "nullable": True,
            "enum": ["ack", "resolve", "shelve", "unshelve"],
            "example": "ack",
        },
        "alert_id": {"type": "integer", "nullable": True, "example": 123},
        "alert_group_id": {"type": "integer", "nullable": True, "example": 123},
        "action_tokens": {
            "type": "object",
            "description": (
                "Optional follow-up one-time action tokens. A successful Shelve "
                "returns Unshelve and Resolve tokens so the confirmation "
                "notification remains actionable during the one-hour shelf."
            ),
            "additionalProperties": {"type": "string"},
            "example": {
                "unshelve": "one-time-unshelve-token",
                "resolve": "one-time-resolve-token",
            },
        },
        "status": {
            "type": "string",
            "nullable": True,
            "description": "Resulting alert status after the action.",
            "example": "acknowledged",
        },
        "error": {
            "type": "string",
            "nullable": True,
            "description": (
                "Error code when ok=false. Possible values include invalid_action, "
                "missing_token, invalid_token, token_already_used, token_expired, "
                "action_mismatch and action_not_authorized."
            ),
            "example": "token_expired",
        },
    },
}


def tags():
    """Return OpenAPI tags."""
    return [
        {
            "name": "browser-push",
            "description": (
                "Profile-level browser push subscriptions and one-time alert actions. "
                "Browser push is not a notification channel; it is used by profile "
                "notification rules and by the default profile push behavior when no "
                "custom notification rules exist."
            ),
        }
    ]


def paths():
    """Return OpenAPI paths for browser push endpoints."""
    return {
        "/api/profile/push/vapid-public-key": {
            "get": {
                "tags": ["browser-push"],
                "summary": "Get browser push public config",
                "description": (
                    "Returns browser push status and the VAPID public key used by "
                    "PushManager.subscribe(). This endpoint is used by the profile UI "
                    "before creating a browser push subscription."
                ),
                "operationId": "getBrowserPushPublicConfig",
                "security": [{"bearerAuth": []}],
                "responses": {
                    "200": response(
                        "Browser push public config returned.",
                        BROWSER_PUSH_PUBLIC_CONFIG_SCHEMA,
                    ),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                },
            },
        },
        "/api/profile/push/subscriptions": {
            "get": {
                "tags": ["browser-push"],
                "summary": "List current user's browser push devices",
                "description": (
                    "Returns browser push subscriptions registered by the current user. "
                    "Deleted devices are not returned."
                ),
                "operationId": "listBrowserPushSubscriptions",
                "security": [{"bearerAuth": []}],
                "responses": {
                    "200": response(
                        "Browser push devices returned.",
                        {"type": "array", "items": BROWSER_PUSH_SUBSCRIPTION_SCHEMA},
                    ),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["browser-push"],
                "summary": "Create or update browser push subscription",
                "description": (
                    "Creates or updates the current browser push subscription for the "
                    "current user. The request body matches subscription.toJSON() plus "
                    "optional device_name and user_agent."
                ),
                "operationId": "saveBrowserPushSubscription",
                "security": [{"bearerAuth": []}],
                "requestBody": json_body(
                    "Browser push subscription returned by PushManager.subscribe().",
                    BROWSER_PUSH_SUBSCRIPTION_CREATE_SCHEMA,
                ),
                "responses": {
                    "201": response(
                        "Browser push subscription saved.",
                        BROWSER_PUSH_SUBSCRIPTION_SCHEMA,
                    ),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                },
            },
        },
        "/api/profile/push/subscriptions/{subscription_id}": {
            "delete": {
                "tags": ["browser-push"],
                "summary": "Disable browser push device",
                "description": (
                    "Soft-deletes one browser push subscription owned by the current "
                    "user. The device stops receiving browser push notifications."
                ),
                "operationId": "disableBrowserPushSubscription",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("subscription_id", "Browser push subscription id."),
                ],
                "responses": {
                    "200": response(
                        "Browser push subscription disabled.",
                        BROWSER_PUSH_DISABLE_RESPONSE_SCHEMA,
                    ),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                    "404": response("Browser push subscription not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/profile/push/test": {
            "post": {
                "tags": ["browser-push"],
                "summary": "Send test browser push",
                "description": (
                    "Sends a test browser push notification to all active devices of "
                    "the current user."
                ),
                "operationId": "sendBrowserPushTest",
                "security": [{"bearerAuth": []}],
                "responses": {
                    "200": response("Test browser push sent.", BROWSER_PUSH_TEST_RESPONSE_SCHEMA),
                    "401": response("Valid JWT token is required.", ERROR_SCHEMA),
                },
            },
        },
        "/api/push/actions": {
            "post": {
                "tags": ["browser-push"],
                "summary": "Execute browser push alert action",
                "description": (
                    "Executes ACK, Resolve, Shelve or Unshelve from a browser push notification button. "
                    "This endpoint is intentionally public and authenticates the action "
                    "using a one-time action token embedded into the notification payload. "
                    "It does not require a JWT or personal API token."
                ),
                "operationId": "executeBrowserPushAction",
                "requestBody": json_body(
                    "Browser push action token and requested action.",
                    BROWSER_PUSH_ACTION_REQUEST_SCHEMA,
                ),
                "responses": {
                    "200": response(
                        "Browser push action executed.",
                        BROWSER_PUSH_ACTION_RESPONSE_SCHEMA,
                    ),
                    "400": response(
                        "Action was rejected.",
                        BROWSER_PUSH_ACTION_RESPONSE_SCHEMA,
                    ),
                },
            },
        },
    }
