"""New routes have exact scope mappings and truthful OpenAPI response shapes."""

import pytest
from openapi_schema_validator import OAS30Validator

from app.api.openapi.spec import build_openapi_spec
from app.services.api_token_scopes import required_scopes_for_path
from tests.integrations.test_change_reviews import (
    base,
    headers,
    incident_url,
    intake,
    link_body,
    review_body,
    review_case,
    review_url,
    setup_identity,
)

__all__ = ["intake", "review_case", "setup_identity"]

CHANGE_PATH = "/api/changes/00000000-0000-0000-0000-000000000001"


@pytest.mark.parametrize(
    "path,method,expected",
    [
        (CHANGE_PATH + "/correlations", "GET", ["changes:read", "alerts:read"]),
        (CHANGE_PATH + "/correlation-targets", "GET", ["changes:read", "alerts:read"]),
        (
            CHANGE_PATH + "/correlations/1/review",
            "POST",
            ["changes:write", "alerts:write"],
        ),
        (CHANGE_PATH + "/incidents", "GET", ["changes:read", "incidents:read"]),
        ("/api/incidents/1/changes", "GET", ["changes:read", "incidents:read"]),
        ("/api/incidents/1/changes", "POST", ["changes:write", "incidents:write"]),
        ("/api/incidents/1/changes/1", "PATCH", ["changes:write", "incidents:write"]),
        ("/api/incidents/1/changes/1", "DELETE", ["changes:write", "incidents:write"]),
        ("/api/incidents/1/changes/1", "PUT", None),
        ("/api/incidents/1/changes/private", "GET", None),
        ("/api/incidents/1/changes/1/private", "POST", None),
        (CHANGE_PATH + "/correlations/1/private", "POST", None),
    ],
)
def test_review_scope_routes_are_explicit(path, method, expected):
    assert required_scopes_for_path(path, method) == expected


def test_review_and_incident_responses_match_openapi(client, review_case):
    case = review_case
    spec = build_openapi_spec()
    auth = headers(case.user)
    cases = [
        (
            client.get(base(case) + "/correlations", headers=auth),
            "ChangeCorrelationPage",
        ),
        (
            client.get(base(case) + "/correlation-targets", headers=auth),
            "ChangeCorrelationTargetPage",
        ),
        (
            client.post(review_url(case), headers=auth, json=review_body(case)),
            "ChangeCorrelation",
        ),
        (
            client.post(incident_url(case), headers=auth, json=link_body(case)),
            "ChangeIncidentLink",
        ),
        (client.get(incident_url(case), headers=auth), "ChangeIncidentLinkPage"),
        (
            client.post(review_url(case), headers=auth, json=review_body(case)),
            "ChangeReviewConflict",
        ),
    ]
    for response, name in cases:
        if name == "ChangeReviewConflict":
            assert response.status_code == 409, response.json
            assert response.json["reason"] == "relation_changed"
        else:
            assert response.status_code in (200, 201), response.json
        OAS30Validator(
            {
                "$ref": "#/components/schemas/" + name,
                "components": spec["components"],
            },
            format_checker=OAS30Validator.FORMAT_CHECKER,
        ).validate(response.json)


def test_all_review_mutations_document_conflict_reasons():
    spec = build_openapi_spec()
    for path, method in (
        ("/api/changes/{change_uid}/correlations", "post"),
        ("/api/changes/{change_uid}/correlations/{correlation_id}/review", "post"),
        ("/api/incidents/{incident_id}/changes", "post"),
        ("/api/incidents/{incident_id}/changes/{link_id}", "patch"),
        ("/api/incidents/{incident_id}/changes/{link_id}", "delete"),
    ):
        schema = spec["paths"][path][method]["responses"]["409"]["content"][
            "application/json"
        ]["schema"]
        assert schema == {"$ref": "#/components/schemas/ChangeReviewConflict"}
