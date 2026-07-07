from app.api.openapi.common import response, path_param, json_body, query_param


def string_path_param(name, description, pattern=None):
    """Build a string path parameter."""
    schema = {"type": "string", "minLength": 1}

    if pattern:
        schema["pattern"] = pattern

    return {
        "name": name,
        "in": "path",
        "required": True,
        "description": description,
        "schema": schema,
    }


def content_response(description, content):
    """Build a response object with custom content types."""
    return {
        "description": description,
        "content": content,
    }


ERROR_SCHEMA = {
    "type": "object",
    "properties": {
        "error": {
            "type": "string",
            "example": "validation_error",
        },
        "message": {
            "type": "string",
            "nullable": True,
            "example": "Request validation failed",
        },
        "details": {
            "type": "array",
            "nullable": True,
            "items": {"type": "object"},
        },
    },
}

CALENDAR_EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "Calendar event title.",
            "example": "On-call: Alice",
        },
        "start": {
            "type": "string",
            "format": "date-time",
            "description": "Event start date/time.",
            "example": "2026-06-13T09:00:00",
        },
        "end": {
            "type": "string",
            "format": "date-time",
            "description": "Event end date/time.",
            "example": "2026-06-14T09:00:00",
        },
        "rotation_id": {
            "type": "integer",
            "nullable": True,
            "description": "Rotation id that produced this event.",
            "example": 3,
        },
        "user_id": {
            "type": "integer",
            "nullable": True,
            "description": "On-call user id.",
            "example": 12,
        },
    },
}

CALENDAR_FEED_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {
            "type": "integer",
            "readOnly": True,
            "description": "Calendar feed id.",
            "example": 7,
        },
        "team_id": {
            "type": "integer",
            "description": "Team id exported by this feed.",
            "example": 1,
        },
        "team_name": {
            "type": "string",
            "description": "Team display name.",
            "example": "Cloud OPS",
        },
        "name": {
            "type": "string",
            "description": "Feed display name.",
            "example": "Outlook subscription",
        },
        "enabled": {
            "type": "boolean",
            "description": "Whether this feed URL is enabled.",
            "example": True,
        },
        "past_days": {
            "type": "integer",
            "description": "Number of past days included in the feed.",
            "example": 7,
        },
        "future_days": {
            "type": "integer",
            "description": "Number of future days included in the feed.",
            "example": 90,
        },
        "created_at": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
            "description": "Feed creation timestamp.",
            "example": "2026-06-13T10:00:00",
        },
        "last_used_at": {
            "type": "string",
            "format": "date-time",
            "nullable": True,
            "description": "Last time the public ICS URL was requested.",
            "example": "2026-06-13T10:30:00",
        },
    },
}

CALENDAR_FEED_CREATE_SCHEMA = {
    "type": "object",
    "required": ["team_id"],
    "properties": {
        "team_id": {
            "type": "integer",
            "minimum": 1,
            "description": "Team id to export.",
            "example": 1,
        },
        "name": {
            "type": "string",
            "nullable": True,
            "description": "Optional feed display name.",
            "example": "Outlook subscription",
        },
        "past_days": {
            "type": "integer",
            "minimum": 0,
            "maximum": 365,
            "description": "Number of past days included in the feed.",
            "default": 7,
            "example": 7,
        },
        "future_days": {
            "type": "integer",
            "minimum": 1,
            "maximum": 730,
            "description": "Number of future days included in the feed.",
            "default": 90,
            "example": 90,
        },
    },
}

CALENDAR_FEED_CREATE_RESPONSE_SCHEMA = {
    "allOf": [
        CALENDAR_FEED_SCHEMA,
        {
            "type": "object",
            "properties": {
                "token": {
                    "type": "string",
                    "description": (
                        "Raw secret feed token. Returned only once during "
                        "feed creation or token regeneration."
                    ),
                    "example": "R7JnYxUeQJf5m6vL0uYwX9z...",
                },
                "feed_url": {
                    "type": "string",
                    "format": "uri",
                    "description": (
                        "Public ICS subscription URL. Anyone with this URL "
                        "can read the exported team calendar."
                    ),
                    "example": (
                        "https://incidentrelay.example.com/api/calendar/feeds/"
                        "R7JnYxUeQJf5m6vL0uYwX9z.ics"
                    ),
                },
            },
        },
    ],
}

CALENDAR_FEED_DELETE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "deleted": {
            "type": "boolean",
            "example": True,
        },
        "id": {
            "type": "integer",
            "example": 7,
        },
    },
}

ICS_CALENDAR_CONTENT = {
    "text/calendar": {
        "schema": {
            "type": "string",
            "description": "RFC 5545 iCalendar content.",
            "example": (
                "BEGIN:VCALENDAR\\r\\n"
                "VERSION:2.0\\r\\n"
                "PRODID:-//IncidentRelay//On-call Calendar//EN\\r\\n"
                "X-WR-CALNAME:Cloud OPS on-call\\r\\n"
                "BEGIN:VEVENT\\r\\n"
                "UID:incidentrelay-team-1-rotation-3-20260613T090000\\r\\n"
                "SUMMARY:On-call: Alice\\r\\n"
                "DTSTART:20260613T090000Z\\r\\n"
                "DTEND:20260614T090000Z\\r\\n"
                "END:VEVENT\\r\\n"
                "END:VCALENDAR\\r\\n"
            ),
        },
    },
}


def tags():
    """Return OpenAPI tags."""
    return [
        {
            "name": "calendar",
            "description": (
                "On-call calendar API, tokenized ICS subscription feeds "
                "and calendar export management."
            ),
        },
    ]


def paths():
    """Return OpenAPI paths for calendar endpoints."""
    return {
        "/api/calendar": {
            "get": {
                "tags": ["calendar"],
                "summary": "Get team on-call calendar",
                "description": (
                    "Returns calculated calendar events for a team in a date range. "
                    "The result includes rotation slots and active overrides, so "
                    "the web calendar shows the effective on-call schedule."
                ),
                "operationId": "getOnCallCalendar",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    query_param(
                        "team_id",
                        "Team id to build the calendar for.",
                        {"type": "integer", "minimum": 1},
                        required=True,
                    ),
                    query_param(
                        "start",
                        "Start date or datetime, for example 2026-04-01.",
                        {"type": "string"},
                    ),
                    query_param(
                        "end",
                        "End date or datetime, for example 2026-05-01.",
                        {"type": "string"},
                    ),
                ],
                "responses": {
                    "200": response(
                        "Calendar events.",
                        {
                            "type": "array",
                            "items": CALENDAR_EVENT_SCHEMA,
                        },
                    ),
                    "400": response("Invalid request.", ERROR_SCHEMA),
                    "401": response("Valid JWT or API token is required.", ERROR_SCHEMA),
                    "403": response("Access to the team is denied.", ERROR_SCHEMA),
                    "404": response("Team was not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/calendar/feeds": {
            "get": {
                "tags": ["calendar"],
                "summary": "List calendar feeds",
                "description": (
                    "Lists tokenized ICS subscription feeds for a team. "
                    "The raw feed token and public feed URL are not returned by "
                    "this endpoint; they are returned only on creation or token "
                    "regeneration."
                ),
                "operationId": "listCalendarFeeds",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    query_param(
                        "team_id",
                        "Team id whose calendar feeds should be listed.",
                        {"type": "integer", "minimum": 1},
                        required=True,
                    ),
                ],
                "responses": {
                    "200": response(
                        "Calendar feed metadata.",
                        {
                            "type": "array",
                            "items": CALENDAR_FEED_SCHEMA,
                        },
                    ),
                    "400": response("team_id is required or invalid.", ERROR_SCHEMA),
                    "401": response("Valid JWT or API token is required.", ERROR_SCHEMA),
                    "403": response("Access to the team is denied.", ERROR_SCHEMA),
                    "404": response("Team was not found.", ERROR_SCHEMA),
                },
            },
            "post": {
                "tags": ["calendar"],
                "summary": "Create calendar feed",
                "description": (
                    "Creates a tokenized public ICS subscription feed for a team. "
                    "The returned feed_url is intended for Outlook, Google Calendar "
                    "and other clients that support subscribing to an iCalendar URL. "
                    "The feed token is returned only once."
                ),
                "operationId": "createCalendarFeed",
                "security": [{"bearerAuth": []}],
                "requestBody": json_body(
                    "Calendar feed creation properties.",
                    CALENDAR_FEED_CREATE_SCHEMA,
                ),
                "responses": {
                    "201": response(
                        "Calendar feed created.",
                        CALENDAR_FEED_CREATE_RESPONSE_SCHEMA,
                    ),
                    "400": response("Validation error.", ERROR_SCHEMA),
                    "401": response("Valid JWT or API token is required.", ERROR_SCHEMA),
                    "403": response("Access to the team is denied.", ERROR_SCHEMA),
                    "404": response("Team was not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/calendar/feeds/{feed_id}/token": {
            "post": {
                "tags": ["calendar"],
                "summary": "Regenerate calendar feed token",
                "description": (
                    "Regenerates the secret token for an existing ICS subscription "
                    "feed. The old public URL stops working immediately. The new "
                    "feed_url and raw token are returned only in this response."
                ),
                "operationId": "regenerateCalendarFeedToken",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("feed_id", "Calendar feed id."),
                ],
                "responses": {
                    "200": response(
                        "Calendar feed token regenerated.",
                        CALENDAR_FEED_CREATE_RESPONSE_SCHEMA,
                    ),
                    "401": response("Valid JWT or API token is required.", ERROR_SCHEMA),
                    "403": response("Access to the team is denied.", ERROR_SCHEMA),
                    "404": response("Calendar feed was not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/calendar/feeds/{feed_id}": {
            "delete": {
                "tags": ["calendar"],
                "summary": "Delete calendar feed",
                "description": (
                    "Disables and soft-deletes an ICS subscription feed. "
                    "The public .ics URL stops working after deletion."
                ),
                "operationId": "deleteCalendarFeed",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    path_param("feed_id", "Calendar feed id."),
                ],
                "responses": {
                    "200": response(
                        "Calendar feed deleted.",
                        CALENDAR_FEED_DELETE_RESPONSE_SCHEMA,
                    ),
                    "401": response("Valid JWT or API token is required.", ERROR_SCHEMA),
                    "403": response("Access to the team is denied.", ERROR_SCHEMA),
                    "404": response("Calendar feed was not found.", ERROR_SCHEMA),
                },
            },
        },
        "/api/calendar/feeds/{token}.ics": {
            "get": {
                "tags": ["calendar"],
                "summary": "Download public ICS calendar feed",
                "description": (
                    "Returns an iCalendar subscription feed for the team associated "
                    "with the secret feed token. This endpoint is intentionally public: "
                    "authentication is the secret token embedded in the URL. Regenerate "
                    "or delete the feed to revoke access."
                ),
                "operationId": "downloadCalendarFeedIcs",
                "parameters": [
                    string_path_param(
                        "token",
                        "Secret calendar feed token.",
                        pattern="^[A-Za-z0-9_\\-\\.]+$",
                    ),
                ],
                "responses": {
                    "200": content_response(
                        "iCalendar feed.",
                        ICS_CALENDAR_CONTENT,
                    ),
                    "403": response(
                        "Feed exists, but the team or group is inactive.",
                        ERROR_SCHEMA,
                    ),
                    "404": response("Calendar feed was not found.", ERROR_SCHEMA),
                },
            },
            "head": {
                "tags": ["calendar"],
                "summary": "Check public ICS calendar feed",
                "description": (
                    "Returns headers for a public ICS subscription feed without "
                    "returning the calendar body."
                ),
                "operationId": "headCalendarFeedIcs",
                "parameters": [
                    string_path_param(
                        "token",
                        "Secret calendar feed token.",
                        pattern="^[A-Za-z0-9_\\-\\.]+$",
                    ),
                ],
                "responses": {
                    "200": {
                        "description": "Calendar feed exists.",
                    },
                    "403": response(
                        "Feed exists, but the team or group is inactive.",
                        ERROR_SCHEMA,
                    ),
                    "404": response("Calendar feed was not found.", ERROR_SCHEMA),
                },
            },
        },
    }
