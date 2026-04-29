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


USER_SCHEMA = {
    "type": "object",
    "required": ["username"],
    "properties": {
        "username": {"type": "string", "example": "ivan"},
        "display_name": {"type": "string", "nullable": True, "example": "Ivan"},
        "email": {"type": "string", "nullable": True, "format": "email", "example": "ivan@example.com"},
        "phone": {"type": "string", "nullable": True},
        "telegram_chat_id": {"type": "string", "nullable": True},
        "slack_user_id": {"type": "string", "nullable": True},
        "mattermost_user_id": {"type": "string", "nullable": True},
        "active": {"type": "boolean", "default": True},
        "is_admin": {"type": "boolean", "default": False},
    },
}


def tags():
    """
    Return OpenAPI tags.
    """

    return [
        {
            "name": "users",
            "description": (
                "User management endpoints. Regular endpoints manage on-call users; "
                "admin endpoints are reserved for the future RBAC/admin area."
            ),
        }
    ]


def paths():
    """
    Return OpenAPI paths for user endpoints.
    """

    return {
        "/api/users": {
            "get": {
                "tags": ["users"],
                "summary": "List users",
                "description": "Returns all users that can be assigned to teams and rotations.",
                "operationId": "listUsers",
                "responses": {"200": response("List of users.", {"type": "array", "items": USER_SCHEMA})},
            },
            "post": {
                "tags": ["users"],
                "summary": "Create user",
                "description": "Creates an on-call user with optional messenger identifiers.",
                "operationId": "createUser",
                "requestBody": json_body("User properties.", USER_SCHEMA),
                "responses": {"201": response("User created."), "400": response("Validation error.")},
            },
        },
        "/api/users/{user_id}": {
            "get": {
                "tags": ["users"],
                "summary": "Get user",
                "description": "Returns one user by id.",
                "operationId": "getUser",
                "parameters": [path_param("user_id", "User id.")],
                "responses": {"200": response("User details.", USER_SCHEMA), "404": response("User not found.")},
            },
            "put": {
                "tags": ["users"],
                "summary": "Update user",
                "description": "Updates contact fields and messenger identifiers for an on-call user.",
                "operationId": "updateUser",
                "parameters": [path_param("user_id", "User id.")],
                "requestBody": json_body("Updated user properties.", USER_SCHEMA),
                "responses": {"200": response("User updated."), "400": response("Validation error.")},
            },
            "delete": {
                "tags": ["users"],
                "summary": "Disable user",
                "description": "Soft-deletes a user by marking it inactive. Existing alert history remains intact.",
                "operationId": "disableUser",
                "parameters": [path_param("user_id", "User id.")],
                "responses": {"200": response("User disabled.")},
            },
        },
        "/api/admin/users": {
            "get": {
                "tags": ["users"],
                "summary": "List admin users",
                "description": (
                    "Returns users for the admin users page. This endpoint is separated from regular user "
                    "management so RBAC enforcement can be enabled later without changing the UI contract."
                ),
                "operationId": "listAdminUsers",
                "responses": {"200": response("List of admin users.")},
            },
        },
        "/api/admin/users/{user_id}": {
            "get": {
                "tags": ["users"],
                "summary": "Get admin user",
                "description": "Returns a user from the admin namespace.",
                "operationId": "getAdminUser",
                "parameters": [path_param("user_id", "User id.")],
                "responses": {"200": response("User details.")},
            },
            "put": {
                "tags": ["users"],
                "summary": "Update admin user",
                "description": "Updates user fields from the admin namespace. Intended for future RBAC enforcement.",
                "operationId": "updateAdminUser",
                "parameters": [path_param("user_id", "User id.")],
                "requestBody": json_body("Updated user properties.", USER_SCHEMA),
                "responses": {"200": response("User updated.")},
            },
            "delete": {
                "tags": ["users"],
                "summary": "Disable admin user",
                "description": "Soft-deletes a user from the admin namespace.",
                "operationId": "disableAdminUser",
                "parameters": [path_param("user_id", "User id.")],
                "responses": {"200": response("User disabled.")},
            },
        },
    }
