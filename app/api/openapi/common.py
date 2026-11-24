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


def catalog_page_parameters():
    """Query options shared by both paged service lists."""
    return [
        query_param("page", "Request a page instead of the full list (1-based).",
                    {"type": "integer", "minimum": 1, "default": 1}),
        query_param("page_size", "Rows per page. Also enables the paged response.",
                    {"type": "integer", "minimum": 1, "maximum": 100, "default": 25}),
        query_param("search", "Case-insensitive substring search over the scoped catalog (paged mode)."),
    ]


def catalog_list_schema(item, summary_fields):
    """Describe the legacy array and the opt-in paged catalog response."""
    items = {"type": "array", "items": item}
    count = {"type": "integer", "minimum": 0}
    pagination = {
        name: count for name in ("page", "page_size", "total_items", "total_pages", "from", "to")
    }
    pagination.update({name: {"type": "boolean"} for name in ("has_prev", "has_next")})
    return {"oneOf": [items, {
        "type": "object",
        "required": ["items", "pagination", "summary"],
        "properties": {
            "items": items,
            "pagination": {"type": "object", "properties": pagination, "required": list(pagination)},
            "summary": {
                "type": "object", "description": "Totals before applying table filters.",
                "properties": {name: count for name in summary_fields}, "required": list(summary_fields),
            },
        },
    }]}
