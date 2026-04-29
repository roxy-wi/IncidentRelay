def path_param(name, description):
    """
    Build an integer path parameter.
    """

    return {
        "name": name,
        "in": "path",
        "required": True,
        "description": description,
        "schema": {"type": "integer", "minimum": 1},
    }


def query_param(name, description, schema=None, required=False):
    """
    Build a query parameter.
    """

    return {
        "name": name,
        "in": "query",
        "required": required,
        "description": description,
        "schema": schema or {"type": "string"},
    }


def json_body(description, schema, required=True):
    """
    Build a JSON request body.
    """

    return {
        "required": required,
        "description": description,
        "content": {
            "application/json": {
                "schema": schema
            }
        },
    }


def response(description, schema=None):
    """
    Build a JSON response.
    """

    item = {"description": description}

    if schema:
        item["content"] = {
            "application/json": {
                "schema": schema
            }
        }

    return item


CHANNEL_SCHEMA = {
    "type": "object",
    "required": ["name", "channel_type", "config"],
    "properties": {
        "team_id": {"type": "integer", "nullable": True, "description": "Owner team id."},
        "name": {"type": "string", "example": "infra-telegram"},
        "channel_type": {
            "type": "string",
            "enum": ["telegram", "slack", "mattermost", "webhook", "discord", "teams", "email"],
            "example": "telegram",
        },
        "config": {
            "type": "object",
            "description": (
                "Channel-specific configuration. Telegram requires bot_token and chat_id. "
                "Slack/Webhook/Discord/Teams require webhook_url. Mattermost can use webhook_url, or "
                "mode=bot_api with api_url, bot_token and channel_id for buttons and post updates. Email requires recipients."
            ),
            "example": {"mode": "bot_api", "api_url": "https://mattermost.example.com", "bot_token": "...", "channel_id": "..."},
        },
        "enabled": {"type": "boolean", "default": True},
        "intake_token_prefix": {"type": "string", "nullable": True, "description": "Prefix of the alert intake token. The full token is shown only once."},
        "has_intake_token": {"type": "boolean", "description": "True when this channel has an alert intake token."},
    },
}


def tags():
    """
    Return OpenAPI tags.
    """

    return [
        {
            "name": "channels",
            "description": (
                "Notification channels. Channels are connected to alert routes and are used to send "
                "initial notifications, reminders, escalations and resolve messages."
            ),
        }
    ]


def paths():
    """
    Return OpenAPI paths for channel endpoints.
    """

    return {
        "/api/channels/types": {
            "get": {
                "tags": ["channels"],
                "summary": "List supported channel types",
                "description": "Returns channel plugins supported by the service.",
                "operationId": "listChannelTypes",
                "responses": {"200": response("Supported channel types.")},
            }
        },
        "/api/channels": {
            "get": {
                "tags": ["channels"],
                "summary": "List channels",
                "description": "Returns notification channels. Optional team_id filters channels by owner team.",
                "operationId": "listChannels",
                "parameters": [query_param("team_id", "Filter channels by team id.", {"type": "integer", "minimum": 1})],
                "responses": {"200": response("List of channels.", {"type": "array", "items": CHANNEL_SCHEMA})},
            },
            "post": {
                "tags": ["channels"],
                "summary": "Create channel",
                "description": (
                    "Creates a notification channel. The response contains intake_token once. Store it safely and use it "
                    "as Authorization: Bearer TOKEN for incoming alert endpoints."
                ),
                "operationId": "createChannel",
                "requestBody": json_body("Channel properties.", CHANNEL_SCHEMA),
                "responses": {"201": response("Channel created. The full intake_token is returned only in this response."), "400": response("Validation error.")},
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
                "responses": {"200": response("Channel updated."), "400": response("Validation error.")},
            },
            "delete": {
                "tags": ["channels"],
                "summary": "Disable channel",
                "description": "Soft-deletes a channel by setting enabled=false. Route/channel history remains intact.",
                "operationId": "disableChannel",
                "parameters": [path_param("channel_id", "Channel id.")],
                "responses": {"200": response("Channel disabled.")},
            },
        },
        "/api/channels/{channel_id}/intake-token": {
            "post": {
                "tags": ["channels"],
                "summary": "Regenerate alert intake token",
                "description": "Creates a new per-channel token for incoming alerts. The old token stops working. The full token is returned only once.",
                "operationId": "regenerateChannelIntakeToken",
                "parameters": [path_param("channel_id", "Channel id.")],
                "responses": {"200": response("New channel intake token returned.")},
            }
        },
        "/api/channels/{channel_id}/test": {
            "post": {
                "tags": ["channels"],
                "summary": "Send test notification",
                "description": (
                    "Sends a test message through the selected channel. Use this to verify Telegram bot tokens, "
                    "webhook URLs and SMTP settings before attaching the channel to alert routes."
                ),
                "operationId": "testChannel",
                "parameters": [path_param("channel_id", "Channel id.")],
                "responses": {
                    "200": response("Test notification sent."),
                    "400": response("Test failed. The response contains the transport error."),
                },
            }
        },
    }
