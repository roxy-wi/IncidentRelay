from app.api.openapi.common import ERROR_SCHEMA, json_body, path_param, query_param, response
from app.notifiers.email.email_templates import (
    DEFAULT_EMAIL_HTML_TEMPLATE,
    EMAIL_HTML_TEMPLATE_MAX_LENGTH,
)
from app.notifiers.types import CHANNEL_TYPE_VALUES


SEVERITY_FILTER_SCHEMA = {
    "type": "array",
    "description": (
        "Optional channel-level alert severity filter. If empty or omitted, "
        "the channel receives all severities. Values are normalized, for example "
        "crit -> critical, warn -> warning, information -> info."
    ),
    "items": {
        "type": "string",
        "enum": ["critical", "high", "medium", "warning", "low", "info"],
    },
    "example": ["critical", "high"],
}


EMAIL_CONFIG_SCHEMA = {
    "type": "object",
    "description": (
        "Email channel config. The recipient is not stored in the channel: "
        "real alerts are sent to the assigned user's profile email, and test "
        "emails are sent to the current user's profile email. SMTP transport "
        "is configured globally."
    ),
    "properties": {
        "notify_on_severities": SEVERITY_FILTER_SCHEMA,
        "html_template": {
            "type": "string",
            "maxLength": EMAIL_HTML_TEMPLATE_MAX_LENGTH,
            "description": (
                "Optional Python-format HTML template. Leave empty to use "
                "the service default. Supported placeholders: {alert_id}, "
                "{event_type}, {title}, {message}, {severity}, {status}, "
                "{team}, {assignee}, {source}, {alert_url}."
            ),
            "example": DEFAULT_EMAIL_HTML_TEMPLATE,
        },
    },
    "additionalProperties": True,
}


CHANNEL_SCHEMA = {
    "type": "object",
    "required": ["team_id", "name", "channel_type", "config"],
    "properties": {
        "team_id": {
            "type": "integer",
            "minimum": 1,
            "nullable": True,
            "description": "Owner team id.",
        },
        "name": {
            "type": "string",
            "minLength": 2,
            "maxLength": 120,
            "example": "infra-email",
        },
        "channel_type": {
            "type": "string",
            "enum": list(CHANNEL_TYPE_VALUES),
            "example": "email",
        },
        "config": {
            "type": "object",
            "description": (
                "Channel-specific notification configuration. Channels are "
                "team-level external delivery targets attached to alert routes. "
                "All channel types support notify_on_severities as an optional "
                "channel-level severity filter. Telegram requires bot_token and "
                "chat_id. Slack supports webhook mode or Bot API mode. Slack "
                "Bot API actions can use connection_mode=http with a signing "
                "secret, or connection_mode=socket_mode with an xapp app token. "
                "Webhook/Discord/Teams require webhook_url. Mattermost can use "
                "webhook_url, or mode=bot_api with api_url, "
                "bot_token and channel_id for buttons and post updates. Email sends "
                "to the assigned user's profile email and supports html_template. "
                "Voice calls and browser push are configured through profile "
                "notification rules, not channels."
            ),
            "properties": {
                "notify_on_severities": SEVERITY_FILTER_SCHEMA,
            },
            "additionalProperties": True,
            "example": {
                "html_template": "# {event_type}: {title}\n\n{message}\n",
                "notify_on_severities": ["critical", "high"],
            },
        },
        "enabled": {
            "type": "boolean",
            "default": True,
        },
    },
}


CHANNEL_CONFLICT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "error": {"type": "string", "example": "conflict"},
        "message": {
            "type": "string",
            "example": "Channel with this name already exists in this team",
        },
        "details": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "example": "name"},
                    "loc": {
                        "type": "array",
                        "items": {"type": "string"},
                        "example": ["name"],
                    },
                    "message": {
                        "type": "string",
                        "example": "Channel name must be unique within a team",
                    },
                    "type": {"type": "string", "example": "unique"},
                    "input": {"type": "string", "example": "cloud-mail"},
                },
            },
        },
    },
}


EMAIL_DEFAULT_TEMPLATE_SCHEMA = {
    "type": "object",
    "properties": {
        "html_template": {
            "type": "string",
            "description": "Default email channel HTML template.",
            "example": DEFAULT_EMAIL_HTML_TEMPLATE,
        }
    },
}


CHANNEL_DELETE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "deleted": {"type": "boolean", "example": True},
        "id": {"type": "integer", "example": 1},
        "name": {"type": "string", "example": "infra-email"},
    },
}


def tags():
    """Return OpenAPI tags."""
    return [
        {
            "name": "channels",
            "description": (
                "Team-level outbound notification channels. Channels are connected "
                "to alert routes and are used to send initial notifications, "
                "reminders, escalations and resolve messages to external systems. "
                "User-level browser push, email and voice call preferences are "
                "configured with profile notification rules."
            ),
        }
    ]


def paths():
    """Return OpenAPI paths for channel endpoints."""
    return {
        "/api/channels/types": {
            "get": {
                "tags": ["channels"],
                "summary": "List supported channel types",
                "description": (
                    "Returns notification channel plugins supported by the service. "
                    "The list contains route-attached channel types only; voice_call "
                    "and browser_push are not channel types."
                ),
                "operationId": "listChannelTypes",
                "responses": {
                    "200": response(
                        "Supported channel types.",
                        {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": list(CHANNEL_TYPE_VALUES),
                            },
                        },
                    )
                },
            }
        },
        "/api/channels/email-template/default": {
            "get": {
                "tags": ["channels"],
                "summary": "Get default email HTML template",
                "description": (
                    "Returns the built-in email HTML template used when channel config "
                    "does not define html_template."
                ),
                "operationId": "getDefaultEmailTemplate",
                "responses": {
                    "200": response("Default email template.", EMAIL_DEFAULT_TEMPLATE_SCHEMA)
                },
            }
        },
        "/api/channels": {
            "get": {
                "tags": ["channels"],
                "summary": "List channels",
                "description": "Returns notification channels. Optional team_id filters channels by owner team.",
                "operationId": "listChannels",
                "parameters": [
                    query_param(
                        "team_id",
                        "Filter channels by team id.",
                        {"type": "integer", "minimum": 1},
                    )
                ],
                "responses": {
                    "200": response(
                        "List of channels.",
                        {"type": "array", "items": CHANNEL_SCHEMA},
                    )
                },
            },
            "post": {
                "tags": ["channels"],
                "summary": "Create channel",
                "description": (
                    "Creates an outbound route channel. Intake tokens belong to alert "
                    "routes, not channels. Attach channels to routes to receive alert "
                    "notifications. Voice calls and browser push are configured in "
                    "profile notification rules."
                ),
                "operationId": "createChannel",
                "requestBody": json_body("Channel properties.", CHANNEL_SCHEMA),
                "responses": {
                    "201": response("Channel created.", CHANNEL_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "409": response(
                        "Channel name already exists in this team.",
                        CHANNEL_CONFLICT_RESPONSE_SCHEMA,
                    ),
                },
            },
        },
        "/api/channels/{channel_id}": {
            "get": {
                "tags": ["channels"],
                "summary": "Get channel",
                "description": "Returns one channel by id, including config.",
                "operationId": "getChannel",
                "parameters": [path_param("channel_id", "Channel id.")],
                "responses": {"200": response("Channel details.", CHANNEL_SCHEMA)},
            },
            "put": {
                "tags": ["channels"],
                "summary": "Update channel",
                "description": "Updates channel name, type, enabled flag and config.",
                "operationId": "updateChannel",
                "parameters": [path_param("channel_id", "Channel id.")],
                "requestBody": json_body("Updated channel properties.", CHANNEL_SCHEMA),
                "responses": {
                    "200": response("Channel updated.", CHANNEL_SCHEMA),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "409": response(
                        "Channel name already exists in this team.",
                        CHANNEL_CONFLICT_RESPONSE_SCHEMA,
                    ),
                },
            },
            "delete": {
                "tags": ["channels"],
                "summary": "Delete channel",
                "description": "Soft-deletes a notification channel. Historical alerts are preserved.",
                "operationId": "deleteChannel",
                "parameters": [path_param("channel_id", "Channel id.")],
                "responses": {
                    "200": response("Channel deleted.", CHANNEL_DELETE_RESPONSE_SCHEMA),
                    "403": response("Access denied.", ERROR_SCHEMA),
                    "404": response("Channel not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/channels/{channel_id}/disable": {
            "post": {
                "tags": ["channels"],
                "summary": "Disable channel",
                "description": "Disables a notification channel by setting enabled=false.",
                "operationId": "disableChannel",
                "parameters": [path_param("channel_id", "Channel id.")],
                "responses": {"200": response("Channel disabled.", CHANNEL_SCHEMA)},
            }
        },
        "/api/channels/{channel_id}/enable": {
            "post": {
                "tags": ["channels"],
                "summary": "Enable channel",
                "description": "Enables a previously disabled notification channel.",
                "operationId": "enableChannel",
                "parameters": [path_param("channel_id", "Channel id.")],
                "responses": {"200": response("Channel enabled.", CHANNEL_SCHEMA)},
            }
        },
        "/api/channels/{channel_id}/test": {
            "post": {
                "tags": ["channels"],
                "summary": "Send test notification",
                "description": (
                    "Sends a test message through the selected channel. Email tests "
                    "are sent to the current user's profile email."
                ),
                "operationId": "testChannel",
                "parameters": [path_param("channel_id", "Channel id.")],
                "responses": {
                    "200": response("Test notification sent."),
                    "400": response(
                        "Test failed. The response contains the transport error.",
                        ERROR_SCHEMA,
                    ),
                },
            }
        },
    }
