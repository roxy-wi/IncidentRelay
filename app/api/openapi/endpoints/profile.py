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


def json_body(description, schema, required=True):
    """
    Build a JSON request body.
    """
    return {
        "required": required,
        "description": description,
        "content": {
            "application/json": {
                "schema": schema,
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
                "schema": schema,
            }
        }

    return item


PROFILE_TOKEN_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "readOnly": True},
        "name": {"type": "string"},
        "token_prefix": {"type": "string"},
        "scopes": {
            "type": "array",
            "items": {"type": "string"},
        },
        "group_id": {"type": "integer", "nullable": True},
        "group_slug": {"type": "string", "nullable": True},
        "group_name": {"type": "string", "nullable": True},
        "active": {"type": "boolean"},
        "expired": {"type": "boolean"},
        "created_at": {"type": "string", "format": "date-time", "nullable": True},
        "expires_at": {"type": "string", "format": "date-time", "nullable": True},
        "last_used_at": {"type": "string", "format": "date-time", "nullable": True},
    },
}


PROFILE_TOKEN_CREATE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "default": "personal-api-token",
        },
        "group_id": {
            "type": "integer",
            "nullable": True,
        },
        "scopes": {
            "type": "array",
            "items": {"type": "string"},
            "default": ["alerts:read"],
        },
        "days": {
            "type": "integer",
            "minimum": 0,
            "default": 0,
            "description": "Token lifetime in days. 0 means no expiration.",
        },
    },
}


def tags():
    """
    Return OpenAPI tags.
    """
    return [
        {
            "name": "profile",
            "description": "Current user profile, active group, password and personal API tokens.",
        }
    ]


def paths():
    """
    Return OpenAPI paths for profile endpoints.
    """
    return {
        "/api/profile/tokens": {
            "get": {
                "tags": ["profile"],
                "summary": "List personal API tokens",
                "description": (
                    "Returns metadata for current user's personal API tokens. "
                    "The token hash and full raw token are never returned."
                ),
                "operationId": "listProfileTokens",
                "security": [{"bearerAuth": []}],
                "responses": {
                    "200": response(
                        "Token metadata returned.",
                        {
                            "type": "array",
                            "items": PROFILE_TOKEN_SCHEMA,
                        },
                    ),
                    "401": response("Valid JWT token is required."),
                },
            },
            "post": {
                "tags": ["profile"],
                "summary": "Create personal API token",
                "description": (
                    "Creates a personal API token. "
                    "The full token is returned only once in this response."
                ),
                "operationId": "createProfileToken",
                "security": [{"bearerAuth": []}],
                "requestBody": json_body(
                    "Token creation properties.",
                    PROFILE_TOKEN_CREATE_SCHEMA,
                ),
                "responses": {
                    "201": response(
                        "Token created.",
                        {
                            "allOf": [
                                PROFILE_TOKEN_SCHEMA,
                                {
                                    "type": "object",
                                    "properties": {
                                        "token": {
                                            "type": "string",
                                            "description": "Full token value shown only once.",
                                        }
                                    },
                                },
                            ]
                        },
                    ),
                    "400": response("Validation error."),
                    "403": response("Selected group is not accessible."),
                    "401": response("Valid JWT token is required."),
                },
            },
        },
        "/api/profile/tokens/{token_id}": {
            "delete": {
                "tags": ["profile"],
                "summary": "Revoke personal API token",
                "description": (
                    "Revokes a personal API token owned by the current user. "
                    "The token is soft-deleted and becomes inactive."
                ),
                "operationId": "revokeProfileToken",
                "security": [{"bearerAuth": []}],
                "parameters": [path_param("token_id", "Personal API token id.")],
                "responses": {
                    "200": response(
                        "Token revoked.",
                        {
                            "type": "object",
                            "properties": {
                                "revoked": {"type": "boolean"},
                                "id": {"type": "integer"},
                            },
                        },
                    ),
                    "404": response("Token not found."),
                    "401": response("Valid JWT token is required."),
                },
            },
        },
    }
