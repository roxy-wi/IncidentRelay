"""JWT administration of Change Intelligence integrations."""

from app.api.openapi.common import json_body, path_param, response

BASE = "/api/admin/change-integrations"
ID = {"type": "integer", "minimum": 1}
NAME = {"type": "string", "minLength": 1, "maxLength": 255}
ACTIVE = {"type": "boolean"}
ORDER = {"type": "string", "enum": ["timestamp", "sequence"]}


def tags():
    return [
        {
            "name": "Change integrations",
            "description": "Global or Group user_admin JWT required; personal and machine API tokens are rejected.",
        }
    ]


def body(properties, required):
    return json_body(
        "Configuration mutation",
        {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": required,
        },
    )


def operation(summary, *, properties=None, required=None, created=False):
    result = {
        "tags": ["Change integrations"],
        "summary": summary,
        "security": [{"bearerAuth": []}],
        "description": "Requires a current global administrator or Group user_admin JWT, even with global API auth disabled. Group administrators manage only identities owned by their active Groups. Central identities remain global-only. owner_group_id is immutable; null means central. Sources and grants of Group-owned identities must stay within that Group. Mutations are audited. Permission edits require the current auth_revision as expected_revision; stale edits return 409. Responses are not cached.",
        "responses": {
            "201" if created else "200": response(
                "Created" if created else "Configuration returned"
            ),
            "400": response("Invalid body"),
            "401": response("Administrator JWT required"),
            "403": response("Access denied"),
            "404": response("Configuration not found"),
            "409": response(
                "Stale revision, reserved namespace, or already rotated credential"
            ),
        },
    }
    if properties is not None:
        result["requestBody"] = body(properties, required or [])
    return result


def paths():
    revision = {"expected_revision": ID}
    token_fields = {
        **revision,
        "name": NAME,
        "days": {"type": "integer", "minimum": 1, "maximum": 3650, "default": 90},
    }
    result = {
        BASE: {
            "get": operation(
                "List identities with source_count and permission_count, including disabled entries (100 per page; after ID cursor)"
            ),
            "post": operation(
                "Create integration and one default source atomically; no implicit permissions",
                properties={
                    "name": NAME,
                    "owner_group_id": {**ID, "nullable": True},
                    "owner_team_id": ID,
                },
                required=["name", "owner_team_id"],
                created=True,
            ),
        },
        BASE + "/targets": {
            "get": operation(
                "List permitted owner Groups and Teams; integration_id limits Teams to its owner Group; team_id lists permitted Services"
            )
        },
        BASE + "/{integration_id}": {
            "get": operation(
                "Get integration, sources, grants and credential metadata, including visible Team/Service names and slugs; unavailable catalog names are null; never secrets or hashes"
            ),
            "patch": operation(
                "Update integration name/activity",
                properties={**revision, "name": NAME, "active": ACTIVE},
                required=["expected_revision"],
            ),
        },
        BASE + "/{integration_id}/sources": {
            "post": operation(
                "Reserve an owner/source namespace",
                properties={
                    **revision,
                    "owner_team_id": ID,
                    "source": NAME,
                    "ordering_mode": ORDER,
                },
                required=["expected_revision", "owner_team_id", "source"],
                created=True,
            )
        },
        BASE + "/{integration_id}/sources/{source_id}": {
            "patch": operation(
                "Edit source; name and owner Team are editable only before its first Change (409 otherwise); identity_editable is returned in source metadata",
                properties={
                    **revision,
                    "active": ACTIVE,
                    "ordering_mode": ORDER,
                    "source": NAME,
                    "owner_team_id": ID,
                },
                required=["expected_revision"],
            )
        },
        BASE + "/{integration_id}/sources/{source_id}/grants": {
            "post": operation(
                "Grant claim or lookup authority",
                properties={
                    **revision,
                    "capability": {
                        "type": "string",
                        "enum": ["reference", "changed", "reported_affected"],
                    },
                    "target_team_id": ID,
                    "target_service_id": {**ID, "nullable": True},
                },
                required=["expected_revision", "capability", "target_team_id"],
                created=True,
            )
        },
        BASE + "/{integration_id}/sources/{source_id}/grants/{grant_id}": {
            "patch": operation(
                "Edit permission atomically with previous settings in audit; explicit null Service grants the whole Team; duplicates return 409",
                properties={
                    **revision,
                    "active": ACTIVE,
                    "source_id": ID,
                    "capability": {
                        "type": "string",
                        "enum": ["reference", "changed", "reported_affected"],
                    },
                    "target_team_id": ID,
                    "target_service_id": {**ID, "nullable": True},
                },
                required=["expected_revision"],
            )
        },
        BASE + "/{integration_id}/tokens": {
            "post": operation(
                "Issue changes:ingest credential; raw token returned once in token, metadata in credential",
                properties=token_fields,
                required=["expected_revision", "name"],
                created=True,
            )
        },
        BASE + "/{integration_id}/tokens/{token_id}/rotate": {
            "post": operation(
                "Atomically issue replacement and revoke old credential; auth_revision and accepted event ownership remain unchanged",
                properties=token_fields,
                required=["expected_revision", "name"],
                created=True,
            )
        },
        BASE + "/{integration_id}/tokens/{token_id}/revoke": {
            "post": operation(
                "Revoke new intake only; retain accepted work and event ownership",
                properties=revision,
                required=["expected_revision"],
            )
        },
    }
    for prefix in (BASE, BASE + "/{integration_id}"):
        result[prefix + "/jobs"] = {
            "get": operation(
                "List queue metadata only; root listing requires a global administrator"
            )
        }
        result[prefix + "/jobs/{job_id}/retry"] = {
            "post": operation(
                "Audited retry of a job and blocked references; keeps pinned identities; root endpoint requires a global administrator",
                properties={"expected_generation": ID},
                required=["expected_generation"],
            )
        }
        for method in (
            result[prefix + "/jobs"]["get"],
            result[prefix + "/jobs/{job_id}/retry"]["post"],
        ):
            method["description"] = (
                "JWT only, even when API authentication is optional. Global administrators manage all jobs; "
                "Group user_admin members use the integration-scoped route for their own Group. "
                "Listing returns up to 50 queue metadata records, without event payloads, Services or lease credentials. "
                "Retry requires expected_generation; a stale generation returns 409. It renews the pending window "
                "for blocked unresolved references and records an audit, retaining original identities and canonical IDs. "
                "Current source/grants are rechecked by the worker. Responses are not cached."
            )
    for path, methods in result.items():
        for operation_data in methods.values():
            operation_data["parameters"] = [
                path_param(name, name)
                for name in [
                    "integration_id",
                    "source_id",
                    "grant_id",
                    "token_id",
                    "job_id",
                ]
                if "{" + name + "}" in path
            ]
    result[BASE]["get"]["parameters"] = [
        {"name": "after", "in": "query", "schema": {"type": "integer", "minimum": 0}}
    ]
    result[BASE + "/targets"]["get"]["parameters"] = [
        {"name": "team_id", "in": "query", "schema": ID},
        {"name": "integration_id", "in": "query", "schema": ID},
    ]
    for prefix in (BASE, BASE + "/{integration_id}"):
        result[prefix + "/jobs"]["get"]["parameters"].extend(
            [
                {
                    "name": "after",
                    "in": "query",
                    "schema": {"type": "integer", "minimum": 0},
                },
                {
                    "name": "state",
                    "in": "query",
                    "schema": {
                        "type": "string",
                        "enum": ["pending", "running", "done", "dead"],
                    },
                },
            ]
        )
    return result
