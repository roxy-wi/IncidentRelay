from app.modules.db.models import AlertEvent, BusinessService, BusinessServiceComponent
from app.services.business_services.impact import refresh_business_impacts_for_group
from tests.factories import create_group, create_impact_alert_group, create_service, create_team, unique


def create_business_impact_event_fixture():
    group = create_group()
    team = create_team(group=group)
    service = create_service(team=team, slug=unique("api"), name="API")

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
        fingerprint=unique("business-impact-event"),
        status="firing",
        severity="warning",
        alertname="API warning",
        summary="API warning",
    )

    return service, business_service, alert_group


def list_group_event_types(group_id):
    return [
        event.event_type
        for event in AlertEvent.select().where(AlertEvent.group == group_id).order_by(AlertEvent.id.asc())
    ]


def test_business_impact_detected_event_is_recorded(db):
    service, business_service, alert_group = create_business_impact_event_fixture()

    service.status = "major_outage"
    service.save()

    refresh_business_impacts_for_group(alert_group)

    event_types = list_group_event_types(alert_group.id)

    assert "business_impact_detected" in event_types

    event = AlertEvent.select().where(
        AlertEvent.group == alert_group.id,
        AlertEvent.event_type == "business_impact_detected",
    ).get()

    assert "Checkout" in event.message
    assert "major_outage" in event.message
    assert "score=100" in event.message


def test_business_impact_refresh_does_not_duplicate_detected_event(db):
    service, business_service, alert_group = create_business_impact_event_fixture()

    service.status = "major_outage"
    service.save()

    refresh_business_impacts_for_group(alert_group)
    refresh_business_impacts_for_group(alert_group)

    assert AlertEvent.select().where(
        AlertEvent.group == alert_group.id,
        AlertEvent.event_type == "business_impact_detected",
    ).count() == 1


def test_business_impact_updated_event_is_recorded_when_score_changes(db):
    service, business_service, alert_group = create_business_impact_event_fixture()

    service.status = "degraded"
    service.save()

    refresh_business_impacts_for_group(alert_group)

    service.status = "major_outage"
    service.save()

    refresh_business_impacts_for_group(alert_group)

    event = AlertEvent.select().where(
        AlertEvent.group == alert_group.id,
        AlertEvent.event_type == "business_impact_updated",
    ).get()

    assert "Checkout" in event.message
    assert "major_outage" in event.message
    assert "previous:" in event.message


def test_business_impact_deactivated_event_is_recorded_when_group_resolves(db):
    service, business_service, alert_group = create_business_impact_event_fixture()

    service.status = "major_outage"
    service.save()

    refresh_business_impacts_for_group(alert_group)

    alert_group.status = "resolved"
    alert_group.save()

    refresh_business_impacts_for_group(alert_group)

    event_types = list_group_event_types(alert_group.id)

    assert "business_impact_deactivated" in event_types
