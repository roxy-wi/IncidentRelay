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


def tags():
    """
    Return OpenAPI tags.
    """

    return [
        {
            "name": "version",
            "description": "Service version and runtime metadata.",
        }
    ]


def paths():
    """
    Return OpenAPI paths for version endpoints.
    """

    return {
        "/api/version": {
            "get": {
                "tags": ["version"],
                "summary": "Get service version",
                "description": (
                    "Returns the current service version from the application code. "
                    "Use this endpoint for health checks, deployment verification and UI version display."
                ),
                "operationId": "getServiceVersion",
                "responses": {
                    "200": response(
                        "Service version information.",
                        {
                            "type": "object",
                            "properties": {
                                "version": {"type": "string", "example": "0.5.0"},
                            },
                        },
                    )
                },
            }
        }
    }
