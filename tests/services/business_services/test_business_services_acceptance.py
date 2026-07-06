from datetime import datetime, timedelta

from app.modules.db.models import (
    BusinessService,
    BusinessServiceComponent,
    BusinessServiceIncidentImpact,
    ServiceDependency,
)
from app.services.business_services.impact import refresh_business_impacts_for_group
from app.services.business_services.status import apply_business_service_status
from tests.factories import create_group, create_impact_alert_group, create_service, create_team, unique


def create_business_service_with_component():
    group = create_group()
    team = create_team(group=group)
    service = create_service(team=team, slug=unique("api"), name="API")

    business_service = BusinessService.create(
        group=group,
        owner_team=team,
        slug=unique("checkout"),
        name="Checkout",
        enabled=True,
    )

    BusinessServiceComponent.create(
        business_service=business_service,
        service=service,
        criticality="required",
        impact_weight=100,
        enabled=True,
    )

    return group, team, service, business_service


def create_business_service_with_upstream_dependency():
    group = create_group()
    team = create_team(group=group)
    app_service = create_service(team=team, slug=unique("openstack"), name="Openstack")
    upstream_service = create_service(team=team, slug=unique("compute"), name="Cloud computes")

    app_service.status = "operational"
    app_service.save()
    upstream_service.status = "operational"
    upstream_service.save()

    ServiceDependency.create(
        service=app_service,
        depends_on_service=upstream_service,
        dependency_type="hard",
        criticality="required",
        enabled=True,
    )

    business_service = BusinessService.create(
        group=group,
        owner_team=team,
        slug=unique("cloud"),
        name="Cloud",
        enabled=True,
    )

    BusinessServiceComponent.create(
        business_service=business_service,
        service=app_service,
        criticality="required",
        impact_weight=100,
        enabled=True,
    )

    return group, team, app_service, upstream_service, business_service


def test_business_service_details_status_matches_effective_component_impact(client, db, auth_headers):
    group, team, service, business_service = create_business_service_with_component()

    service.status = "operational"
    service.save()

    create_impact_alert_group(
        team=team,
        service=service,
        fingerprint=unique("business-details-alert"),
        status="firing",
        severity="warning",
        alertname="API warning",
        summary="API warning",
    )

    response = client.get(
        f"/api/business-services/{business_service.id}",
        headers=auth_headers,
    )

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "degraded"
    assert data["components"][0]["service_status"] == "operational"
    assert data["components"][0]["effective_status"] == "degraded"
    assert data["components"][0]["effective_status_reason"] == "alert_group"


def test_business_services_list_is_not_stale_after_upstream_alert(client, db, auth_headers):
    group, team, app_service, upstream_service, business_service = create_business_service_with_upstream_dependency()

    create_impact_alert_group(
        team=team,
        service=upstream_service,
        fingerprint=unique("business-list-upstream-alert"),
        status="firing",
        severity="critical",
        alertname="Compute down",
        summary="Compute down",
    )

    response = client.get(
        f"/api/business-services?group_id={group.id}",
        headers=auth_headers,
    )

    assert response.status_code == 200

    data = response.get_json()
    item = next(row for row in data if row["id"] == business_service.id)

    assert item["status"] == "major_outage"


def test_manual_status_set_and_clear_return_details_payload(client, db, auth_headers):
    group, team, service, business_service = create_business_service_with_component()

    service.status = "major_outage"
    service.save()
    apply_business_service_status(business_service)

    set_response = client.post(
        f"/api/business-services/{business_service.id}/manual-status",
        json={
            "status": "degraded",
            "message": "Limited customer impact",
            "until": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        },
        headers=auth_headers,
    )

    assert set_response.status_code == 200

    set_data = set_response.get_json()

    assert set_data["status"] == "degraded"
    assert set_data["status_source"] == "manual"
    assert set_data["manual_status_active"] is True
    assert "components" in set_data
    assert "status_history" in set_data
    assert len(set_data["components"]) == 1

    clear_response = client.delete(
        f"/api/business-services/{business_service.id}/manual-status",
        headers=auth_headers,
    )

    assert clear_response.status_code == 200

    clear_data = clear_response.get_json()

    assert clear_data["status_source"] == "calculated"
    assert clear_data["manual_status"] is None
    assert clear_data["manual_status_active"] is False
    assert "components" in clear_data
    assert "status_history" in clear_data
    assert len(clear_data["components"]) == 1


def test_upstream_alert_creates_dependency_business_impact(db):
    group, team, app_service, upstream_service, business_service = create_business_service_with_upstream_dependency()

    alert_group = create_impact_alert_group(
        team=team,
        service=upstream_service,
        fingerprint=unique("business-impact-upstream-alert"),
        status="firing",
        severity="critical",
        alertname="Compute down",
        summary="Compute down",
    )

    impacts = refresh_business_impacts_for_group(alert_group)

    assert impacts

    impact = BusinessServiceIncidentImpact.get(
        BusinessServiceIncidentImpact.business_service == business_service.id,
        BusinessServiceIncidentImpact.group == alert_group.id,
        BusinessServiceIncidentImpact.relation == "dependency_upstream_alert",
    )

    assert impact.active is True
    assert impact.impact_status == "major_outage"
    assert impact.impact_score == 100
