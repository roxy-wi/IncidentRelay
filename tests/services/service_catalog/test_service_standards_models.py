import uuid

import pytest
from peewee import IntegrityError

from app.modules.db.models import ServiceReadinessCheckResult, ServiceReadinessEvaluation, ServiceReadinessState, ServiceStandard, ServiceStandardCheck
from tests.factories import create_group, create_service, create_team


def create_standard(group, slug="production-services", name="Production services"):
    return ServiceStandard.create(group=group, slug=slug, name=name)


def create_check(standard, slug="owner-exists", name="Owner exists", check_type="owner_exists"):
    return ServiceStandardCheck.create(standard=standard, slug=slug, name=name, check_type=check_type)


def test_service_standard_gets_uuid():
    group = create_group()
    standard = create_standard(group)

    assert isinstance(standard.uid, uuid.UUID)


def test_service_standard_defaults_apply_to_all_services():
    group = create_group()
    standard = create_standard(group)

    assert standard.applies_to == {}
    assert standard.enabled is True


def test_service_standard_slug_is_unique_inside_group():
    group = create_group()
    create_standard(group)

    with pytest.raises(IntegrityError):
        create_standard(group)


def test_same_service_standard_slug_can_exist_in_different_groups():
    first_group = create_group()
    second_group = create_group()

    first = create_standard(first_group)
    second = create_standard(second_group)

    assert first.id != second.id


def test_service_standard_check_defaults():
    group = create_group()
    standard = create_standard(group)
    check = create_check(standard)

    assert isinstance(check.uid, uuid.UUID)
    assert check.configuration == {}
    assert check.weight == 1
    assert check.severity == "warning"
    assert check.required is True
    assert check.enabled is True


def test_service_standard_check_slug_is_unique_inside_standard():
    group = create_group()
    standard = create_standard(group)
    create_check(standard)

    with pytest.raises(IntegrityError):
        create_check(standard)


def test_same_check_slug_can_exist_in_different_standards():
    group = create_group()
    first_standard = create_standard(group, slug="tier-one")
    second_standard = create_standard(group, slug="tier-two")

    first = create_check(first_standard)
    second = create_check(second_standard)

    assert first.id != second.id


def test_readiness_evaluation_stores_check_result_snapshot():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    standard = create_standard(group)
    check = create_check(standard)
    batch_uid = uuid.uuid4()

    evaluation = ServiceReadinessEvaluation.create(batch_uid=batch_uid, service=service, standard=standard, status="not_ready", score=0, total_weight=1, checks_count=1, failed_count=1, failed_required_count=1)
    result = ServiceReadinessCheckResult.create(evaluation=evaluation, check=check, check_uid=check.uid, check_slug=check.slug, check_name=check.name, check_type=check.check_type, status="failed", weight=check.weight, severity=check.severity, required=check.required, message="Service has no owner")

    assert result.check_uid == check.uid
    assert result.check_slug == "owner-exists"
    assert result.check_name == "Owner exists"
    assert result.status == "failed"


def test_service_has_only_one_current_readiness_state():
    group = create_group()
    team = create_team(group)
    service = create_service(team)

    ServiceReadinessState.create(service=service, batch_uid=uuid.uuid4(), status="ready", score=100)

    with pytest.raises(IntegrityError):
        ServiceReadinessState.create(service=service, batch_uid=uuid.uuid4(), status="warning", score=80)


def test_readiness_evaluations_keep_history():
    group = create_group()
    team = create_team(group)
    service = create_service(team)
    standard = create_standard(group)

    first = ServiceReadinessEvaluation.create(batch_uid=uuid.uuid4(), service=service, standard=standard, status="not_ready", score=40)
    second = ServiceReadinessEvaluation.create(batch_uid=uuid.uuid4(), service=service, standard=standard, status="ready", score=100)

    evaluations = list(ServiceReadinessEvaluation.select().where(ServiceReadinessEvaluation.service == service).order_by(ServiceReadinessEvaluation.evaluated_at, ServiceReadinessEvaluation.id))

    assert [evaluation.id for evaluation in evaluations] == [first.id, second.id]
