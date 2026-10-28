"""Shared OpenAPI helper builders."""

ERROR_SCHEMA = {
    "type": "object",
    "properties": {
        "error": {"type": "string", "example": "validation_error"},
        "message": {"type": "string", "nullable": True},
        "details": {"type": "array", "items": {"type": "object"}},
    },
}


def path_param(name, description):
    """Build an integer path parameter."""
    return {
        "name": name,
        "in": "path",
        "required": True,
        "description": description,
        "schema": {"type": "integer", "minimum": 1},
    }


def query_param(name, description, schema=None, required=False):
    """Build a query parameter."""
    return {
        "name": name,
        "in": "query",
        "required": required,
        "description": description,
        "schema": schema or {"type": "string"},
    }


def json_body(description, schema, required=True, *, examples=None):
    """Build a JSON request body."""
    media_type = {"schema": schema}
    if examples is not None:
        media_type["examples"] = examples
    return {
        "required": required,
        "description": description,
        "content": {"application/json": media_type},
    }


def response(description, schema=None):
    """Build a JSON response object."""
    item = {"description": description}
    if schema:
        item["content"] = {"application/json": {"schema": schema}}
    return item
