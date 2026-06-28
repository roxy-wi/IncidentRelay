from app.modules.db.models import ServiceEvent
from app.services.service_catalog import events as catalog_events
from app.services.service_catalog.events import (
    READINESS_SCOPE_DEPENDENCY_COMPONENT,
    READINESS_SCOPE_NONE,
    READINESS_SCOPE_SERVICE,
    READINESS_SCOPE_SERVICES,
    emit_service_catalog_event,
)
from tests.factories import create_group, create_service, create_team


def test_emit_service_catalog_event_creates_timeline_event_and_runs_service_readiness(monkeypatch):
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    calls = []

    def fake_reconcile_service_readiness(service_arg, *, trigger, actor_user=None):
        calls.append({"service_id": service_arg.id, "trigger": trigger, "actor_user": actor_user})
        return {"state": {"service_id": service_arg.id, "status": "ready"}}

    monkeypatch.setattr(
        catalog_events,
        "reconcile_service_readiness",
        fake_reconcile_service_readiness,
    )

    result = emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service_runbook.created",
        title="Service runbook created",
        summary="Primary runbook",
        source_ref="service_runbook:10",
        payload={"runbook": {"id": 10, "title": "Primary runbook"}},
        readiness_scope=READINESS_SCOPE_SERVICE,
        readiness_trigger="service_runbook_created",
    )

    assert len(result.readiness_results) == 1
    assert calls == [
        {
            "service_id": service.id,
            "trigger": "service_runbook_created",
            "actor_user": None,
        }
    ]

    event = ServiceEvent.get_by_id(result.timeline_event.id)
    assert event.service_id == service.id
    assert event.group_id == group.id
    assert event.team_id == team.id
    assert event.category == "configuration"
    assert event.event_type == "service_runbook.created"
    assert event.title == "Service runbook created"
    assert event.summary == "Primary runbook"
    assert event.source_ref == "service_runbook:10"
    assert event.payload == {"runbook": {"id": 10, "title": "Primary runbook"}}


def test_emit_service_catalog_event_can_skip_readiness(monkeypatch):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    def fail_reconcile(*args, **kwargs):
        raise AssertionError("readiness should not be reconciled")

    monkeypatch.setattr(catalog_events, "reconcile_service_readiness", fail_reconcile)

    result = emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service.deleted",
        title="Service deleted",
        payload={"deleted": True},
        readiness_scope=READINESS_SCOPE_NONE,
    )

    assert result.timeline_event.service_id == service.id
    assert result.readiness_results == []


def test_emit_service_catalog_event_passes_before_after_to_payload(monkeypatch):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    monkeypatch.setattr(
        catalog_events,
        "reconcile_service_readiness",
        lambda *args, **kwargs: {"state": {"status": "ok"}},
    )

    result = emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service_link.updated",
        title="Service link updated",
        payload={"source": "test"},
        before={"label": "Old"},
        after={"label": "New"},
    )

    event = ServiceEvent.get_by_id(result.timeline_event.id)
    assert event.payload == {
        "source": "test",
        "before": {"label": "Old"},
        "after": {"label": "New"},
    }


def test_emit_service_catalog_event_reconciles_explicit_service_set(monkeypatch):
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    other_service = create_service(team)
    calls = []

    def fake_list_services_by_ids(service_ids):
        calls.append({"listed_ids": set(service_ids)})
        return [service, other_service]

    def fake_reconcile_services_readiness(services, *, trigger, actor_user=None):
        calls.append({
            "service_ids": [item.id for item in services],
            "trigger": trigger,
            "actor_user": actor_user,
        })
        return [{"state": {"service_id": item.id}} for item in services]

    monkeypatch.setattr(catalog_events, "list_services_by_ids", fake_list_services_by_ids)
    monkeypatch.setattr(
        catalog_events,
        "reconcile_services_readiness",
        fake_reconcile_services_readiness,
    )

    result = emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service_owner.updated",
        title="Default stakeholder updated",
        affected_service_ids=[other_service.id],
        readiness_scope=READINESS_SCOPE_SERVICES,
        readiness_trigger="owner_updated",
    )

    assert calls == [
        {"listed_ids": {service.id, other_service.id}},
        {
            "service_ids": [service.id, other_service.id],
            "trigger": "owner_updated",
            "actor_user": None,
        },
    ]
    assert len(result.readiness_results) == 2


def test_emit_service_catalog_event_reconciles_dependency_component(monkeypatch):
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    dependency_service = create_service(team)
    calls = []

    def fake_reconcile_dependency_component(service_ids, *, trigger, actor_user=None):
        calls.append({"service_ids": set(service_ids), "trigger": trigger, "actor_user": actor_user})
        return [{"state": {"status": "ready"}}]

    monkeypatch.setattr(
        catalog_events,
        "reconcile_dependency_component",
        fake_reconcile_dependency_component,
    )

    result = emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service_dependency.updated",
        title="Service dependency updated",
        affected_service_ids=[dependency_service.id],
        readiness_scope=READINESS_SCOPE_DEPENDENCY_COMPONENT,
        readiness_trigger="service_dependency_updated",
    )

    assert calls == [
        {
            "service_ids": {service.id, dependency_service.id},
            "trigger": "service_dependency_updated",
            "actor_user": None,
        }
    ]
    assert len(result.readiness_results) == 1


def test_emit_service_catalog_event_reuses_deduplicated_timeline_event(monkeypatch):
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    monkeypatch.setattr(
        catalog_events,
        "reconcile_service_readiness",
        lambda *args, **kwargs: {"state": {"status": "ok"}},
    )

    first = emit_service_catalog_event(
        service,
        category="configuration",
        event_type="external.sync",
        title="External sync",
        source="test",
        dedup_key="sync:1",
    )
    second = emit_service_catalog_event(
        service,
        category="configuration",
        event_type="external.sync",
        title="External sync duplicate",
        source="test",
        dedup_key="sync:1",
    )

    assert second.timeline_event.id == first.timeline_event.id
    assert ServiceEvent.select().where(
        ServiceEvent.service == service.id,
        ServiceEvent.source == "test",
        ServiceEvent.dedup_key == "sync:1",
    ).count() == 1
