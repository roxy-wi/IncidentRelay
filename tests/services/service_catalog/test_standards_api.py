from app.modules.db.models import ServiceStandard, ServiceStandardCheck
from tests.factories import create_group, create_team, create_service
from app.modules.db.models import ServiceReadinessState
from app.services.service_catalog.presets import BASIC_OPERATIONAL_STANDARD_SLUG


def standard_payload(group, **overrides):
    payload = {
        "group_id": group.id,
        "slug": "production-tier-one",
        "name": "Production Tier One",
        "description": "Requirements for production Tier 1 services",
        "applies_to": {
            "kinds": ["technical"],
            "lifecycles": ["production"],
            "tiers": ["tier_1"],
        },
        "enabled": True,
    }
    payload.update(overrides)
    return payload


def standard_update_payload(**overrides):
    payload = {
        "slug": "production-tier-one",
        "name": "Production Tier One",
        "description": "Updated production requirements",
        "applies_to": {
            "kinds": ["technical"],
            "lifecycles": ["production"],
            "tiers": ["tier_1"],
        },
        "enabled": True,
    }
    payload.update(overrides)
    return payload


def check_payload(**overrides):
    payload = {
        "slug": "owner-exists",
        "name": "Owner exists",
        "description": "Service must have an active owner",
        "check_type": "owner_exists",
        "configuration": {
            "roles": ["owner"],
            "minimum": 1,
        },
        "weight": 10,
        "severity": "critical",
        "required": True,
        "enabled": True,
        "position": 10,
    }
    payload.update(overrides)
    return payload


def test_create_and_list_service_standards_api(client, admin_headers):
    group = create_group()

    response = client.post(
        "/api/services/standards",
        json=standard_payload(group),
        headers=admin_headers,
    )

    assert response.status_code == 201

    standard = response.get_json()

    assert standard["id"]
    assert standard["group_id"] == group.id
    assert standard["slug"] == "production-tier-one"
    assert standard["checks"] == []
    assert standard["checks_count"] == 0

    response = client.get(
        f"/api/services/standards?group_id={group.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.get_json()] == [standard["id"]]


def test_update_and_delete_service_standard_api(client, admin_headers):
    group = create_group()
    standard = ServiceStandard.create(
        group=group,
        slug="production",
        name="Production",
    )

    response = client.put(
        f"/api/services/standards/{standard.id}",
        json=standard_update_payload(
            slug="production",
            name="Updated Production",
            enabled=False,
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["name"] == "Updated Production"
    assert response.get_json()["enabled"] is False

    response = client.delete(
        f"/api/services/standards/{standard.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["deleted"] is True

    response = client.get(
        f"/api/services/standards/{standard.id}",
        headers=admin_headers,
    )

    assert response.status_code == 404


def test_standard_slug_must_be_unique_inside_group(client, admin_headers):
    group = create_group()

    first = client.post(
        "/api/services/standards",
        json=standard_payload(group),
        headers=admin_headers,
    )

    duplicate = client.post(
        "/api/services/standards",
        json=standard_payload(group),
        headers=admin_headers,
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409


def test_create_list_update_delete_standard_checks_api(client, admin_headers):
    group = create_group()
    standard = ServiceStandard.create(
        group=group,
        slug="production",
        name="Production",
    )

    response = client.post(
        f"/api/services/standards/{standard.id}/checks",
        json=check_payload(),
        headers=admin_headers,
    )

    assert response.status_code == 201

    check = response.get_json()

    assert check["standard_id"] == standard.id
    assert check["check_type"] == "owner_exists"
    assert check["configuration"]["roles"] == ["owner"]

    response = client.get(
        f"/api/services/standards/{standard.id}/checks",
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.get_json()] == [check["id"]]

    response = client.put(
        f"/api/services/standards/{standard.id}/checks/{check['id']}",
        json=check_payload(
            slug="description-present",
            name="Description present",
            check_type="field_present",
            configuration={"field": "description"},
            weight=5,
            severity="warning",
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["check_type"] == "field_present"
    assert response.get_json()["configuration"] == {"field": "description"}

    response = client.delete(
        f"/api/services/standards/{standard.id}/checks/{check['id']}",
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["deleted"] is True


def test_standard_api_rejects_invalid_applies_to(client, admin_headers):
    group = create_group()

    response = client.post(
        "/api/services/standards",
        json=standard_payload(group, applies_to={"kinds": ["invalid"]}),
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "service_standard_invalid"


def test_standard_check_api_rejects_invalid_configuration(client, admin_headers):
    group = create_group()
    standard = ServiceStandard.create(
        group=group,
        slug="production",
        name="Production",
    )

    response = client.post(
        f"/api/services/standards/{standard.id}/checks",
        json=check_payload(configuration={"roles": ["invalid"]}),
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "service_standard_check_invalid"


def test_deleting_standard_soft_deletes_checks(client, admin_headers):
    group = create_group()
    standard = ServiceStandard.create(
        group=group,
        slug="production",
        name="Production",
    )
    check = ServiceStandardCheck.create(
        standard=standard,
        slug="owner",
        name="Owner",
        check_type="owner_exists",
    )

    response = client.delete(
        f"/api/services/standards/{standard.id}",
        headers=admin_headers,
    )

    assert response.status_code == 200

    check = ServiceStandardCheck.get_by_id(check.id)

    assert check.deleted is True
    assert check.enabled is False


def test_creating_standard_check_recalculates_group_services(
    client,
    admin_headers,
):
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    standard = ServiceStandard.create(
        group=group,
        slug="production",
        name="Production",
    )

    response = client.post(
        f"/api/services/standards/{standard.id}/checks",
        json=check_payload(
            slug="description-present",
            name="Description present",
            check_type="field_present",
            configuration={"field": "description"},
        ),
        headers=admin_headers,
    )

    assert response.status_code == 201

    state = ServiceReadinessState.get(
        ServiceReadinessState.service == service.id
    )

    assert state.status == "not_ready"
    assert state.score == 0


def test_apply_basic_operational_standard_preset(client, admin_headers):
    group = create_group()

    response = client.post(
        "/api/services/standards/presets/basic-operational",
        json={"group_id": group.id},
        headers=admin_headers,
    )

    assert response.status_code == 200

    payload = response.get_json()

    assert payload["slug"] == BASIC_OPERATIONAL_STANDARD_SLUG
    assert payload["group_id"] == group.id
    assert payload["checks_count"] == 6
    assert [check["slug"] for check in payload["checks"]] == [
        "owner",
        "escalation-policy",
        "notification-policy",
        "alert-route",
        "runbook",
        "dependency-cycle",
    ]


def test_apply_basic_operational_standard_preset_is_idempotent(client, admin_headers):
    group = create_group()

    first = client.post(
        "/api/services/standards/presets/basic-operational",
        json={"group_id": group.id},
        headers=admin_headers,
    )
    second = client.post(
        "/api/services/standards/presets/basic-operational",
        json={"group_id": group.id},
        headers=admin_headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.get_json()["id"] == second.get_json()["id"]
    assert second.get_json()["checks_count"] == 6


def test_apply_basic_operational_standard_preset_recalculates_services(client, admin_headers):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    response = client.post(
        "/api/services/standards/presets/basic-operational",
        json={"group_id": group.id},
        headers=admin_headers,
    )

    assert response.status_code == 200

    state = ServiceReadinessState.get(ServiceReadinessState.service == service.id)

    assert state.standards_count == 1
    assert state.checks_count == 6
    assert state.status == "not_ready"
