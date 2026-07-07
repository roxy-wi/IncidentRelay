from app.api.openapi.common import response


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
