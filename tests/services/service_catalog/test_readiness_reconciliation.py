from app.modules.db.models import (
    ServiceReadinessEvaluation,
    ServiceReadinessState,
    ServiceStandard,
    ServiceStandardCheck,
    ServiceDependency,
    AlertRoute,
    EscalationPolicy,
    NotificationPolicy,
    Rotation,
    ServiceMatchRule,
)
from app.services.service_catalog.reconciliation import (
    list_group_services,
    reconcile_group_readiness,
    reconcile_service_readiness,
    list_dependency_component_services,
    reconcile_dependency_component,
    list_services_for_escalation_policy,
    list_services_for_notification_policy,
    list_services_for_rotation,
    list_services_for_route,
    reconcile_escalation_policy_services,
    reconcile_notification_policy_services,
    reconcile_rotation_services,
    reconcile_route_services,
    list_services_by_rotation,
    list_services_by_route,
)
from tests.factories import create_group, create_rotation, create_route, create_service, create_team


def create_description_standard(group):
    standard = ServiceStandard.create(
        group=group,
        slug="description-required",
        name="Description required",
    )
    ServiceStandardCheck.create(
        standard=standard,
        slug="description-present",
        name="Description present",
        check_type="field_present",
        configuration={"field": "description"},
        weight=10,
        severity="critical",
        required=True,
    )

    return standard


def test_reconcile_service_readiness_creates_state():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    create_description_standard(group)

    result = reconcile_service_readiness(
        service,
        trigger="service_created",
    )

    assert result["state"].service_id == service.id
    assert result["state"].status == "not_ready"
    assert result["state"].score == 0


def test_reconcile_service_readiness_updates_existing_state():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    create_description_standard(group)

    first_result = reconcile_service_readiness(
        service,
        trigger="service_created",
    )

    service.description = "Production service"
    service.save(only=[service.__class__.description])

    second_result = reconcile_service_readiness(
        service,
        trigger="service_updated",
    )

    assert first_result["state"].status == "not_ready"
    assert second_result["state"].status == "ready"
    assert second_result["state"].score == 100
    assert ServiceReadinessState.select().where(
        ServiceReadinessState.service == service.id
    ).count() == 1


def test_list_group_services_uses_team_group():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    service.group = None
    service.save(only=[service.__class__.group])

    services = list_group_services(group.id)

    assert [item.id for item in services] == [service.id]


def test_list_group_services_excludes_deleted_services():
    group = create_group()
    team = create_team(group)
    active_service = create_service(team)
    deleted_service = create_service(team)

    deleted_service.deleted = True
    deleted_service.save(only=[deleted_service.__class__.deleted])

    services = list_group_services(group.id)

    assert [service.id for service in services] == [active_service.id]


def test_reconcile_group_readiness_evaluates_all_group_services():
    group = create_group()
    team = create_team(group)
    first_service = create_service(team)
    second_service = create_service(team)
    create_description_standard(group)

    results = reconcile_group_readiness(
        group.id,
        trigger="standard_created",
    )

    assert len(results) == 2

    states = {
        state.service_id: state
        for state in ServiceReadinessState.select()
    }

    assert states[first_service.id].status == "not_ready"
    assert states[second_service.id].status == "not_ready"


def test_reconcile_group_readiness_does_not_touch_other_groups():
    first_group = create_group()
    second_group = create_group()
    first_team = create_team(first_group)
    second_team = create_team(second_group)
    first_service = create_service(first_team)
    second_service = create_service(second_team)
    create_description_standard(first_group)

    reconcile_group_readiness(
        first_group.id,
        trigger="standard_created",
    )

    assert ServiceReadinessState.get_or_none(
        ServiceReadinessState.service == first_service.id
    ) is not None
    assert ServiceReadinessState.get_or_none(
        ServiceReadinessState.service == second_service.id
    ) is None


def test_reconcile_group_readiness_preserves_evaluation_history():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    create_description_standard(group)

    reconcile_group_readiness(
        group.id,
        trigger="standard_created",
    )
    reconcile_group_readiness(
        group.id,
        trigger="standard_updated",
    )

    evaluations = ServiceReadinessEvaluation.select().where(
        ServiceReadinessEvaluation.service == service.id
    )

    assert evaluations.count() == 2


def test_list_dependency_component_services_returns_transitive_component():
    group = create_group()
    team = create_team(group)
    first_service = create_service(team)
    second_service = create_service(team)
    third_service = create_service(team)
    unrelated_service = create_service(team)

    ServiceDependency.create(
        service=first_service,
        depends_on_service=second_service,
    )
    ServiceDependency.create(
        service=second_service,
        depends_on_service=third_service,
    )

    services = list_dependency_component_services([first_service.id])

    assert [service.id for service in services] == [
        first_service.id,
        second_service.id,
        third_service.id,
    ]
    assert unrelated_service.id not in {service.id for service in services}


def test_reconcile_dependency_component_updates_all_related_services():
    group = create_group()
    team = create_team(group)
    first_service = create_service(team)
    second_service = create_service(team)
    third_service = create_service(team)
    standard = ServiceStandard.create(
        group=group,
        slug="dependency-graph",
        name="Dependency graph",
    )

    ServiceStandardCheck.create(
        standard=standard,
        slug="no-cycle",
        name="No dependency cycle",
        check_type="dependency_cycle_absent",
        severity="critical",
        required=True,
    )

    ServiceDependency.create(
        service=first_service,
        depends_on_service=second_service,
    )
    ServiceDependency.create(
        service=second_service,
        depends_on_service=third_service,
    )

    results = reconcile_dependency_component(
        [first_service.id],
        trigger="service_dependency_created",
    )

    assert len(results) == 3

    states = {
        state.service_id: state
        for state in ServiceReadinessState.select()
    }

    assert states[first_service.id].status == "ready"
    assert states[second_service.id].status == "ready"
    assert states[third_service.id].status == "ready"


def test_list_services_for_rotation():
    group = create_group()
    team = create_team(group)
    rotation = create_rotation(team, name="Primary")
    matching_service = create_service(team)
    unrelated_service = create_service(team)

    matching_service.default_rotation = rotation
    matching_service.save(only=[matching_service.__class__.default_rotation])

    services = list_services_by_rotation(rotation.id)

    assert [service.id for service in services] == [matching_service.id]
    assert unrelated_service.id not in {service.id for service in services}


def test_list_services_for_escalation_policy():
    group = create_group()
    team = create_team(group)
    policy = EscalationPolicy.create(team=team, name="Primary")
    service = create_service(team)

    service.default_escalation_policy = policy
    service.save(only=[service.__class__.default_escalation_policy])

    services = list_services_for_escalation_policy(policy.id)

    assert [item.id for item in services] == [service.id]


def test_list_services_for_notification_policy():
    group = create_group()
    team = create_team(group)
    policy = NotificationPolicy.create(team=team, name="Default")
    service = create_service(team)

    service.notification_policy = policy
    service.save(only=[service.__class__.notification_policy])

    services = list_services_for_notification_policy(policy.id)

    assert [item.id for item in services] == [service.id]


def test_list_services_for_route_through_match_rule():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    route = create_route(team, name="Primary")

    ServiceMatchRule.create(
        team=team,
        service=service,
        route=route,
        name="Production alerts",
        matchers={"environment": "production"},
        enabled=True,
    )

    services = list_services_by_route(route.id)

    assert [item.id for item in services] == [service.id]


def test_reconcile_rotation_services_updates_matching_service():
    group = create_group()
    team = create_team(group)
    rotation = create_rotation(team, name="Primary")
    service = create_service(team)
    standard = ServiceStandard.create(
        group=group,
        slug="rotation-required",
        name="Rotation required",
    )

    ServiceStandardCheck.create(
        standard=standard,
        slug="active-rotation",
        name="Active rotation",
        check_type="active_rotation_exists",
        severity="critical",
        required=True,
    )

    reconcile_service_readiness(service, trigger="test")

    state = ServiceReadinessState.get(
        ServiceReadinessState.service == service.id
    )

    assert state.status == "not_ready"

    service.default_rotation = rotation
    service.save(only=[service.__class__.default_rotation])

    reconcile_rotation_services(
        rotation.id,
        trigger="rotation_updated",
    )

    state = ServiceReadinessState.get(
        ServiceReadinessState.service == service.id
    )

    assert state.status == "ready"
