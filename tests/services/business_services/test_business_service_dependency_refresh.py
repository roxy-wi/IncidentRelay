from app.modules.db.models import BusinessService, BusinessServiceComponent, ServiceDependency
from app.services.business_services.status import (
    impacted_service_ids_for_technical_service,
    refresh_business_services_for_technical_service,
)
from tests.factories import create_group, create_service, create_team, unique


def _create_business_service(group, team, name="Checkout"):
    return BusinessService.create(
        group=group,
        owner_team=team,
        slug=unique("business-service"),
        name=name,
        enabled=True,
    )


def _create_dependency(service, depends_on_service, *, enabled=True, deleted=False):
    return ServiceDependency.create(
        service=service,
        depends_on_service=depends_on_service,
        dependency_type="hard",
        criticality="required",
        enabled=enabled,
        deleted=deleted,
    )


def _add_component(business_service, service, *, criticality="required", weight=100):
    return BusinessServiceComponent.create(
        business_service=business_service,
        service=service,
        criticality=criticality,
        impact_weight=weight,
        enabled=True,
    )


def test_impacted_service_ids_walks_downstream_dependency_chain_once(db):
    group = create_group()
    team = create_team(group=group)
    database = create_service(team=team, slug=unique("database"), name="Database")
    api = create_service(team=team, slug=unique("api"), name="API")
    frontend = create_service(team=team, slug=unique("frontend"), name="Frontend")
    checkout = create_service(team=team, slug=unique("checkout"), name="Checkout")

    _create_dependency(api, database)
    _create_dependency(frontend, api)
    _create_dependency(checkout, frontend)
    _create_dependency(database, checkout)

    assert impacted_service_ids_for_technical_service(database.id) == {
        database.id,
        api.id,
        frontend.id,
        checkout.id,
    }


def test_impacted_service_ids_ignores_disabled_and_deleted_dependencies(db):
    group = create_group()
    team = create_team(group=group)
    database = create_service(team=team, slug=unique("database"), name="Database")
    active_api = create_service(team=team, slug=unique("api"), name="API")
    disabled_api = create_service(team=team, slug=unique("disabled"), name="Disabled")
    deleted_api = create_service(team=team, slug=unique("deleted"), name="Deleted")

    _create_dependency(active_api, database)
    _create_dependency(disabled_api, database, enabled=False)
    _create_dependency(deleted_api, database, deleted=True)

    assert impacted_service_ids_for_technical_service(database.id) == {
        database.id,
        active_api.id,
    }


def test_refresh_business_services_for_dependency_updates_business_once(db):
    group = create_group()
    team = create_team(group=group)
    database = create_service(team=team, slug=unique("database"), name="Database")
    api = create_service(team=team, slug=unique("api"), name="API")
    frontend = create_service(team=team, slug=unique("frontend"), name="Frontend")
    business_service = _create_business_service(group, team)

    database.status = "major_outage"
    database.save()
    api.status = "operational"
    api.save()
    frontend.status = "operational"
    frontend.save()

    _create_dependency(api, database)
    _create_dependency(frontend, database)
    _add_component(business_service, api)
    _add_component(business_service, frontend)

    refreshed = refresh_business_services_for_technical_service(database.id)

    assert len(refreshed) == 1

    refreshed_business_service, result = refreshed[0]
    business_service = BusinessService.get_by_id(business_service.id)

    assert refreshed_business_service.id == business_service.id
    assert result["status"] == "major_outage"
    assert business_service.status == "major_outage"
    assert result["component_snapshot"]
    assert {item["service_id"] for item in result["component_snapshot"]} == {
        api.id,
        frontend.id,
    }


def test_refresh_business_services_for_dependency_skips_disabled_business_service(db):
    group = create_group()
    team = create_team(group=group)
    database = create_service(team=team, slug=unique("database"), name="Database")
    api = create_service(team=team, slug=unique("api"), name="API")
    business_service = _create_business_service(group, team)

    business_service.enabled = False
    business_service.save()
    database.status = "major_outage"
    database.save()

    _create_dependency(api, database)
    _add_component(business_service, api)

    assert refresh_business_services_for_technical_service(database.id) == []

    business_service = BusinessService.get_by_id(business_service.id)
    assert business_service.status != "major_outage"
