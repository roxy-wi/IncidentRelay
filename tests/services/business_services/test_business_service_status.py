from app.modules.db.models import (
    BusinessService,
    BusinessServiceComponent,
    BusinessServiceIncidentImpact,
    BusinessServiceStatusHistory,
)
from app.services.business_services.impact import refresh_business_impacts_for_group
from app.services.business_services.status import apply_business_service_status
from tests.factories import create_group, create_impact_alert_group, create_service, create_team, unique


def create_business_service_fixture():
    group = create_group()
    team = create_team(group=group)

    api = create_service(team=team, slug=unique("api"), name="API")
    database = create_service(team=team, slug=unique("database"), name="Database")

    business_service = BusinessService.create(
        group=group,
        owner_team=team,
        slug=unique("checkout"),
        name="Checkout",
        criticality="critical",
        tier="tier_1",
        public=True,
        enabled=True,
    )

    return group, team, api, database, business_service


def test_business_service_status_is_operational_when_components_are_operational(db):
    group, team, api, database, business_service = create_business_service_fixture()

    api.status = "operational"
    api.save()

    BusinessServiceComponent.create(
        business_service=business_service,
        service=api,
        criticality="required",
        impact_weight=100,
        enabled=True,
    )

    result = apply_business_service_status(business_service)

    assert result["status"] == "operational"
    assert result["impact_score"] == 0

    business_service = BusinessService.get_by_id(business_service.id)

    assert business_service.status == "operational"
    assert BusinessServiceStatusHistory.select().count() == 1


def test_required_major_component_marks_business_service_major_outage(db):
    group, team, api, database, business_service = create_business_service_fixture()

    database.status = "major_outage"
    database.save()

    BusinessServiceComponent.create(
        business_service=business_service,
        service=database,
        criticality="required",
        impact_weight=100,
        enabled=True,
    )

    result = apply_business_service_status(business_service)

    assert result["status"] == "major_outage"
    assert result["impact_score"] == 100

    business_service = BusinessService.get_by_id(business_service.id)

    assert business_service.status == "major_outage"
    assert business_service.status_message.startswith("Affected components:")


def test_optional_component_degrades_business_service_less(db):
    group, team, api, database, business_service = create_business_service_fixture()

    api.status = "major_outage"
    api.save()

    BusinessServiceComponent.create(
        business_service=business_service,
        service=api,
        criticality="optional",
        impact_weight=100,
        enabled=True,
    )

    result = apply_business_service_status(business_service)

    assert result["status"] == "degraded"
    assert result["impact_score"] == 40


def test_business_impact_is_saved_for_alert_group(db):
    group, team, api, database, business_service = create_business_service_fixture()

    api.status = "major_outage"
    api.save()

    BusinessServiceComponent.create(
        business_service=business_service,
        service=api,
        criticality="required",
        impact_weight=100,
        enabled=True,
    )

    alert_group = create_impact_alert_group(
        team=team,
        service=api,
        fingerprint=unique("business-impact"),
        status="firing",
        severity="critical",
        alertname="API down",
        summary="API down",
    )

    impacts = refresh_business_impacts_for_group(alert_group)

    assert len(impacts) == 1

    impact = BusinessServiceIncidentImpact.get()

    assert impact.business_service_id == business_service.id
    assert impact.group_id == alert_group.id
    assert impact.service_id == api.id
    assert impact.impact_status == "major_outage"
    assert impact.impact_score == 100
    assert impact.active is True


def test_business_impact_is_deactivated_when_alert_group_is_resolved(db):
    group, team, api, database, business_service = create_business_service_fixture()

    api.status = "major_outage"
    api.save()

    BusinessServiceComponent.create(
        business_service=business_service,
        service=api,
        criticality="required",
        impact_weight=100,
        enabled=True,
    )

    alert_group = create_impact_alert_group(
        team=team,
        service=api,
        fingerprint=unique("business-impact"),
        status="firing",
        severity="critical",
        alertname="API down",
        summary="API down",
    )

    refresh_business_impacts_for_group(alert_group)

    assert BusinessServiceIncidentImpact.select().where(
        BusinessServiceIncidentImpact.active == True  # noqa: E712
    ).count() == 1

    alert_group.status = "resolved"
    alert_group.save()

    refresh_business_impacts_for_group(alert_group)

    assert BusinessServiceIncidentImpact.select().where(
        BusinessServiceIncidentImpact.active == True  # noqa: E712
    ).count() == 0
