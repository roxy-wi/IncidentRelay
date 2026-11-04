"""Human Change reads, including the deliberately limited cross-team projection."""

from app.api.openapi.common import query_param, response

TEXT = {"type": "string"}
TIME = {"type": "string", "format": "date-time", "nullable": True}
ID = {"type": "integer", "minimum": 1}


def tags():
    """Group read endpoints separately from machine ingestion."""
    return [
        {
            "name": "Changes",
            "description": "Human read API; integration tokens cannot read Changes.",
        }
    ]


def object_schema(properties, required=None):
    """Document explicit response whitelists, including optional owner details."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties) if required is None else required,
    }


def page_schema(item):
    """Use the application's bounded page response shape."""
    return object_schema(
        {
            "items": {"type": "array", "items": item},
            "pagination": object_schema(
                {
                    name: {"type": "integer", "minimum": 0}
                    for name in ("page", "page_size", "total", "pages")
                }
            ),
        }
    )


def components():
    """Describe full and safe responses as mutually exclusive projections."""
    service = object_schema({"id": ID, "name": TEXT, "slug": TEXT, "team_id": ID})
    relation = {"type": "string", "enum": ["changed", "reported_affected"]}
    link = object_schema(
        {"service": service, "relation_type": relation, "verification_state": TEXT},
        ["service", "relation_type"],
    )
    shared = {
        "uid": {"type": "string", "format": "uuid"},
        "projection": TEXT,
        "title": TEXT,
        "kind": TEXT,
        "occurred_at": TIME,
    }
    safe = object_schema(
        {
            **shared,
            "projection": {"type": "string", "enum": ["safe"]},
            "services": {
                "type": "array",
                "maxItems": 5,
                "items": object_schema({"service": service, "relation_type": relation}),
            },
        }
    )
    full_properties = {
        **shared,
        "projection": {"type": "string", "enum": ["full"]},
        "change_id": TEXT,
        "source": TEXT,
        "owner_team": object_schema({"id": ID, "name": TEXT}),
        "environment": {**TEXT, "nullable": True},
        "status": TEXT,
        "lifecycle_conflict": {"type": "boolean"},
        "mapping_status": TEXT,
        "reference_counts": {
            "type": "object",
            "additionalProperties": {"type": "integer", "minimum": 0},
        },
        "revision": ID,
        "processing": object_schema(
            {
                "state": TEXT,
                "current": {"type": "boolean"},
                "error": {**TEXT, "nullable": True},
            }
        ),
        "started_at": TIME,
        "completed_at": TIME,
    }
    full = object_schema(
        {
            **full_properties,
            "description": {**TEXT, "nullable": True},
            "external_url": {**TEXT, "nullable": True},
            "ordering_mode": TEXT,
            "diagnostics": {
                "type": "array",
                "items": object_schema(
                    {
                        "code": TEXT,
                        "event_ids": {"type": "array", "items": TEXT},
                        "count": {"type": "integer", "minimum": 1},
                    },
                    ["code"],
                ),
            },
        },
        list(full_properties),
    )
    event = object_schema(
        {
            "uid": {"type": "string", "format": "uuid"},
            "event_id": TEXT,
            "event_type": TEXT,
            "occurred_at": TIME,
            "received_at": TIME,
            "source_sequence": {"type": "integer", "nullable": True},
            "actor": object_schema(
                {"type": {**TEXT, "nullable": True}, "name": {**TEXT, "nullable": True}}
            ),
            "details": {"type": "object"},
            "fields": {"type": "object"},
        }
    )
    reference = object_schema(
        {
            "id": ID,
            "relation_type": relation,
            "team_id": ID,
            "service_id": {**ID, "nullable": True},
            "service": {**service, "nullable": True},
            "requested_service_id": {**ID, "nullable": True},
            "requested_service_slug": {**TEXT, "nullable": True},
            "resolution_status": TEXT,
            "verification_state": TEXT,
            "expires_at": TIME,
            "last_error_code": {**TEXT, "nullable": True},
        }
    )
    services = page_schema(link)
    services["properties"]["references"] = page_schema(reference)
    return {
        "ChangeFull": full,
        "ChangeSafe": safe,
        "ChangeRead": {
            "oneOf": [
                {"$ref": "#/components/schemas/ChangeFull"},
                {"$ref": "#/components/schemas/ChangeSafe"},
            ]
        },
        "ChangeSourceOptions": object_schema(
            {"items": {"type": "array", "items": TEXT, "uniqueItems": True}}
        ),
        "ChangeReadPage": page_schema({"$ref": "#/components/schemas/ChangeRead"}),
        "ChangeEventPage": page_schema(event),
        "ChangeServicePage": services,
    }


def paths():
    """Publish exact read routes and their authentication/filter boundaries."""
    pagination = [
        query_param(
            "page",
            "Page number",
            {"type": "integer", "minimum": 1, "maximum": 1000000, "default": 1},
        ),
        query_param(
            "page_size",
            "Rows per page",
            {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
        ),
    ]
    filters = pagination + [
        query_param(name, description, schema)
        for name, description, schema in (
            (
                "search",
                "Owner title/external ID; safe rows match only kind or the constant Related change title",
                {**TEXT, "maxLength": 200},
            ),
            ("owner_team_id", "Readable owner Team only", ID),
            (
                "scope_team_id",
                "Readable Team context: ownership or a related Service",
                ID,
            ),
            (
                "service_id",
                "Readable Service; mutually exclusive with service_slug",
                ID,
            ),
            (
                "service_slug",
                "Requires exactly one team_id or team_slug namespace",
                TEXT,
            ),
            ("team_id", "Namespace for service_slug only", ID),
            ("team_slug", "Namespace for service_slug only", TEXT),
            (
                "kind",
                "Change kind",
                {
                    "type": "string",
                    "enum": [
                        "deployment",
                        "configuration",
                        "infrastructure",
                        "database",
                        "feature_flag",
                        "other",
                    ],
                },
            ),
            (
                "status",
                "Owner projections only",
                {
                    "type": "string",
                    "enum": [
                        "unknown",
                        "running",
                        "succeeded",
                        "failed",
                        "rolled_back",
                        "cancelled",
                    ],
                },
            ),
            ("source", "Exact source, owner projections only", TEXT),
            ("environment", "Exact environment, owner projections only", TEXT),
            (
                "occurred_from",
                "Inclusive last sender event time, ISO timestamp with timezone",
                TIME,
            ),
            (
                "occurred_to",
                "Inclusive last sender event time, ISO timestamp with timezone",
                TIME,
            ),
        )
    ]
    result = {}
    for path, schema, summary, parameters in (
        ("/api/changes", "ChangeReadPage", "List visible Changes", filters),
        (
            "/api/changes/sources",
            "ChangeSourceOptions",
            "List distinct source names in readable owner Teams (including inactive sources)",
            [],
        ),
        (
            "/api/changes/{change_uid}",
            "ChangeRead",
            "Read a full or safe Change projection",
            [],
        ),
        (
            "/api/changes/{change_uid}/events",
            "ChangeEventPage",
            "Read immutable events (owner Team readers only)",
            pagination,
        ),
        (
            "/api/changes/{change_uid}/services",
            "ChangeServicePage",
            "Read scoped canonical links and owner reference diagnostics",
            pagination,
        ),
        (
            "/api/services/{service_id}/changes",
            "ChangeReadPage",
            "List Changes for a readable Service",
            filters,
        ),
    ):
        params = list(parameters)
        if "{change_uid}" in path:
            params.append(
                {
                    "name": "change_uid",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string", "format": "uuid"},
                }
            )
        if "{service_id}" in path:
            params.append(
                {"name": "service_id", "in": "path", "required": True, "schema": ID}
            )
        result[path] = {
            "get": {
                "tags": ["Changes"],
                "summary": summary,
                "security": [{"bearerAuth": []}],
                "parameters": params,
                "description": (
                    "Authentication is mandatory even with optional global auth. Human JWT or an active user's personal token with changes:read; "
                    "nested Service reads also require services:read. Token Group/Team restrictions apply. "
                    "SQL visibility precedes search, counting and pagination. Unavailable and hidden resources return the same 404. "
                    "Foreign readers receive only an opaque UUID, constant title, kind, event time and accessible trusted Service relations. "
                    "Summary services are limited to five; use the paginated services endpoint for all accessible links. "
                    "Events are owner-only and omit raw snapshots, submitted references and credential data. "
                    "Canonical links and references are separately paginated by the same page parameters; reference counts exclude hidden resources. "
                    "Foreign visibility requires a completed mapping pass with current input revisions. Reads never enqueue work. "
                    "Lists use last event time descending, then ID; event history follows the Change ordering mode descending. "
                    "Unknown/duplicate filters are rejected. All responses use Cache-Control: no-store."
                ),
                "responses": {
                    "200": response(
                        "Visible data", {"$ref": "#/components/schemas/" + schema}
                    ),
                    "400": response("Invalid query"),
                    "401": response("Authentication required"),
                    "403": response("Missing scope or machine token"),
                    "404": response("Resource unavailable"),
                },
            }
        }
        if path == "/api/changes/sources":
            result[path]["get"]["description"] = (
                "Authentication is mandatory: human JWT or a personal token with changes:read. "
                "Token Group/Team restrictions apply; machine tokens cannot read. "
                "Returns all distinct source names in readable owner Teams, sorted by name. "
                "Includes inactive sources/integrations and sources without Changes for historical filtering. "
                "Cross-team Service links do not grant access to the owner's source names. "
                "No query parameters are accepted. Cache-Control: no-store."
            )
    return result
