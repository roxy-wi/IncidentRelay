from app.modules.db.models import (
    ServiceReadinessEvaluation,
    ServiceReadinessState,
    ServiceStandard,
    ServiceStandardCheck,
)
from tests.factories import create_group, create_service, create_team, create_user
from app.services.service_catalog.reconciliation import reconcile_service_readiness


def create_name_standard(group):
    standard = ServiceStandard.create(
        group=group,
        slug="basic-readiness",
        name="Basic readiness",
    )
    ServiceStandardCheck.create(
        standard=standard,
        slug="name-present",
        name="Name present",
        check_type="field_present",
        configuration={"field": "name"},
        weight=10,
        severity="critical",
        required=True,
    )

    return standard


def test_get_service_readiness_returns_empty_state_before_evaluation(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    response = client.get(
        f"/api/services/{service.id}/readiness",
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "service_id": service.id,
        "state": None,
        "evaluations": [],
    }


def test_evaluate_service_readiness_api(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    standard = create_name_standard(group)

    response = client.post(
        f"/api/services/{service.id}/readiness/evaluate",
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()

    assert payload["service_id"] == service.id
    assert payload["state"]["status"] == "ready"
    assert payload["state"]["score"] == 100
    assert payload["state"]["standards_count"] == 1
    assert payload["state"]["checks_count"] == 1
    assert len(payload["evaluations"]) == 1

    evaluation = payload["evaluations"][0]

    assert evaluation["standard"]["id"] == standard.id
    assert evaluation["status"] == "ready"
    assert evaluation["score"] == 100
    assert evaluation["results"][0]["check_slug"] == "name-present"
    assert evaluation["results"][0]["status"] == "passed"


def test_get_service_readiness_returns_current_batch(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    create_name_standard(group)

    first_response = client.post(
        f"/api/services/{service.id}/readiness/evaluate",
        headers=admin_headers,
    )
    second_response = client.post(
        f"/api/services/{service.id}/readiness/evaluate",
        headers=admin_headers,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    response = client.get(
        f"/api/services/{service.id}/readiness",
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()
    state = ServiceReadinessState.get(
        ServiceReadinessState.service == service.id
    )

    assert payload["state"]["batch_uid"] == str(state.batch_uid)
    assert len(payload["evaluations"]) == 1
    assert payload["evaluations"][0]["batch_uid"] == str(state.batch_uid)
    assert ServiceReadinessEvaluation.select().where(
        ServiceReadinessEvaluation.service == service.id
    ).count() == 2


def test_service_list_includes_readiness_state(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    create_name_standard(group)

    evaluation_response = client.post(
        f"/api/services/{service.id}/readiness/evaluate",
        headers=admin_headers,
    )

    assert evaluation_response.status_code == 200

    response = client.get(
        f"/api/services?team_id={team.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200

    serialized_service = next(
        item for item in response.get_json() if item["id"] == service.id
    )

    assert serialized_service["uid"] == str(service.uid)
    assert serialized_service["kind"] == "technical"
    assert serialized_service["lifecycle"] == "production"
    assert serialized_service["readiness"]["status"] == "ready"
    assert serialized_service["readiness"]["score"] == 100


def test_service_details_include_readiness(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    create_name_standard(group)

    client.post(
        f"/api/services/{service.id}/readiness/evaluate",
        headers=admin_headers,
    )

    response = client.get(
        f"/api/services/{service.id}/details",
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()

    assert payload["service"]["readiness"]["status"] == "ready"
    assert payload["summary"]["readiness"]["score"] == 100
    assert payload["readiness"]["state"]["status"] == "ready"
    assert len(payload["readiness"]["evaluations"]) == 1


def test_readiness_evaluation_requires_existing_service(
    client,
    admin_headers,
):
    response = client.post(
        "/api/services/999999/readiness/evaluate",
        headers=admin_headers,
    )

    assert response.status_code == 404
    assert response.get_json()["error"] == "service_not_found"


def test_service_create_automatically_evaluates_readiness(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)
    create_name_standard(group)

    response = client.post(
        "/api/services",
        json={
            "team_id": team.id,
            "slug": "billing-api",
            "name": "Billing API",
            "description": None,
            "kind": "technical",
            "lifecycle": "production",
            "service_type": "api",
            "environment": "production",
            "criticality": "critical",
            "tier": "tier_1",
            "status": "operational",
            "status_source": "manual",
            "status_message": None,
            "default_rotation_id": None,
            "default_escalation_policy_id": None,
            "notification_policy_id": None,
            "priority_policy_id": None,
            "labels": {},
            "tags": [],
            "metadata": {},
            "enabled": True,
            "public": False,
            "public_name": None,
            "public_description": None,
            "public_order": 100,
        },
        headers=admin_headers,
    )

    assert response.status_code == 201
    assert response.get_json()["readiness"]["status"] == "ready"
    assert response.get_json()["readiness"]["score"] == 100


def test_creating_service_owner_recalculates_readiness(client, admin_headers):
    group = create_group()
    team = create_team(group)
    user = create_user(group=group)
    service = create_service(team)
    standard = ServiceStandard.create(
        group=group,
        slug="owner-required",
        name="Owner required",
    )

    ServiceStandardCheck.create(
        standard=standard,
        slug="owner-exists",
        name="Owner exists",
        check_type="owner_exists",
        configuration={"roles": ["owner"]},
        severity="critical",
        required=True,
    )

    reconcile_service_readiness(service, trigger="test")

    state = ServiceReadinessState.get(
        ServiceReadinessState.service == service.id
    )

    assert state.status == "not_ready"

    response = client.post(
        f"/api/services/{service.id}/owners",
        json={
            "user_id": user.id,
            "role": "owner",
            "active": True,
            "notify_on_created": True,
            "notify_on_priority_change": True,
            "notify_on_status_change": True,
            "notify_on_resolved": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 201

    state = ServiceReadinessState.get(
        ServiceReadinessState.service == service.id
    )

    assert state.status == "ready"
    assert state.score == 100
