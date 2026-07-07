from app.modules.db.models import BusinessService, BusinessServiceComponent, ServiceDependency
from app.services.business_services.status import apply_business_service_status
from tests.factories import create_group, create_impact_alert_group, create_service, create_team, unique


def test_business_service_uses_effective_component_status_from_open_alert(db):
    group = create_group()
    team = create_team(group=group)
    service = create_service(team=team, slug=unique("api"), name="API")

    service.status = "operational"
    service.save()

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

    create_impact_alert_group(
        team=team,
        service=service,
        fingerprint=unique("api-warning"),
        status="firing",
        severity="warning",
        alertname="API warning",
        summary="API warning",
    )

    result = apply_business_service_status(business_service)

    assert result["status"] == "degraded"
    assert result["component_snapshot"][0]["service_status"] == "operational"
    assert result["component_snapshot"][0]["effective_status"] == "degraded"
    assert result["component_snapshot"][0]["effective_status_reason"] == "alert_group"


def test_business_service_uses_effective_component_status_from_dependency(db):
    group = create_group()
    team = create_team(group=group)

    app_service = create_service(team=team, slug=unique("app"), name="App")
    dependency_service = create_service(team=team, slug=unique("postgres"), name="Postgres")

    app_service.status = "operational"
    app_service.save()

    dependency_service.status = "operational"
    dependency_service.save()

    ServiceDependency.create(
        service=app_service,
        depends_on_service=dependency_service,
        dependency_type="hard",
        criticality="required",
        enabled=True,
    )

    business_service = BusinessService.create(
        group=group,
        owner_team=team,
        slug=unique("checkout"),
        name="Checkout",
        enabled=True,
    )

    BusinessServiceComponent.create(
        business_service=business_service,
        service=app_service,
        criticality="required",
        impact_weight=100,
        enabled=True,
    )

    create_impact_alert_group(
        team=team,
        service=dependency_service,
        fingerprint=unique("postgres-critical"),
        status="firing",
        severity="critical",
        alertname="Postgres down",
        summary="Postgres down",
    )

    result = apply_business_service_status(business_service)

    assert result["status"] == "major_outage"
    assert result["component_snapshot"][0]["service_status"] == "operational"
    assert result["component_snapshot"][0]["effective_status"] == "major_outage"
    assert result["component_snapshot"][0]["effective_status_reason"] == "upstream_dependency"


def test_business_service_combines_multiple_component_scores(db):
    group = create_group()
    team = create_team(group=group)

    business_service = BusinessService.create(
        group=group,
        owner_team=team,
        slug=unique("checkout"),
        name="Checkout",
        enabled=True,
    )

    components = []

    for index in range(3):
        service = create_service(team=team, slug=unique(f"component-{index}"), name=f"Component {index}")
        components.append(service)

        BusinessServiceComponent.create(
            business_service=business_service,
            service=service,
            criticality="important",
            impact_weight=100,
            enabled=True,
        )

        create_impact_alert_group(
            team=team,
            service=service,
            fingerprint=unique(f"component-{index}-warning"),
            status="firing",
            severity="warning",
            alertname=f"Component{index}Warning",
            summary=f"Component {index} warning",
        )

    result = apply_business_service_status(business_service)

    assert result["status"] == "partial_outage"
    assert result["impact_score"] == 66
    assert [item["weighted_impact_score"] for item in result["component_snapshot"]] == [30, 30, 30]
    assert all(item["service_impact_score"] == 40 for item in result["component_snapshot"])


def test_business_service_uses_priority_based_component_impact(db):
    group = create_group()
    team = create_team(group=group)
    service = create_service(team=team, slug=unique("payment"), name="Payment")

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

    create_impact_alert_group(
        team=team,
        service=service,
        fingerprint=unique("payment-warning-p2"),
        status="firing",
        severity="warning",
        priority_slug="p2",
        priority_order=2,
        alertname="PaymentProviderSlow",
        summary="Payment provider warning with P2 priority",
    )

    result = apply_business_service_status(business_service)

    assert result["status"] == "partial_outage"
    assert result["impact_score"] == 75
    assert result["component_snapshot"][0]["alert_impact_score"] == 75
    assert result["component_snapshot"][0]["weighted_impact_score"] == 75
