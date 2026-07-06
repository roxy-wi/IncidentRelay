from datetime import datetime

import pytest
from peewee import IntegrityError

from app.modules.db.models import (
    AlertGroup,
    BusinessService,
    BusinessServiceComponent,
    BusinessServiceIncidentImpact,
    BusinessServiceStatusHistory,
)
from app.services.business_services.impact import refresh_business_impacts_for_group
from app.services.business_services.status import apply_business_service_status
from tests.factories import create_group, create_impact_alert_group, create_service, create_team, unique


def create_unmapped_alert_group(team, status="firing"):
    now = datetime.utcnow()
    fingerprint = unique("business-impact-no-service")

    labels = {
        "alertname": "Unmapped alert",
        "severity": "critical",
    }

    return AlertGroup.create(
        team=team,
        route=None,
        service=None,
        source="pytest",
        group_key_hash=fingerprint,
        group_key=fingerprint,
        title="Unmapped alert",
        message="Unmapped alert",
        severity="critical",
        common_labels=labels,
        label_values=labels,
        payload_summary={
            "summary": "Unmapped alert",
            "alertname": "Unmapped alert",
            "severity": "critical",
        },
        status=status,
        first_seen_at=now,
        last_seen_at=now,
        alert_count=1,
        firing_count=1 if status == "firing" else 0,
        acknowledged_count=1 if status == "acknowledged" else 0,
        resolved_count=1 if status == "resolved" else 0,
        silenced_count=1 if status == "silenced" else 0,
    )


def create_business_service_base():
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

    return group, team, service, business_service


def test_duplicate_business_service_slug_is_rejected(db):
    group = create_group()

    slug = unique("checkout")

    BusinessService.create(
        group=group,
        slug=slug,
        name="Checkout",
        enabled=True,
    )

    with pytest.raises(IntegrityError):
        BusinessService.create(
            group=group,
            slug=slug,
            name="Checkout duplicate",
            enabled=True,
        )


def test_same_slug_is_allowed_in_different_groups(db):
    group_a = create_group()
    group_b = create_group()

    slug = unique("checkout")

    first = BusinessService.create(
        group=group_a,
        slug=slug,
        name="Checkout A",
        enabled=True,
    )

    second = BusinessService.create(
        group=group_b,
        slug=slug,
        name="Checkout B",
        enabled=True,
    )

    assert first.id != second.id
    assert first.slug == second.slug


def test_duplicate_component_is_rejected(db):
    group, team, service, business_service = create_business_service_base()

    BusinessServiceComponent.create(
        business_service=business_service,
        service=service,
        criticality="required",
        impact_weight=100,
        enabled=True,
    )

    with pytest.raises(IntegrityError):
        BusinessServiceComponent.create(
            business_service=business_service,
            service=service,
            criticality="important",
            impact_weight=50,
            enabled=True,
        )


def test_disabled_component_is_ignored_by_status_calculation(db):
    group, team, service, business_service = create_business_service_base()

    service.status = "major_outage"
    service.save()

    BusinessServiceComponent.create(
        business_service=business_service,
        service=service,
        criticality="required",
        impact_weight=100,
        enabled=False,
    )

    result = apply_business_service_status(business_service)

    assert result["status"] == "unknown"
    assert result["impact_score"] == 0

    business_service = BusinessService.get_by_id(business_service.id)

    assert business_service.status == "unknown"


def test_deleted_component_is_ignored_by_status_calculation(db):
    group, team, service, business_service = create_business_service_base()

    service.status = "major_outage"
    service.save()

    component = BusinessServiceComponent.create(
        business_service=business_service,
        service=service,
        criticality="required",
        impact_weight=100,
        enabled=True,
        deleted=True,
    )

    result = apply_business_service_status(business_service)

    assert result["status"] == "unknown"
    assert result["impact_score"] == 0
    assert component.deleted is True


def test_status_history_is_not_duplicated_without_status_change(db):
    group, team, service, business_service = create_business_service_base()

    service.status = "operational"
    service.save()

    BusinessServiceComponent.create(
        business_service=business_service,
        service=service,
        criticality="required",
        impact_weight=100,
        enabled=True,
    )

    apply_business_service_status(business_service)
    apply_business_service_status(business_service)

    assert BusinessServiceStatusHistory.select().where(
        BusinessServiceStatusHistory.business_service == business_service.id
    ).count() == 1


def test_resolved_alert_deactivates_business_impact(db):
    group, team, service, business_service = create_business_service_base()

    service.status = "major_outage"
    service.save()

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
        fingerprint=unique("business-impact-resolved"),
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


def test_alert_without_service_does_not_create_business_impact(db):
    group = create_group()
    team = create_team(group=group)

    alert_group = create_unmapped_alert_group(team)

    impacts = refresh_business_impacts_for_group(alert_group)

    assert impacts == []
    assert BusinessServiceIncidentImpact.select().count() == 0
