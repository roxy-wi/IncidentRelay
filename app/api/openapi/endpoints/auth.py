def tags():
    """
    Return OpenAPI tags for authentication.
    """

    return [
        {
            "name": "Authentication",
            "description": "JWT authentication methods for the web UI and API clients.",
        }
    ]


def paths():
    """
    Return OpenAPI paths for JWT authentication.
    """

    return {
        "/api/auth/login": {
            "post": {
                "tags": ["Authentication"],
                "summary": "Login with username and password",
                "description": "Authenticates a user and returns a JWT access token. The token must be sent as Authorization: Bearer TOKEN.",
                "operationId": "login",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["username", "password"],
                                "properties": {
                                    "username": {"type": "string", "example": "ivan"},
                                    "password": {"type": "string", "format": "password", "example": "changeme123"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "JWT token returned"},
                    "401": {"description": "Invalid username or password"},
                },
            }
        },
        "/api/auth/me": {
            "get": {
                "tags": ["Authentication"],
                "summary": "Get current JWT user",
                "description": "Returns the user attached to the current JWT token.",
                "operationId": "getCurrentUser",
                "security": [{"bearerAuth": []}],
                "responses": {
                    "200": {"description": "Current user returned"},
                    "401": {"description": "Valid JWT token is required"},
                },
            }
        },
        "/api/auth/change-password": {
            "post": {
                "tags": ["Authentication"],
                "summary": "Change password",
                "description": "Changes the password for the current JWT user.",
                "operationId": "changePassword",
                "security": [{"bearerAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["old_password", "new_password"],
                                "properties": {
                                    "old_password": {"type": "string", "format": "password"},
                                    "new_password": {"type": "string", "format": "password"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Password changed"},
                    "400": {"description": "Old password is invalid"},
                    "401": {"description": "Valid JWT token is required"},
                },
            }
        },
    }
