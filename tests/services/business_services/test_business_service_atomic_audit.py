"""Business Service mutations, status history and audit share one commit."""

import pytest

from app.modules.db import business_services_repo
from app.modules.db.models import (
    AuditLog,
    BusinessService,
    BusinessServiceComponent,
    BusinessServiceStatusHistory,
)
from app.services.business_services.status import apply_business_service_status
from app.views.business_services import routes as business_routes
from tests.factories import create_group, create_service, create_team, unique


def _deny_audit(*_args, **_kwargs):
    raise RuntimeError("audit persistence failed")


def test_service_creation_rolls_back_when_audit_fails(
    client, db, auth_headers, monkeypatch,
):
    group = create_group()
    monkeypatch.setattr(business_routes, "_audit_business_service", _deny_audit)

    response = client.post(
        "/api/business-services",
        headers=auth_headers,
        json={
            "group_id": group.id,
            "slug": unique("atomic-create"),
            "name": "Atomic test service",
        },
    )

    assert response.status_code == 500, response.get_json()
    assert response.get_json()["error"] == "Internal Server Error"
    assert BusinessService.select().count() == 0
    assert AuditLog.select().count() == 0


def test_component_and_status_history_roll_back_on_audit_failure(
    client, db, auth_headers, monkeypatch,
):
    group = create_group()
    team = create_team(group)
    technical = create_service(team, slug=unique("atomic-technical"))
    technical.status = "major_outage"
    technical.save()
    business = BusinessService.create(
        group=group, slug=unique("atomic-business"), name="Business", enabled=True,
    )
    original_status = business.status
    monkeypatch.setattr(business_routes, "_audit_business_service", _deny_audit)

    response = client.post(
        f"/api/business-services/{business.id}/components",
        headers=auth_headers,
        json={
            "service_id": technical.id,
            "component_type": "technical_service",
            "criticality": "required",
            "impact_weight": 100,
            "status_rule": "inherit",
            "enabled": True,
        },
    )

    assert response.status_code == 500, response.get_json()
    assert response.get_json()["error"] == "Internal Server Error"
    assert BusinessServiceComponent.select().where(
        BusinessServiceComponent.business_service == business.id
    ).count() == 0
    assert BusinessServiceStatusHistory.select().where(
        BusinessServiceStatusHistory.business_service == business.id
    ).count() == 0
    assert BusinessService.get_by_id(business.id).status == original_status


def test_soft_delete_and_components_roll_back_on_audit_failure(
    client, db, auth_headers, monkeypatch,
):
    group = create_group()
    team = create_team(group)
    technical = create_service(team, slug=unique("delete-technical"))
    business = BusinessService.create(
        group=group, slug=unique("delete-business"), name="Business", enabled=True,
    )
    component = BusinessServiceComponent.create(
        business_service=business, service=technical, enabled=True,
    )
    monkeypatch.setattr(business_routes, "_audit_business_service", _deny_audit)

    response = client.delete(f"/api/business-services/{business.id}", headers=auth_headers)

    assert response.status_code == 500, response.get_json()
    assert response.get_json()["error"] == "Internal Server Error"
    assert BusinessService.get_by_id(business.id).deleted is False
    assert BusinessServiceComponent.get_by_id(component.id).deleted is False


def test_recalculation_and_history_roll_back_on_history_insert_failure(
    db, monkeypatch,
):
    group = create_group()
    team = create_team(group)
    technical = create_service(team, slug=unique("history-technical"))
    technical.status = "major_outage"
    technical.save()
    business = BusinessService.create(
        group=group,
        slug=unique("history-business"),
        name="Business",
        status="unknown",
        enabled=True,
    )
    BusinessServiceComponent.create(
        business_service=business,
        service=technical,
        criticality="required",
        impact_weight=100,
        enabled=True,
    )
    monkeypatch.setattr(
        business_services_repo,
        "create_business_service_status_history",
        lambda **_kwargs: _deny_audit(),
    )

    with pytest.raises(RuntimeError, match="audit persistence failed"):
        apply_business_service_status(business)

    assert BusinessService.get_by_id(business.id).status == "unknown"
    assert BusinessServiceStatusHistory.select().where(
        BusinessServiceStatusHistory.business_service == business.id
    ).count() == 0


def test_repository_soft_delete_rolls_back_parent_on_component_failure(
    db, monkeypatch,
):
    group = create_group()
    team = create_team(group)
    technical = create_service(team, slug=unique("repo-delete-technical"))
    business = BusinessService.create(
        group=group, slug=unique("repo-delete-business"), name="Business",
        enabled=True,
    )
    component = BusinessServiceComponent.create(
        business_service=business, service=technical, enabled=True,
    )

    monkeypatch.setattr(
        business_services_repo.BusinessServiceComponent,
        "update",
        lambda **_kwargs: _deny_audit(),
    )

    with pytest.raises(RuntimeError, match="audit persistence failed"):
        business_services_repo.soft_delete_business_service(business.id)

    assert BusinessService.get_by_id(business.id).deleted is False
    assert BusinessServiceComponent.get_by_id(component.id).deleted is False
