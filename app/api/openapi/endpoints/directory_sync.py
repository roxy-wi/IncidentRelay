"""Configurable directory sync administration, including personal token access."""

from app.api.openapi.common import json_body, path_param, query_param, response
from app.services.directory_sync.config import SyncConfig
from app.services.directory_sync.shift_editor import ShiftInput

TAG = "Directory synchronization"
ROOT = "/api/admin/directory-sync"


def tags():
    return [{"name": TAG, "description": "Group-owned team, user and on-call imports with preview."}]


def components():
    """Expose the same configuration contract that validates API writes."""
    schema = SyncConfig.model_json_schema(ref_template="#/components/schemas/DirectorySync{model}")
    definitions = schema.pop("$defs", {})
    shift = ShiftInput.model_json_schema(ref_template="#/components/schemas/DirectorySync{model}")
    definitions.update(shift.pop("$defs", {}))

    def convert(value):
        if isinstance(value, list):
            return [convert(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: convert(item) for key, item in value.items()}
        choices = result.get("anyOf", [])
        if any(item == {"type": "null"} for item in choices):
            choices = [item for item in choices if item != {"type": "null"}]
            result.pop("anyOf")
            result.update(choices[0] if len(choices) == 1 else {"anyOf": choices})
            result["nullable"] = True
        return result

    return {"DirectorySyncConfig": convert(schema), "DirectorySyncShiftInput": convert(shift),
            **{"DirectorySync" + key: convert(value) for key, value in definitions.items()}}


def paths():
    config = {"type": "object", "required": ["name", "group_id", "config"], "additionalProperties": False,
              "properties": {"name": {"type": "string", "maxLength": 255}, "group_id": {"type": "integer"},
                             "config": {"$ref": "#/components/schemas/DirectorySyncConfig"},
                             "headers": {"type": "object", "additionalProperties": {"type": "string"}, "writeOnly": True},
                             "enabled": {"type": "boolean", "default": False}, "revision": {"type": "integer"}}}
    common = {"tags": [TAG], "security": [{"bearerAuth": []}],
              "description": "Requires global admin or destination Group user_admin. Personal tokens require directory-sync:read/write; team-bound tokens are denied. Headers are encrypted and never returned.",
              "responses": {"200": response("Result"), "400": response("Invalid configuration"),
                            "401": response("Authentication required"), "403": response("Access denied"),
                            "404": response("Not found"), "409": response("Busy, stale revision or conflict")}}
    result = {
        ROOT: {"get": {**common, "summary": "List visible synchronization sources"},
               "post": {**common, "summary": "Create a disabled source", "requestBody": json_body("Source", config),
                        "responses": {**common["responses"], "201": response("Created")}}},
        ROOT + "/options": {"get": {**common, "summary": "Get managed groups, teams and the editable org-service preset"}},
        ROOT + "/{source_id}": {"parameters": [path_param("source_id", "Source ID")],
                               "get": {**common, "summary": "Read configuration, queue and preview status"},
                               "put": {**common, "summary": "Update using the last read revision", "requestBody": json_body("Source", config)}},
        ROOT + "/{source_id}/sample": {"parameters": [path_param("source_id", "Source ID")],
                                       "post": {**common, "summary": "Inspect response field names and types",
                                                "responses": {**common["responses"],
                                                              "502": response("External API failure (sync_api_error)"),
                                                              "504": response("External API timeout (sync_api_error)")}}},
    }
    for action in ("preview", "apply", "run"):
        result[ROOT + "/{source_id}/" + action] = {
            "parameters": [path_param("source_id", "Source ID")],
            "post": {**common, "summary": f"Queue {action}; poll the source for completion",
                     "requestBody": json_body("Revision and preview token", {
                         "type": "object", "required": ["revision"],
                         "properties": {"revision": {"type": "integer"}, "preview_token": {"type": "string"}}}),
                     "responses": {**common["responses"], "202": response("Queued for the scheduler")}},
        }
    shift_common = {**common, "description": "Uses existing rotation team access and rotations:read/write token scopes. Writes require an editable synchronization source. Times require explicit timezones; user IDs are local IR users imported by this source."}
    body = json_body("Concrete shift and replacements", {"$ref": "#/components/schemas/DirectorySyncShiftInput"})
    result["/api/rotations/{rotation_id}/imported-shifts"] = {
        "parameters": [path_param("rotation_id", "Rotation ID")],
        "get": {**shift_common, "summary": "List up to 100 imported shifts and eligible people",
                "parameters": [query_param("after", "Previous next_cursor", {"type": "integer", "minimum": 0})]},
        "post": {**shift_common, "summary": "Add a local shift", "requestBody": body,
                 "responses": {**common["responses"], "201": response("Created")}},
    }
    result["/api/rotations/imported-shifts/{shift_id}"] = {
        "parameters": [path_param("shift_id", "Imported shift ID")],
        "put": {**shift_common, "summary": "Edit a concrete shift", "requestBody": body},
        "delete": {**shift_common, "summary": "Suppress an imported shift until synchronization restores it"},
    }
    return result
