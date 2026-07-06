from datetime import datetime, timedelta

from app.modules.db.models import BusinessService, BusinessServiceComponent, BusinessServiceStatusHistory
from app.modules.db import business_services_repo
from app.services.business_services.status import apply_business_service_status
from tests.factories import create_group, create_service, create_team, unique


def create_manual_status_fixture():
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


def test_manual_status_override_wins_over_calculated_status(db):
    group, team, service, business_service = create_manual_status_fixture()

    service.status = "major_outage"
    service.save()

    business_services_repo.set_business_service_manual_status(
        business_service.id,
        manual_status="degraded",
        message="Customer impact is limited",
        until=datetime.utcnow() + timedelta(hours=1),
        user_id=None,
    )

    result = apply_business_service_status(business_service)

    business_service = BusinessService.get_by_id(business_service.id)

    assert result["status"] == "degraded"
    assert result["status_source"] == "manual"
    assert result["calculated_status"] == "major_outage"
    assert business_service.status == "degraded"
    assert business_service.status_source == "manual"
    assert business_service.status_message == "Customer impact is limited"


def test_expired_manual_status_is_ignored_and_cleared(db):
    group, team, service, business_service = create_manual_status_fixture()

    service.status = "major_outage"
    service.save()

    business_services_repo.set_business_service_manual_status(
        business_service.id,
        manual_status="operational",
        message="Expired override",
        until=datetime.utcnow() - timedelta(minutes=1),
        user_id=None,
    )

    business_service = BusinessService.get_by_id(business_service.id)

    result = apply_business_service_status(business_service)

    business_service = BusinessService.get_by_id(business_service.id)

    assert result["status"] == "major_outage"
    assert result["status_source"] == "calculated"
    assert business_service.manual_status is None
    assert business_service.manual_status_message is None
    assert business_service.manual_status_until is None
    assert business_service.status == "major_outage"


def test_clear_manual_status_reverts_to_calculated_status(db):
    group, team, service, business_service = create_manual_status_fixture()

    service.status = "major_outage"
    service.save()

    business_services_repo.set_business_service_manual_status(
        business_service.id,
        manual_status="degraded",
        message="Manual degraded",
        until=datetime.utcnow() + timedelta(hours=1),
        user_id=None,
    )

    business_service = BusinessService.get_by_id(business_service.id)
    apply_business_service_status(business_service)

    business_services_repo.clear_business_service_manual_status(business_service.id)

    business_service = BusinessService.get_by_id(business_service.id)
    result = apply_business_service_status(business_service)

    business_service = BusinessService.get_by_id(business_service.id)

    assert result["status"] == "major_outage"
    assert result["status_source"] == "calculated"
    assert business_service.manual_status is None
    assert business_service.status == "major_outage"


def test_manual_status_source_change_writes_history(db):
    group, team, service, business_service = create_manual_status_fixture()

    service.status = "degraded"
    service.save()

    apply_business_service_status(business_service)

    business_services_repo.set_business_service_manual_status(
        business_service.id,
        manual_status="degraded",
        message="Manual confirmation",
        until=datetime.utcnow() + timedelta(hours=1),
        user_id=None,
    )

    business_service = BusinessService.get_by_id(business_service.id)
    apply_business_service_status(business_service)

    history = list(
        BusinessServiceStatusHistory
        .select()
        .where(BusinessServiceStatusHistory.business_service == business_service.id)
        .order_by(BusinessServiceStatusHistory.id.asc())
    )

    assert len(history) == 2
    assert history[-1].old_status == "degraded"
    assert history[-1].new_status == "degraded"
    assert history[-1].status_source == "manual"
    assert history[-1].message == "Manual confirmation"


def test_set_manual_status_api(client, db, auth_headers):
    group, team, service, business_service = create_manual_status_fixture()

    service.status = "major_outage"
    service.save()

    response = client.post(
        f"/api/business-services/{business_service.id}/manual-status",
        json={
            "status": "degraded",
            "message": "Limited customer impact",
            "until": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
        },
        headers=auth_headers,
    )

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "degraded"
    assert data["status_source"] == "manual"
    assert data["manual_status"] == "degraded"
    assert data["manual_status_message"] == "Limited customer impact"
    assert data["manual_status_active"] is True


def test_clear_manual_status_api(client, db, auth_headers):
    group, team, service, business_service = create_manual_status_fixture()

    service.status = "major_outage"
    service.save()

    business_services_repo.set_business_service_manual_status(
        business_service.id,
        manual_status="degraded",
        message="Manual degraded",
        until=datetime.utcnow() + timedelta(hours=1),
        user_id=None,
    )

    business_service = BusinessService.get_by_id(business_service.id)
    apply_business_service_status(business_service)

    response = client.delete(
        f"/api/business-services/{business_service.id}/manual-status",
        headers=auth_headers,
    )

    assert response.status_code == 200

    data = response.get_json()

    assert data["status"] == "major_outage"
    assert data["status_source"] == "calculated"
    assert data["manual_status"] is None
    assert data["manual_status_active"] is False
