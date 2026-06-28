import uuid

import pytest
from peewee import IntegrityError

from app.modules.db.models import ServiceDependency, ServiceEvent
from tests.factories import create_group, create_service, create_team


def test_service_gets_uuid_uid():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    assert isinstance(service.uid, uuid.UUID)


def test_service_uids_are_unique():
    group = create_group()
    team = create_team(group)
    first_service = create_service(team)
    second_service = create_service(team)

    assert first_service.uid != second_service.uid


def test_service_defaults_to_technical_production():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    assert service.kind == "technical"
    assert service.lifecycle == "production"


def test_service_event_keeps_scope_snapshot():
    group = create_group()
    original_team = create_team(group)
    new_team = create_team(group)
    service = create_service(original_team)

    event = ServiceEvent.create(service=service, group=group, team=original_team, category="configuration", event_type="service.created", title="Service created")

    service.team = new_team
    service.save(only=[service.__class__.team])

    event = ServiceEvent.get_by_id(event.id)

    assert event.group_id == group.id
    assert event.team_id == original_team.id
    assert event.service_id == service.id


def test_service_event_deduplication_is_scoped_by_service_and_source():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    ServiceEvent.create(service=service, group=group, team=team, category="change", event_type="change.deployment_succeeded", title="Deployment completed", source="github_actions", dedup_key="run-123")

    with pytest.raises(IntegrityError):
        ServiceEvent.create(service=service, group=group, team=team, category="change", event_type="change.deployment_succeeded", title="Deployment completed again", source="github_actions", dedup_key="run-123")


def test_same_dedup_key_can_be_used_by_different_sources():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    first_event = ServiceEvent.create(service=service, group=group, team=team, category="change", event_type="change.deployment_succeeded", title="GitHub deployment", source="github_actions", dedup_key="deployment-123")
    second_event = ServiceEvent.create(service=service, group=group, team=team, category="change", event_type="change.deployment_succeeded", title="Argo deployment", source="argocd", dedup_key="deployment-123")

    assert first_event.id != second_event.id


def test_same_dedup_key_can_be_used_for_different_services():
    group = create_group()
    team = create_team(group)
    first_service = create_service(team)
    second_service = create_service(team)

    first_event = ServiceEvent.create(service=first_service, group=group, team=team, category="change", event_type="change.deployment_succeeded", title="First deployment", source="github_actions", dedup_key="run-123")
    second_event = ServiceEvent.create(service=second_service, group=group, team=team, category="change", event_type="change.deployment_succeeded", title="Second deployment", source="github_actions", dedup_key="run-123")

    assert first_event.id != second_event.id


def test_service_dependency_has_correlation_defaults():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    dependency_service = create_service(team)

    dependency = ServiceDependency.create(service=service, depends_on_service=dependency_service)

    assert dependency.correlation_enabled is True
    assert dependency.propagation_delay_seconds == 300
    assert dependency.metadata == {}
