from datetime import timedelta

from app.modules.common import utc_now
from app.modules.db import routes_repo, services_repo
from app.modules.db.models import (
    AlertGroup,
    AutomationExecution,
    EventOrchestration,
    EventOrchestrationVersion,
    OrchestrationExecution,
    OrchestrationWebhookAction,
    PendingOrchestratedEvent,
)
from app.services.orchestration import webhooks as webhook_service
from tests.factories import (
    create_group,
    create_impact_alert_group,
    create_route,
    create_service,
    create_team,
    unique,
)


def _orchestration(group, *, service=None):
    orchestration = EventOrchestration.create(
        group=group,
        name=unique("orchestration"),
        scope="service" if service is not None else "global",
        service=service,
        enabled=True,
        mode="active",
        compatibility_mode="hybrid",
    )
    version = EventOrchestrationVersion.create(
        orchestration=orchestration,
        version_number=1,
        status="draft",
        definition_json={},
    )
    return orchestration, version


def _webhook_action(group):
    return OrchestrationWebhookAction.create(
        group=group,
        name=unique("webhook-action"),
        url="https://hooks.example.test/action",
        method="POST",
    )


def _automation_execution(
    *,
    group,
    orchestration,
    version,
    action,
    alert_group,
):
    orchestration_execution = OrchestrationExecution.create(
        group=group,
        orchestration=orchestration,
        version=version,
        source="pytest",
        alert_group_id=alert_group.id,
    )
    return AutomationExecution.create(
        action=action,
        orchestration_execution=orchestration_execution,
        group=group,
        alert_group_id=alert_group.id,
        idempotency_key=unique("automation"),
        status="pending",
        request_metadata_json={
            "url": "https://hooks.example.test/action",
            "method": "POST",
            "timeout_seconds": 5,
            "retry_count": 0,
            "private_network_policy": "deny",
        },
    )


def _pending_event(
    *,
    group,
    orchestration,
    version,
    route,
    service,
):
    return PendingOrchestratedEvent.create(
        group=group,
        orchestration=orchestration,
        version=version,
        route=route,
        service=service,
        source="alertmanager",
        dedup_key=unique("pending-event"),
        normalized_event_json={},
        context_json={},
        activation_at=utc_now() + timedelta(minutes=10),
        status="pending",
    )


def test_service_soft_delete_cancels_global_and_service_work_before_detach(
    db,
    monkeypatch,
):
    group = create_group()
    team = create_team(group)
    target_service = create_service(team, name="Target")
    other_service = create_service(team, name="Other")
    target_route = create_route(team, service=target_service)
    other_route = create_route(team, service=other_service)

    target_alert_group = create_impact_alert_group(
        team=team,
        service=target_service,
        route=target_route,
    )
    other_alert_group = create_impact_alert_group(
        team=team,
        service=other_service,
        route=other_route,
    )

    action = _webhook_action(group)
    global_orchestration, global_version = _orchestration(group)
    service_orchestration, service_version = _orchestration(
        group,
        service=target_service,
    )

    global_work = _automation_execution(
        group=group,
        orchestration=global_orchestration,
        version=global_version,
        action=action,
        alert_group=target_alert_group,
    )
    service_work = _automation_execution(
        group=group,
        orchestration=service_orchestration,
        version=service_version,
        action=action,
        alert_group=target_alert_group,
    )
    unrelated_work = _automation_execution(
        group=group,
        orchestration=global_orchestration,
        version=global_version,
        action=action,
        alert_group=other_alert_group,
    )

    global_pending = _pending_event(
        group=group,
        orchestration=global_orchestration,
        version=global_version,
        route=target_route,
        service=target_service,
    )
    service_pending = _pending_event(
        group=group,
        orchestration=service_orchestration,
        version=service_version,
        route=target_route,
        service=target_service,
    )
    unrelated_pending = _pending_event(
        group=group,
        orchestration=global_orchestration,
        version=global_version,
        route=other_route,
        service=other_service,
    )

    claimed = webhook_service._claim_one(service_work.id, now=utc_now())
    assert claimed is not None

    deliveries = []

    def fake_deliver_webhook(**kwargs):
        deliveries.append(kwargs)
        return webhook_service.WebhookResponse(
            status=204,
            body=b"",
            final_url="https://hooks.example.test/action",
            redirects=0,
        )

    monkeypatch.setattr(webhook_service, "deliver_webhook", fake_deliver_webhook)

    services_repo.soft_delete_service(target_service.id)

    global_work = AutomationExecution.get_by_id(global_work.id)
    service_work = AutomationExecution.get_by_id(service_work.id)
    unrelated_work = AutomationExecution.get_by_id(unrelated_work.id)
    global_pending = PendingOrchestratedEvent.get_by_id(global_pending.id)
    service_pending = PendingOrchestratedEvent.get_by_id(service_pending.id)
    unrelated_pending = PendingOrchestratedEvent.get_by_id(unrelated_pending.id)
    target_alert_group = AlertGroup.get_by_id(target_alert_group.id)
    other_alert_group = AlertGroup.get_by_id(other_alert_group.id)
    service_orchestration = EventOrchestration.get_by_id(service_orchestration.id)

    assert global_work.status == "cancelled"
    assert global_work.error_safe == "service_deleted"
    assert service_work.status == "cancelled"
    assert service_work.error_safe == "service_deleted"
    assert service_work.claim_token is None
    assert service_work.claimed_at is None
    assert unrelated_work.status == "pending"

    assert global_pending.status == "cancelled"
    assert global_pending.last_error == "service_deleted"
    assert service_pending.status == "cancelled"
    assert service_pending.last_error == "service_deleted"
    assert unrelated_pending.status == "pending"

    assert target_alert_group.service_id is None
    assert other_alert_group.service_id == other_service.id
    assert service_orchestration.deleted is True

    # The worker object was claimed before soft-delete. It must observe that
    # its DB claim was cancelled and skip the external side effect.
    assert webhook_service._deliver_claimed(claimed, now=utc_now()) == "cancelled"
    assert deliveries == []


def test_service_soft_delete_cancels_global_work_with_no_service_orchestration(db):
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    route = create_route(team, service=service)
    alert_group = create_impact_alert_group(
        team=team,
        service=service,
        route=route,
    )

    action = _webhook_action(group)
    orchestration, version = _orchestration(group)
    work = _automation_execution(
        group=group,
        orchestration=orchestration,
        version=version,
        action=action,
        alert_group=alert_group,
    )
    pending = _pending_event(
        group=group,
        orchestration=orchestration,
        version=version,
        route=route,
        service=service,
    )

    services_repo.soft_delete_service(service.id)

    assert AutomationExecution.get_by_id(work.id).status == "cancelled"
    assert PendingOrchestratedEvent.get_by_id(pending.id).status == "cancelled"


def test_route_soft_delete_cancels_global_and_service_work_before_detach(db):
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    target_route = create_route(team, service=service)
    other_route = create_route(team, service=service)

    target_alert_group = create_impact_alert_group(
        team=team,
        service=service,
        route=target_route,
    )
    other_alert_group = create_impact_alert_group(
        team=team,
        service=service,
        route=other_route,
    )

    action = _webhook_action(group)
    global_orchestration, global_version = _orchestration(group)
    service_orchestration, service_version = _orchestration(
        group,
        service=service,
    )

    global_work = _automation_execution(
        group=group,
        orchestration=global_orchestration,
        version=global_version,
        action=action,
        alert_group=target_alert_group,
    )
    service_work = _automation_execution(
        group=group,
        orchestration=service_orchestration,
        version=service_version,
        action=action,
        alert_group=target_alert_group,
    )
    unrelated_work = _automation_execution(
        group=group,
        orchestration=global_orchestration,
        version=global_version,
        action=action,
        alert_group=other_alert_group,
    )

    global_pending = _pending_event(
        group=group,
        orchestration=global_orchestration,
        version=global_version,
        route=target_route,
        service=service,
    )
    service_pending = _pending_event(
        group=group,
        orchestration=service_orchestration,
        version=service_version,
        route=target_route,
        service=service,
    )
    unrelated_pending = _pending_event(
        group=group,
        orchestration=global_orchestration,
        version=global_version,
        route=other_route,
        service=service,
    )

    routes_repo.soft_delete_route(target_route.id)

    assert AutomationExecution.get_by_id(global_work.id).status == "cancelled"
    assert AutomationExecution.get_by_id(service_work.id).status == "cancelled"
    assert AutomationExecution.get_by_id(unrelated_work.id).status == "pending"
    assert PendingOrchestratedEvent.get_by_id(global_pending.id).status == "cancelled"
    assert PendingOrchestratedEvent.get_by_id(service_pending.id).status == "cancelled"
    assert PendingOrchestratedEvent.get_by_id(unrelated_pending.id).status == "pending"

    target_alert_group = AlertGroup.get_by_id(target_alert_group.id)
    other_alert_group = AlertGroup.get_by_id(other_alert_group.id)
    assert target_alert_group.route_id is None
    assert other_alert_group.route_id == other_route.id


def test_soft_delete_webhook_action_only_cancels_that_action(db):
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    route = create_route(team, service=service)
    alert_group = create_impact_alert_group(
        team=team,
        service=service,
        route=route,
    )
    orchestration, version = _orchestration(group)
    first_action = _webhook_action(group)
    second_action = _webhook_action(group)

    first_work = _automation_execution(
        group=group,
        orchestration=orchestration,
        version=version,
        action=first_action,
        alert_group=alert_group,
    )
    second_work = _automation_execution(
        group=group,
        orchestration=orchestration,
        version=version,
        action=second_action,
        alert_group=alert_group,
    )

    webhook_service.soft_delete_webhook_action(first_action.id)

    assert AutomationExecution.get_by_id(first_work.id).status == "cancelled"
    assert AutomationExecution.get_by_id(first_work.id).error_safe == (
        "webhook_action_deleted"
    )
    assert AutomationExecution.get_by_id(second_work.id).status == "pending"
