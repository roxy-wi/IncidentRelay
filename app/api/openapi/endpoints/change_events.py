"""Experimental intake contract; this does not enable production ingestion."""

from app.api.openapi.common import json_body, response
from app.api.schemas.change_events import ChangeEventInput


def tags():
    return [
        {
            "name": "Change Events",
            "description": "Experimental machine intake, disabled by default.",
        }
    ]


def _openapi_schema(value):
    """Translate Pydantic's nullable/const definitions to OpenAPI 3.0."""
    if isinstance(value, list):
        return [_openapi_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {
        key: _openapi_schema(item) for key, item in value.items() if key != "$defs"
    }
    if "$ref" in result:
        result["$ref"] = result["$ref"].replace(
            "#/$defs/", "#/components/schemas/ChangeEvent"
        )
    if "const" in result:
        result["enum"] = [result.pop("const")]
    for boundary, inclusive in (
        ("exclusiveMinimum", "minimum"),
        ("exclusiveMaximum", "maximum"),
    ):
        if boundary in result and type(result[boundary]) in {int, float}:
            result[inclusive] = result[boundary]
            result[boundary] = True
    options = result.get("anyOf", [])
    if len(options) == 2 and {"type": "null"} in options:
        result.pop("anyOf")
        result.update(next(item for item in options if item != {"type": "null"}))
        result["nullable"] = True
    return result


def components():
    original = ChangeEventInput.model_json_schema()
    schemas = {
        f"ChangeEvent{name}": _openapi_schema(schema)
        for name, schema in original.get("$defs", {}).items()
    }
    request = _openapi_schema(original)
    for name in (
        "owner_team_id",
        "owner_team_slug",
        "source_sequence",
        "title",
        "actor",
    ):
        request["properties"][name].pop("nullable", None)
        request["properties"][name].pop("default", None)
    request["allOf"] = [
        {"oneOf": [{"required": ["owner_team_id"]}, {"required": ["owner_team_slug"]}]},
        {"not": {"required": ["changed_services", "changed_service_ids"]}},
        {"not": {"required": ["affected_services", "affected_service_ids"]}},
    ]
    reference = schemas["ChangeEventServiceReference"]
    for field in reference["properties"].values():
        field.pop("nullable", None)
        field.pop("default", None)
    reference["allOf"] = [
        {"oneOf": [{"required": ["service_id"]}, {"required": ["service_slug"]}]},
        {"not": {"required": ["team_id", "team_slug"]}},
    ]
    schemas["ChangeEventInput"] = request
    schemas["ChangeEventReceipt"] = {
        "type": "object",
        "properties": {
            "event_uid": {"type": "string", "format": "uuid"},
            "change_uid": {"type": "string", "format": "uuid"},
            "event_id": {"type": "string"},
            "change_id": {"type": "string"},
            "revision": {"type": "integer", "minimum": 1},
            "status": {
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
            "lifecycle_conflict": {"type": "boolean"},
            "mapping_status": {
                "type": "string",
                "enum": ["mapped", "partially_mapped", "unmapped", "mapping_failed"],
            },
            "references": {
                "type": "object",
                "properties": {
                    name: {"type": "integer", "minimum": 0}
                    for name in ("total", "resolved", "pending")
                },
            },
            "correlation_status": {"type": "string", "enum": ["queued", "not_enabled"]},
        },
    }
    return schemas


def paths():
    return {
        "/api/change-events": {
            "post": {
                "tags": ["Change Events"],
                "summary": "Persist one Change Event atomically (experimental)",
                "security": [{"bearerAuth": []}],
                "description": (
                    "Disabled by default. Global administrators can enable intake for internal acceptance in System settings. "
                    "Requires an active integration Bearer credential with changes:ingest even when global API auth is optional. "
                    "JWTs and personal tokens cannot ingest. Maximum body 256 KiB, 100 total references, details 64 KiB/10 levels/2000 nodes. "
                    "occurred_at requires a timezone and at most six fractional digits; default future skew is 300 seconds. "
                    "Sequence sources require a nonnegative integer source_sequence on every event; timestamp sources forbid it. "
                    "kind and environment are immutable per change_id; absent environment is null. Omitted title uses change_id until a title arrives. "
                    "Absent metadata preserves existing values; only description and external_url can be explicitly cleared. "
                    "Same-source event_id plus identical canonical content returns 200 without new writes/jobs; different content returns 409. "
                    "ID and slug forms remain distinct; reference sets are sorted/deduplicated and UTC timestamps normalized. "
                    "Slug namespaces are pinned to a Team ID; unknown authorized slugs remain pending. Reference-only affected claims are unverified. "
                    "Response includes safe counts, no Service metadata; correlation_status is queued when the worker is enabled, otherwise not_enabled. "
                    "Defaults: 600 accepted new events/minute/integration and 1000 events/change; exact retries are exempt. "
                    "No worker, correlation, read API or history cleanup is enabled by this endpoint."
                ),
                "requestBody": json_body(
                    "One immutable event",
                    {"$ref": "#/components/schemas/ChangeEventInput"},
                ),
                "responses": {
                    "201": response(
                        "Durably accepted; pending resolution is asynchronous",
                        {"$ref": "#/components/schemas/ChangeEventReceipt"},
                    ),
                    "200": response(
                        "Exact authorized retry; same event UID, current safe aggregate status",
                        {"$ref": "#/components/schemas/ChangeEventReceipt"},
                    ),
                    "400": response(
                        "Malformed/duplicate-key/non-finite JSON or wrong content type"
                    ),
                    "401": response("Active machine Bearer credential required"),
                    "403": response(
                        "Current source/namespace/capability access denied"
                    ),
                    "404": response("Intake disabled"),
                    "409": response("Event, sequence or operation identity conflict"),
                    "413": response("Body exceeds 256 KiB"),
                    "422": response("Invalid fields, time, identity or history limit"),
                    "429": response(
                        "Integration accepted-event quota exceeded; Retry-After: 60"
                    ),
                    "500": response(
                        "Acceptance could not be confirmed; retry the same event identity/content"
                    ),
                    "503": response(
                        "Database contention after three attempts; Retry-After: 1"
                    ),
                },
            }
        }
    }
