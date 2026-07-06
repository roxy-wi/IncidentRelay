from app.modules.db.models import BusinessService, BusinessServiceComponent
from tests.factories import create_group, create_service, create_team, unique


def test_create_business_service_api(client, db, auth_headers):
    group = create_group()

    response = client.post(
        "/api/business-services",
        json={
            "group_id": group.id,
            "slug": unique("checkout"),
            "name": "Checkout",
            "description": "Customer checkout",
            "criticality": "critical",
            "tier": "tier_1",
            "public": True,
            "public_name": "Checkout",
            "public_description": "Checkout flow",
            "public_order": 10,
            "enabled": True,
        },
        headers=auth_headers,
    )

    assert response.status_code == 201

    data = response.get_json()

    assert data["id"]
    assert data["group_id"] == group.id
    assert data["name"] == "Checkout"
    assert data["status"] == "unknown"
    assert data["public"] is True

    assert BusinessService.select().count() == 1


def test_update_business_service_api(client, db, auth_headers):
    group = create_group()

    item = BusinessService.create(
        group=group,
        slug=unique("checkout"),
        name="Checkout",
        enabled=True,
    )

    response = client.put(
        f"/api/business-services/{item.id}",
        json={
            "group_id": group.id,
            "slug": item.slug,
            "name": "Checkout Updated",
            "description": "Updated",
            "criticality": "important",
            "tier": "tier_2",
            "public": False,
            "public_name": None,
            "public_description": None,
            "public_order": 20,
            "labels": {},
            "metadata": {},
            "enabled": True,
        },
        headers=auth_headers,
    )

    assert response.status_code == 200

    data = response.get_json()

    assert data["name"] == "Checkout Updated"
    assert data["public"] is False


def test_create_business_service_component_api_recalculates_status(client, db, auth_headers):
    group = create_group()
    team = create_team(group=group)

    service = create_service(team=team, slug=unique("api"), name="API")
    service.status = "major_outage"
    service.save()

    item = BusinessService.create(
        group=group,
        owner_team=team,
        slug=unique("checkout"),
        name="Checkout",
        enabled=True,
    )

    response = client.post(
        f"/api/business-services/{item.id}/components",
        json={
            "service_id": service.id,
            "component_type": "technical_service",
            "criticality": "required",
            "impact_weight": 100,
            "position": 0,
            "status_rule": "inherit",
            "description": "API dependency",
            "enabled": True,
        },
        headers=auth_headers,
    )

    assert response.status_code == 201

    data = response.get_json()

    assert data["business_service_id"] == item.id
    assert data["service_id"] == service.id
    assert data["criticality"] == "required"

    item = BusinessService.get_by_id(item.id)

    assert item.status == "major_outage"
    assert BusinessServiceComponent.select().count() == 1


def test_get_business_service_details_includes_components_and_history(client, db, auth_headers):
    group = create_group()
    team = create_team(group=group)

    service = create_service(team=team, slug=unique("api"), name="API")
    item = BusinessService.create(
        group=group,
        owner_team=team,
        slug=unique("checkout"),
        name="Checkout",
        enabled=True,
    )

    BusinessServiceComponent.create(
        business_service=item,
        service=service,
        criticality="required",
        impact_weight=100,
        enabled=True,
    )

    response = client.get(
        f"/api/business-services/{item.id}",
        headers=auth_headers,
    )

    assert response.status_code == 200

    data = response.get_json()

    assert data["id"] == item.id
    assert data["components_count"] == 1
    assert len(data["components"]) == 1
    assert "status_history" in data


def test_delete_business_service_soft_deletes_components(client, db, auth_headers):
    group = create_group()
    team = create_team(group=group)

    service = create_service(team=team, slug=unique("api"), name="API")
    item = BusinessService.create(
        group=group,
        owner_team=team,
        slug=unique("checkout"),
        name="Checkout",
        enabled=True,
    )
    component = BusinessServiceComponent.create(
        business_service=item,
        service=service,
        criticality="required",
        impact_weight=100,
        enabled=True,
    )

    response = client.delete(
        f"/api/business-services/{item.id}",
        headers=auth_headers,
    )

    assert response.status_code == 204

    item = BusinessService.get_by_id(item.id)
    component = BusinessServiceComponent.get_by_id(component.id)

    assert item.deleted is True
    assert item.enabled is False
    assert component.deleted is True
    assert component.enabled is False


def test_list_business_services_includes_components_count(client, db, auth_headers):
    group = create_group()
    team = create_team(group=group)
    service = create_service(team=team, slug=unique("api"), name="API")

    item = BusinessService.create(
        group=group,
        owner_team=team,
        slug=unique("checkout"),
        name="Checkout",
        enabled=True,
    )

    BusinessServiceComponent.create(
        business_service=item,
        service=service,
        criticality="required",
        impact_weight=100,
        enabled=True,
    )

    response = client.get(
        f"/api/business-services?group_id={group.id}",
        headers=auth_headers,
    )

    assert response.status_code == 200

    data = response.get_json()

    assert len(data) == 1
    assert data[0]["id"] == item.id
    assert data[0]["components_count"] == 1


def test_alert_group_serializer_includes_business_impact_summary(db):
    from app.modules.db.models import BusinessService, BusinessServiceComponent
    from app.services.business_services.impact import refresh_business_impacts_for_group
    from app.services.serializers.alerts import serialize_alert_group
    from tests.factories import create_group, create_impact_alert_group, create_service, create_team, unique

    group = create_group()
    team = create_team(group=group)
    service = create_service(team=team, slug=unique("api"), name="API")
    service.status = "major_outage"
    service.save()

    business_service = BusinessService.create(
        group=group,
        owner_team=team,
        slug=unique("checkout"),
        name="Checkout",
        public_name="Checkout",
        enabled=True,
    )

    BusinessServiceComponent.create(
        business_service=business_service,
        service=service,
        criticality="required",
        impact_weight=100,
        enabled=True,
    )

    alert_group = create_impact_alert_group(
        team=team,
        service=service,
        fingerprint=unique("business-impact-summary"),
        status="firing",
        severity="critical",
        alertname="API down",
        summary="API down",
    )

    refresh_business_impacts_for_group(alert_group)

    data = serialize_alert_group(alert_group)

    assert data["business_impact_summary"]["has_business_impact"] is True
    assert data["business_impact_summary"]["total"] == 1
    assert data["business_impact_summary"]["highest_status"] == "major_outage"
    assert data["business_impact_summary"]["services"][0]["public_name"] == "Checkout"
