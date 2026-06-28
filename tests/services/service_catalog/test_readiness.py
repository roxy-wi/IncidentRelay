from app.modules.db.models import (
    ServiceDependency,
    ServiceEvent,
    ServiceLink,
    ServiceOwner,
    ServiceReadinessCheckResult,
    ServiceReadinessEvaluation,
    ServiceReadinessState,
    ServiceRunbook,
    ServiceStandard,
    ServiceStandardCheck,
)
from app.services.service_catalog.readiness import evaluate_service_readiness
from app.services.service_catalog.standards import (
    list_applicable_standards,
    standard_applies_to_service,
)
from tests.factories import (
    create_group,
    create_service,
    create_team,
    create_user,
)


def create_standard(group, *, slug="production", applies_to=None):
    return ServiceStandard.create(
        group=group,
        slug=slug,
        name=slug.replace("-", " ").title(),
        applies_to=applies_to or {},
    )


def create_check(
    standard,
    *,
    slug,
    check_type,
    configuration=None,
    weight=1,
    severity="warning",
    required=True,
    position=0,
):
    return ServiceStandardCheck.create(
        standard=standard,
        slug=slug,
        name=slug.replace("-", " ").title(),
        check_type=check_type,
        configuration=configuration or {},
        weight=weight,
        severity=severity,
        required=required,
        position=position,
    )


def test_standard_applies_to_matching_service():
    group = create_group()
    team = create_team(group)
    service = create_service(
        team,
        environment="production",
        criticality="critical",
        tier="tier_1",
    )
    service.labels = {"customer_facing": "true"}
    service.save(only=[service.__class__.labels])

    standard = create_standard(
        group,
        applies_to={
            "kinds": ["technical"],
            "lifecycles": ["production"],
            "environments": ["production"],
            "tiers": ["tier_1"],
            "criticalities": ["critical"],
            "labels": {"customer_facing": "true"},
        },
    )

    assert standard_applies_to_service(standard, service) is True
    assert list_applicable_standards(service) == [standard]


def test_standard_does_not_apply_when_label_does_not_match():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    service.labels = {"customer_facing": "false"}
    service.save(only=[service.__class__.labels])

    standard = create_standard(
        group,
        applies_to={"labels": {"customer_facing": "true"}},
    )

    assert standard_applies_to_service(standard, service) is False
    assert list_applicable_standards(service) == []


def test_readiness_passes_field_check():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    standard = create_standard(group)

    create_check(
        standard,
        slug="name-present",
        check_type="field_present",
        configuration={"field": "name"},
        weight=10,
    )

    result = evaluate_service_readiness(service)
    state = result["state"]

    assert state.status == "ready"
    assert state.score == 100
    assert state.failed_count == 0
    assert len(result["evaluations"]) == 1


def test_required_failure_caps_status_at_warning():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    standard = create_standard(group)

    create_check(
        standard,
        slug="description-present",
        check_type="field_present",
        configuration={"field": "description"},
        weight=1,
        required=True,
    )
    create_check(
        standard,
        slug="name-present",
        check_type="field_present",
        configuration={"field": "name"},
        weight=9,
        required=True,
        position=1,
    )

    state = evaluate_service_readiness(service)["state"]

    assert state.score == 90
    assert state.status == "warning"
    assert state.failed_required_count == 1


def test_critical_failure_marks_service_not_ready():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    standard = create_standard(group)

    create_check(
        standard,
        slug="description-present",
        check_type="field_present",
        configuration={"field": "description"},
        weight=1,
        severity="critical",
        required=False,
    )
    create_check(
        standard,
        slug="name-present",
        check_type="field_present",
        configuration={"field": "name"},
        weight=9,
        position=1,
    )

    state = evaluate_service_readiness(service)["state"]

    assert state.score == 90
    assert state.status == "not_ready"
    assert state.failed_critical_count == 1


def test_owner_runbook_and_dashboard_checks_pass():
    group = create_group()
    team = create_team(group)
    user = create_user(group=group)
    service = create_service(team)
    standard = create_standard(group)

    ServiceOwner.create(
        service=service,
        user=user,
        role="owner",
        active=True,
    )
    ServiceRunbook.create(
        service=service,
        title="Production incidents",
        url="https://example.com/runbook",
        enabled=True,
    )
    ServiceLink.create(
        service=service,
        link_type="dashboard",
        label="Grafana",
        url="https://example.com/dashboard",
        enabled=True,
    )

    create_check(
        standard,
        slug="owner",
        check_type="owner_exists",
        configuration={"roles": ["owner"]},
    )
    create_check(
        standard,
        slug="runbook",
        check_type="runbook_exists",
        position=1,
    )
    create_check(
        standard,
        slug="dashboard",
        check_type="link_type_exists",
        configuration={"link_type": "dashboard"},
        position=2,
    )

    state = evaluate_service_readiness(service)["state"]

    assert state.status == "ready"
    assert state.score == 100
    assert state.checks_count == 3


def test_dependency_cycle_check_fails_for_cycle():
    group = create_group()
    team = create_team(group)
    first_service = create_service(team)
    second_service = create_service(team)
    standard = create_standard(group)

    ServiceDependency.create(
        service=first_service,
        depends_on_service=second_service,
    )
    ServiceDependency.create(
        service=second_service,
        depends_on_service=first_service,
    )

    create_check(
        standard,
        slug="no-dependency-cycle",
        check_type="dependency_cycle_absent",
        severity="critical",
    )

    result = evaluate_service_readiness(first_service)
    evaluation = result["evaluations"][0]
    check_result = ServiceReadinessCheckResult.get(
        ServiceReadinessCheckResult.evaluation == evaluation.id
    )

    assert result["state"].status == "not_ready"
    assert check_result.status == "failed"
    assert check_result.details["cycle_service_ids"] == [
        first_service.id,
        second_service.id,
        first_service.id,
    ]


def test_unknown_check_type_is_an_evaluation_error():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    standard = create_standard(group)

    create_check(
        standard,
        slug="unknown",
        check_type="unknown_check",
        required=False,
    )

    result = evaluate_service_readiness(service)
    evaluation = result["evaluations"][0]
    check_result = ServiceReadinessCheckResult.get(
        ServiceReadinessCheckResult.evaluation == evaluation.id
    )

    assert result["state"].status == "not_ready"
    assert check_result.status == "error"
    assert "Unsupported readiness check type" in check_result.message


def test_readiness_evaluations_keep_history():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    standard = create_standard(group)

    create_check(
        standard,
        slug="name-present",
        check_type="field_present",
        configuration={"field": "name"},
    )

    evaluate_service_readiness(service)
    evaluate_service_readiness(service)

    evaluations = ServiceReadinessEvaluation.select().where(
        ServiceReadinessEvaluation.service == service.id
    )

    assert evaluations.count() == 2
    assert ServiceReadinessState.select().where(
        ServiceReadinessState.service == service.id
    ).count() == 1


def test_unchanged_readiness_does_not_publish_duplicate_event():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    standard = create_standard(group)

    create_check(
        standard,
        slug="name-present",
        check_type="field_present",
        configuration={"field": "name"},
    )

    evaluate_service_readiness(service)
    evaluate_service_readiness(service)

    events = ServiceEvent.select().where(
        ServiceEvent.service == service.id,
        ServiceEvent.category == "readiness",
    )

    assert events.count() == 1
    assert events.get().event_type == "readiness.evaluated"


def test_changed_readiness_publishes_score_changed_event():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    standard = create_standard(group)

    create_check(
        standard,
        slug="description-present",
        check_type="field_present",
        configuration={"field": "description"},
    )

    first_state = evaluate_service_readiness(service)["state"]

    service.description = "Production service"
    service.save(only=[service.__class__.description])

    second_state = evaluate_service_readiness(service)["state"]

    events = list(
        ServiceEvent.select()
        .where(
            ServiceEvent.service == service.id,
            ServiceEvent.category == "readiness",
        )
        .order_by(ServiceEvent.id)
    )

    assert first_state.status == "not_ready"
    assert second_state.status == "ready"
    assert [event.event_type for event in events] == [
        "readiness.evaluated",
        "readiness.score_changed",
    ]
