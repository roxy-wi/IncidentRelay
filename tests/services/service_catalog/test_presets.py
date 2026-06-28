from app.modules.db.models import ServiceStandard, ServiceStandardCheck
from app.services.service_catalog.presets import BASIC_OPERATIONAL_STANDARD_SLUG, ensure_basic_operational_standard
from tests.factories import create_group


def test_ensure_basic_operational_standard_creates_standard_and_checks():
    group = create_group()

    result = ensure_basic_operational_standard(group)
    standard = result["standard"]

    checks = list(
        ServiceStandardCheck.select()
        .where(ServiceStandardCheck.standard == standard.id)
        .order_by(ServiceStandardCheck.position)
    )

    assert result["standard_created"] is True
    assert standard.slug == BASIC_OPERATIONAL_STANDARD_SLUG
    assert standard.applies_to == {
        "kinds": ["technical"],
        "lifecycles": ["production"],
    }
    assert [check.slug for check in checks] == [
        "owner",
        "escalation-policy",
        "notification-policy",
        "alert-route",
        "runbook",
        "dependency-cycle",
    ]
    assert [check.weight for check in checks] == [15, 20, 20, 20, 15, 10]
    assert sum(check.weight for check in checks) == 100


def test_ensure_basic_operational_standard_is_idempotent():
    group = create_group()

    first = ensure_basic_operational_standard(group)
    second = ensure_basic_operational_standard(group)

    assert first["standard"].id == second["standard"].id
    assert second["standard_created"] is False
    assert second["created_checks"] == []
    assert ServiceStandard.select().where(ServiceStandard.group == group.id).count() == 1
    assert ServiceStandardCheck.select().where(ServiceStandardCheck.standard == first["standard"].id).count() == 6


def test_ensure_basic_operational_standard_does_not_overwrite_existing_check():
    group = create_group()
    result = ensure_basic_operational_standard(group)
    standard = result["standard"]

    check = ServiceStandardCheck.get(
        ServiceStandardCheck.standard == standard.id,
        ServiceStandardCheck.slug == "runbook",
    )
    check.weight = 10
    check.save(only=[ServiceStandardCheck.weight])

    ensure_basic_operational_standard(group)

    check = ServiceStandardCheck.get_by_id(check.id)

    assert check.weight == 10
