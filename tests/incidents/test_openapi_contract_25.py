"""Validate the published specification against real collaboration responses."""

import pytest
from openapi_schema_validator import OAS30Validator
from openapi_spec_validator import validate
from pydantic import ValidationError

from app.api.openapi.spec import build_openapi_spec
from app.api.schemas.incidents import (
    IncidentResponderCreateSchema,
    IncidentStakeholderCreateSchema,
    IncidentUpdateSchema,
)
from app.login import create_access_token
from tests.factories import (
    create_group,
    create_impact_alert_group,
    create_service,
    create_team,
    create_user,
)


def test_complete_openapi_document_is_valid():
    """Catch malformed schemas and unresolved references across the full API."""
    spec = build_openapi_spec()
    validate(spec)
    media = spec["paths"]["/api/services/{service_id}/slos"]["post"]["requestBody"][
        "content"
    ]["application/json"]
    for example in media["examples"].values():
        OAS30Validator(media["schema"]).validate(example["value"])


@pytest.mark.parametrize(
    "path, model, body, valid",
    [
        ("", IncidentUpdateSchema, {"row_version": 1, "root_cause": None}, True),
        ("", IncidentUpdateSchema, {"row_version": 1, "priority": None}, True),
        (
            "",
            IncidentUpdateSchema,
            {"row_version": 1, "resolution_summary": "a" * 10000},
            True,
        ),
        (
            "",
            IncidentUpdateSchema,
            {"row_version": 1, "root_cause": "a" * 10001},
            False,
        ),
        ("", IncidentUpdateSchema, {"root_cause": "reason"}, False),
        ("", IncidentUpdateSchema, {"row_version": 0}, False),
        ("", IncidentUpdateSchema, {"row_version": 1, "unexpected": True}, False),
        ("/stakeholders", IncidentStakeholderCreateSchema, {"user_id": 1}, True),
        (
            "/stakeholders",
            IncidentStakeholderCreateSchema,
            {"email": "a@example.com", "user_id": None},
            True,
        ),
        (
            "/stakeholders",
            IncidentStakeholderCreateSchema,
            {"user_id": 1, "email": None},
            True,
        ),
        ("/stakeholders", IncidentStakeholderCreateSchema, {}, False),
        ("/stakeholders", IncidentStakeholderCreateSchema, {"email": None}, False),
        ("/stakeholders", IncidentStakeholderCreateSchema, {"email": ""}, False),
        ("/stakeholders", IncidentStakeholderCreateSchema, {"email": "invalid"}, False),
        (
            "/stakeholders",
            IncidentStakeholderCreateSchema,
            {"user_id": 1, "email": "a@example.com"},
            False,
        ),
        (
            "/stakeholders",
            IncidentStakeholderCreateSchema,
            {"user_id": 1, "notify_on_comment": False},
            False,
        ),
        (
            "/responders",
            IncidentResponderCreateSchema,
            {"target_type": "user", "target_user_id": 1},
            True,
        ),
        (
            "/responders",
            IncidentResponderCreateSchema,
            {"target_type": "team", "target_team_id": 1, "target_user_id": None},
            True,
        ),
        (
            "/responders",
            IncidentResponderCreateSchema,
            {
                "target_type": "rotation",
                "target_rotation_id": 1,
                "expires_after_minutes": 10080,
            },
            True,
        ),
        (
            "/responders",
            IncidentResponderCreateSchema,
            {
                "target_type": "escalation_policy",
                "target_escalation_policy_id": 1,
                "expires_after_minutes": None,
            },
            True,
        ),
        ("/responders", IncidentResponderCreateSchema, {"target_type": "team"}, False),
        (
            "/responders",
            IncidentResponderCreateSchema,
            {"target_type": "team", "target_user_id": 1},
            False,
        ),
        (
            "/responders",
            IncidentResponderCreateSchema,
            {"target_type": "team", "target_team_id": None},
            False,
        ),
        (
            "/responders",
            IncidentResponderCreateSchema,
            {"target_type": "team", "target_team_id": 0},
            False,
        ),
        (
            "/responders",
            IncidentResponderCreateSchema,
            {"target_type": "team", "target_team_id": 1, "target_user_id": 2},
            False,
        ),
        (
            "/responders",
            IncidentResponderCreateSchema,
            {
                "target_type": "user",
                "target_user_id": 1,
                "expires_after_minutes": 10081,
            },
            False,
        ),
        (
            "/responders",
            IncidentResponderCreateSchema,
            {"target_type": "user", "target_user_id": 1, "message": "a" * 2001},
            False,
        ),
    ],
)
def test_openapi_request_constraints_match_runtime(path, model, body, valid):
    """Public constraints must accept nulls and reject invalid target combinations."""
    operation = build_openapi_spec()["paths"][f"/api/incidents/{{incident_id}}{path}"][
        "post" if path else "patch"
    ]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert OAS30Validator(schema).is_valid(body) is valid
    if valid:
        model.model_validate(body)
    else:
        with pytest.raises(ValidationError):
            model.model_validate(body)


def test_incident_workspace_responses_follow_published_contract(
    client, db, monkeypatch
):
    """Exercise create, read, conflict and repeat responses, not hand-built samples."""
    monkeypatch.setattr(
        "app.services.notifications.incidents.dispatch_event", lambda *a, **k: 0
    )
    group = create_group()
    team = create_team(group)
    actor = create_user(group=group, is_admin=True)
    participant = create_user(group=group)
    service = create_service(team)
    technical = create_impact_alert_group(team=team, service=service)
    token, _ = create_access_token(actor)
    headers = {"Authorization": f"Bearer {token}"}
    paths = build_openapi_spec()["paths"]

    def request(method, path, expected, *, payload=None, **ids):
        response = client.open(
            path.format(**ids), method=method, json=payload, headers=headers
        )
        assert response.status_code == expected, response.get_json()
        documented = paths[path][method.lower()]["responses"][str(expected)]
        if expected != 204:
            schema = documented["content"]["application/json"]["schema"]
            OAS30Validator(
                schema, format_checker=OAS30Validator.FORMAT_CHECKER
            ).validate(response.get_json())
        return response.get_json(silent=True)

    incident = request(
        "POST", "/api/incidents", 201, payload={"team_id": team.id, "title": "Contract"}
    )
    ids = {"incident_id": incident["id"]}
    base = "/api/incidents/{incident_id}"
    request("GET", "/api/incidents", 200)
    updated = request(
        "PATCH",
        base,
        200,
        **ids,
        payload={
            "row_version": incident["row_version"],
            "root_cause": "Broken dependency",
            "resolution_summary": "Restored dependency",
        },
    )
    assert updated["root_cause"] == "Broken dependency"
    request(
        "PATCH",
        base,
        409,
        **ids,
        payload={"row_version": incident["row_version"], "title": "Stale"},
    )
    assignment = request(
        "POST",
        base + "/participants",
        201,
        **ids,
        payload={"user_id": participant.id, "role": "commander"},
    )
    request(
        "POST",
        base + "/participants",
        409,
        **ids,
        payload={"user_id": participant.id, "role": "commander"},
    )
    request(
        "POST",
        base + "/participants",
        201,
        **ids,
        payload={"user_id": participant.id, "role": "communications"},
    )
    stakeholder = request(
        "POST",
        base + "/stakeholders",
        201,
        **ids,
        payload={"email": "observer@example.com"},
    )
    repeated = request(
        "POST",
        base + "/stakeholders",
        200,
        **ids,
        payload={"email": "OBSERVER@example.com"},
    )
    assert repeated["id"] == stakeholder["id"]
    request(
        "POST",
        base + "/responders",
        201,
        **ids,
        payload={"target_type": "user", "target_user_id": actor.id},
    )
    center = request("GET", "/api/notification-center", 200)
    assert center["items"][0]["incident_id"] == incident["id"]
    assert center["items"][0]["url"] == f"/incidents/{incident['id']}"
    request(
        "POST", base + "/comments", 201, **ids, payload={"body": "Operational note"}
    )
    for status in (201, 200):
        request(
            "POST",
            base + "/affected-services",
            status,
            **ids,
            payload={"service_id": service.id},
        )
    request(
        "POST",
        base + "/alert-groups",
        201,
        **ids,
        payload={"alert_group_id": technical.id},
    )
    for suffix in (
        "",
        "/participants",
        "/stakeholders",
        "/responders",
        "/comments",
        "/affected-services",
        "/alert-groups",
        "/events",
        "/activity",
    ):
        request("GET", base + suffix, 200, **ids)
    request(
        "DELETE", base + "/alert-groups/{group_id}", 200, **ids, group_id=technical.id
    )
    request(
        "DELETE",
        base + "/participants/{participant_id}",
        204,
        **ids,
        participant_id=assignment["id"],
    )
    request(
        "DELETE",
        base + "/stakeholders/{stakeholder_id}",
        204,
        **ids,
        stakeholder_id=stakeholder["id"],
    )
    request(
        "POST",
        base + "/stakeholders",
        201,
        **ids,
        payload={"email": "observer@example.com"},
    )
