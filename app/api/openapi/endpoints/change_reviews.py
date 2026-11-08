"""Human review and Incident links with explicit dual-scope authorization."""

from app.api.openapi.common import json_body, query_param, response
from app.api.openapi.endpoints.change_events import _openapi_schema
from app.api.openapi.endpoints.changes import ID, TEXT, TIME, object_schema, page_schema
from app.api.schemas.change_reviews import (
    CorrelationCreate,
    CorrelationReview,
    IncidentChangeCreate,
    IncidentChangeRemove,
    IncidentChangeUpdate,
)


def tags():
    return []


def components():
    """Keep request validation and response whitelists reviewable together."""
    episode = object_schema(
        {
            "id": ID,
            "alert_group_id": ID,
            "title": TEXT,
            "ordinal": ID,
            "state": TEXT,
            "started_at": TIME,
            "ended_at": TIME,
        }
    )
    correlation = object_schema(
        {
            "id": ID,
            "episode": episode,
            "review_status": TEXT,
            "relation_type": TEXT,
            "row_version": ID,
            "score": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "nullable": True,
            },
            "suggestion_current": {"type": "boolean"},
            "evidence_version": {**TEXT, "nullable": True},
            "reviewed_by": {**ID, "nullable": True},
            "reviewed_at": TIME,
            "review_evidence": {
                "type": "object",
                "nullable": True,
                "description": "Immutable reader-scoped decision snapshot. Private Change fields and inaccessible Services are redacted on every read. Raw graph paths are never returned.",
            },
            "can_review": {"type": "boolean"},
        }
    )
    link = object_schema(
        {
            "id": ID,
            "change": {"$ref": "#/components/schemas/ChangeRead"},
            "incident": object_schema({"id": ID, "title": TEXT}),
            "relation_type": TEXT,
            "row_version": ID,
            "linked_by": {**ID, "nullable": True},
            "linked_at": TIME,
            "removed_by": {**ID, "nullable": True},
            "removed_at": TIME,
            "can_manage": {"type": "boolean"},
        }
    )
    requests = {
        cls.__name__: _openapi_schema(cls.model_json_schema())
        for cls in (
            CorrelationCreate,
            CorrelationReview,
            IncidentChangeCreate,
            IncidentChangeUpdate,
            IncidentChangeRemove,
        )
    }
    alert_changes = page_schema(
        object_schema(
            {
                **correlation["properties"],
                "change": {"$ref": "#/components/schemas/ChangeRead"},
            }
        )
    )
    alert_changes["properties"].update(
        episode={**episode, "nullable": True},
        eligibility=TEXT,
        can_review={"type": "boolean"},
    )
    alert_changes["required"] += ["episode", "eligibility", "can_review"]
    return {
        **requests,
        "ChangeReviewConflict": object_schema(
            {
                "error": {"type": "string", "enum": ["conflict"]},
                "message": TEXT,
                "reason": {
                    "type": "string",
                    "description": "Stable conflict reason for localized recovery guidance. Unknown future reasons must use a generic conflict message.",
                    "enum": [
                        "relation_exists",
                        "relation_changed",
                        "suggestion_stale",
                        "evidence_changed",
                        "incident_role_conflict",
                        "incident_link_removed",
                        "incident_link_changed",
                        "incident_link_missing",
                        "incident_changed",
                    ],
                },
            }
        ),
        "ChangeCorrelation": correlation,
        "ChangeCorrelationPage": page_schema(correlation),
        "ChangeCorrelationTargetPage": page_schema(
            object_schema(
                {
                    **episode["properties"],
                    "can_review": {"type": "boolean"},
                }
            )
        ),
        "ChangeIncidentLink": link,
        "ChangeIncidentLinkPage": page_schema(link),
        "AlertEpisodePage": page_schema(episode),
        "AlertRelatedChangesPage": alert_changes,
    }


def paths():
    """Mutations require responder RBAC, changes:write and target write scope."""
    changes = "/api/changes/{change_uid}"
    incidents = "/api/incidents/{incident_id}/changes"
    routes = [
        (
            "/api/alert-groups/{alert_group_id}/episodes",
            "get",
            None,
            "AlertEpisodePage",
            "alerts:read",
        ),
        (
            "/api/alert-groups/{alert_group_id}/related-changes",
            "get",
            None,
            "AlertRelatedChangesPage",
            "alerts:read",
        ),
        (
            changes + "/correlations",
            "get",
            None,
            "ChangeCorrelationPage",
            "alerts:read",
        ),
        (
            changes + "/correlation-targets",
            "get",
            None,
            "ChangeCorrelationTargetPage",
            "alerts:read",
        ),
        (
            changes + "/correlations",
            "post",
            "CorrelationCreate",
            "ChangeCorrelation",
            "alerts:write",
        ),
        (
            changes + "/correlations/{correlation_id}/review",
            "post",
            "CorrelationReview",
            "ChangeCorrelation",
            "alerts:write",
        ),
        (
            changes + "/incidents",
            "get",
            None,
            "ChangeIncidentLinkPage",
            "incidents:read",
        ),
        (incidents, "get", None, "ChangeIncidentLinkPage", "incidents:read"),
        (
            incidents,
            "post",
            "IncidentChangeCreate",
            "ChangeIncidentLink",
            "incidents:write",
        ),
        (
            incidents + "/{link_id}",
            "patch",
            "IncidentChangeUpdate",
            "ChangeIncidentLink",
            "incidents:write",
        ),
        (
            incidents + "/{link_id}",
            "delete",
            "IncidentChangeRemove",
            "ChangeIncidentLink",
            "incidents:write",
        ),
    ]
    result = {}
    for path, method, request_schema, result_schema, target_scope in routes:
        parameters = []
        for name in (
            "change_uid",
            "incident_id",
            "correlation_id",
            "link_id",
            "alert_group_id",
        ):
            if "{" + name + "}" in path:
                parameters.append(
                    {
                        "name": name,
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string", "format": "uuid"}
                        if name == "change_uid"
                        else ID,
                    }
                )
        reading = method == "get"
        description = (
            "Human JWT or personal token only; machine tokens are rejected. "
            + (
                "Requires changes:read and "
                if reading
                else "Requires changes:write and "
            )
            + target_scope
            + ". Group/Team token restrictions apply to both ends. "
            "Incident links never grant access to the linked Change. "
        )
        if reading:
            description += "Visibility is filtered before pagination/counts. Cache-Control: no-store."
            parameters += [
                query_param(
                    "page", "Page number", {**ID, "maximum": 1000000, "default": 1}
                ),
                query_param(
                    "page_size", "Rows per page", {**ID, "maximum": 100, "default": 25}
                ),
            ]
            if "related-changes" in path:
                parameters.append(
                    query_param(
                        "episode_id",
                        "Existing episode of this AlertGroup; defaults to its latest tracked episode",
                        ID,
                    )
                )
                description += " Legacy groups return episode=null; reads never create episodes. Eligibility reports why automatic suggestions are skipped; manual linking remains independent."
            elif "correlation-targets" in path:
                parameters.append(
                    query_param(
                        "search",
                        "AlertGroup title; only existing episodes",
                        {**TEXT, "maxLength": 200},
                    )
                )
            elif "incidents" in path:
                parameters.append(
                    query_param(
                        "include_removed",
                        "Include removed links and their restore versions",
                        {"type": "boolean", "default": False},
                    )
                )
        else:
            description += (
                "Requires responder permission on the target. Link/decision, Incident event/CAS "
                "where applicable, and audit are atomic. No status or notification changes. "
                "A nonempty note is required. Stale row_version returns 409. "
            )
            if request_schema == "CorrelationReview":
                description += "Reviewing an automatic suggestion also requires its evidence_version. Explicit manual=true permits a manual decision without a current automatic candidate."
            if request_schema == "IncidentChangeCreate":
                description += "New/restored link: 201. Same active role: 200 without duplicate event/audit. Different active role: 409. Restore requires the removed link's row_version."
        operation = {
            "tags": ["Changes"],
            "summary": result_schema if reading else request_schema,
            "description": description,
            "parameters": parameters,
            "responses": {
                "200": response(
                    "Visible data or accepted decision",
                    {"$ref": "#/components/schemas/" + result_schema},
                ),
                **(
                    {
                        "201": response(
                            "Relation created or restored",
                            {"$ref": "#/components/schemas/" + result_schema},
                        )
                    }
                    if request_schema in {"CorrelationCreate", "IncidentChangeCreate"}
                    else {}
                ),
                "400": response("Invalid input"),
                "401": response("Authentication required"),
                "403": response("Missing scope or responder role"),
                "404": response("Resource unavailable"),
                **(
                    {
                        "409": response(
                            "Conflict with a stable reason; no mutation is saved",
                            {"$ref": "#/components/schemas/ChangeReviewConflict"},
                        )
                    }
                    if not reading
                    else {}
                ),
            },
        }
        if request_schema:
            operation["requestBody"] = json_body(
                "Manual decision and the version shown to the operator",
                {"$ref": "#/components/schemas/" + request_schema},
            )
        result.setdefault(path, {})[method] = operation
    return result
