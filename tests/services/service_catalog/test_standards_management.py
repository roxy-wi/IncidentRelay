import pytest
from peewee import DoesNotExist

from app.modules.db.models import ServiceStandard, ServiceStandardCheck
from app.services.service_catalog.standards import (
    ServiceStandardValidationError,
    create_service_standard,
    create_standard_check,
    delete_service_standard,
    delete_standard_check,
    get_service_standard,
    get_standard_check,
    list_service_standards,
    list_standard_checks,
    update_service_standard,
    update_standard_check,
    validate_standard_applies_to,
    validate_standard_check,
)
from tests.factories import create_group


def test_validate_standard_applies_to_normalizes_values():
    result = validate_standard_applies_to({
        "kinds": ["technical", "technical"],
        "lifecycles": ["production"],
        "labels": {"customer_facing": "true"},
    })

    assert result == {
        "kinds": ["technical"],
        "lifecycles": ["production"],
        "labels": {"customer_facing": "true"},
    }


def test_validate_standard_applies_to_rejects_unknown_field():
    with pytest.raises(ServiceStandardValidationError) as exc:
        validate_standard_applies_to({"unknown": ["value"]})

    assert "Unsupported applies_to fields" in str(exc.value)


def test_validate_standard_applies_to_rejects_unknown_value():
    with pytest.raises(ServiceStandardValidationError) as exc:
        validate_standard_applies_to({"kinds": ["unknown"]})

    assert "Unsupported values" in str(exc.value)


def test_validate_standard_check_rejects_unknown_type():
    with pytest.raises(ServiceStandardValidationError) as exc:
        validate_standard_check("unknown", {})

    assert "Unsupported readiness check type" in str(exc.value)


def test_validate_standard_check_requires_field():
    with pytest.raises(ServiceStandardValidationError) as exc:
        validate_standard_check("field_present", {})

    assert "Missing configuration fields" in str(exc.value)


def test_validate_standard_check_rejects_unknown_configuration_field():
    with pytest.raises(ServiceStandardValidationError) as exc:
        validate_standard_check(
            "owner_exists",
            {"minimum": 1, "unknown": True},
        )

    assert "Unsupported configuration fields" in str(exc.value)


def test_validate_standard_check_rejects_invalid_owner_role():
    with pytest.raises(ServiceStandardValidationError) as exc:
        validate_standard_check(
            "owner_exists",
            {"roles": ["invalid"]},
        )

    assert "Unsupported values" in str(exc.value)


def test_validate_standard_check_rejects_both_link_fields():
    with pytest.raises(ServiceStandardValidationError) as exc:
        validate_standard_check(
            "link_type_exists",
            {
                "link_type": "dashboard",
                "link_types": ["dashboard"],
            },
        )

    assert 'Use either "link_type" or "link_types"' in str(exc.value)


def test_create_and_get_service_standard():
    group = create_group()

    standard = create_service_standard({
        "group": group.id,
        "slug": "production-services",
        "name": "Production services",
        "description": "Production readiness requirements",
        "applies_to": {
            "kinds": ["technical"],
            "lifecycles": ["production"],
        },
        "enabled": True,
    })

    loaded = get_service_standard(standard.id)

    assert loaded.id == standard.id
    assert loaded.group_id == group.id
    assert loaded.applies_to["kinds"] == ["technical"]


def test_update_service_standard():
    group = create_group()
    standard = ServiceStandard.create(
        group=group,
        slug="production",
        name="Production",
    )

    updated = update_service_standard(
        standard,
        {
            "name": "Production services",
            "enabled": False,
            "applies_to": {"tiers": ["tier_1"]},
        },
    )

    assert updated.name == "Production services"
    assert updated.enabled is False
    assert updated.applies_to == {"tiers": ["tier_1"]}


def test_list_service_standards_filters_groups():
    first_group = create_group()
    second_group = create_group()

    first = ServiceStandard.create(
        group=first_group,
        slug="first",
        name="First",
    )
    ServiceStandard.create(
        group=second_group,
        slug="second",
        name="Second",
    )

    standards = list_service_standards([first_group.id])

    assert [standard.id for standard in standards] == [first.id]


def test_list_service_standards_excludes_disabled_by_default():
    group = create_group()

    active = ServiceStandard.create(
        group=group,
        slug="active",
        name="Active",
    )
    ServiceStandard.create(
        group=group,
        slug="disabled",
        name="Disabled",
        enabled=False,
    )

    standards = list_service_standards([group.id])

    assert [standard.id for standard in standards] == [active.id]


def test_create_standard_check():
    group = create_group()
    standard = ServiceStandard.create(
        group=group,
        slug="production",
        name="Production",
    )

    check = create_standard_check(
        standard,
        {
            "slug": "owner-exists",
            "name": "Owner exists",
            "description": None,
            "check_type": "owner_exists",
            "configuration": {
                "roles": ["owner"],
                "minimum": 1,
            },
            "weight": 10,
            "severity": "critical",
            "required": True,
            "enabled": True,
            "position": 0,
        },
    )

    assert check.standard_id == standard.id
    assert check.configuration["roles"] == ["owner"]
    assert check.weight == 10


def test_update_standard_check_revalidates_configuration():
    group = create_group()
    standard = ServiceStandard.create(
        group=group,
        slug="production",
        name="Production",
    )
    check = ServiceStandardCheck.create(
        standard=standard,
        slug="description",
        name="Description",
        check_type="field_present",
        configuration={"field": "description"},
    )

    updated = update_standard_check(
        check,
        {
            "check_type": "field_equals",
            "configuration": {
                "field": "environment",
                "value": "production",
            },
        },
    )

    assert updated.check_type == "field_equals"
    assert updated.configuration["value"] == "production"


def test_get_standard_check_is_scoped_to_standard():
    group = create_group()
    first_standard = ServiceStandard.create(
        group=group,
        slug="first",
        name="First",
    )
    second_standard = ServiceStandard.create(
        group=group,
        slug="second",
        name="Second",
    )
    check = ServiceStandardCheck.create(
        standard=first_standard,
        slug="owner",
        name="Owner",
        check_type="owner_exists",
    )

    with pytest.raises(DoesNotExist):
        get_standard_check(second_standard.id, check.id)


def test_list_standard_checks_orders_by_position():
    group = create_group()
    standard = ServiceStandard.create(
        group=group,
        slug="production",
        name="Production",
    )
    second = ServiceStandardCheck.create(
        standard=standard,
        slug="second",
        name="Second",
        check_type="owner_exists",
        position=20,
    )
    first = ServiceStandardCheck.create(
        standard=standard,
        slug="first",
        name="First",
        check_type="owner_exists",
        position=10,
    )

    checks = list_standard_checks(standard.id)

    assert [check.id for check in checks] == [first.id, second.id]


def test_delete_standard_check_soft_deletes_check():
    group = create_group()
    standard = ServiceStandard.create(
        group=group,
        slug="production",
        name="Production",
    )
    check = ServiceStandardCheck.create(
        standard=standard,
        slug="owner",
        name="Owner",
        check_type="owner_exists",
    )

    delete_standard_check(check)
    check = ServiceStandardCheck.get_by_id(check.id)

    assert check.deleted is True
    assert check.enabled is False


def test_delete_service_standard_soft_deletes_checks():
    group = create_group()
    standard = ServiceStandard.create(
        group=group,
        slug="production",
        name="Production",
    )
    check = ServiceStandardCheck.create(
        standard=standard,
        slug="owner",
        name="Owner",
        check_type="owner_exists",
    )

    delete_service_standard(standard)

    standard = ServiceStandard.get_by_id(standard.id)
    check = ServiceStandardCheck.get_by_id(check.id)

    assert standard.deleted is True
    assert standard.enabled is False
    assert check.deleted is True
    assert check.enabled is False
