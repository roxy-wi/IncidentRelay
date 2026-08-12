from datetime import datetime

from peewee import IntegrityError

from app.modules.db.models import ServiceStandard, ServiceStandardCheck
from app.modules.common import utc_now


BASIC_OPERATIONAL_STANDARD_SLUG = "basic-operational-readiness"

BASIC_OPERATIONAL_STANDARD = {
    "slug": BASIC_OPERATIONAL_STANDARD_SLUG,
    "name": "Basic operational readiness",
    "description": "Default readiness requirements for production technical services.",
    "applies_to": {
        "kinds": ["technical"],
        "lifecycles": ["production"],
    },
    "enabled": True,
}

BASIC_OPERATIONAL_CHECKS = [
    {
        "slug": "owner",
        "name": "Owner configured",
        "description": "Service must have at least one active owner.",
        "check_type": "owner_exists",
        "configuration": {"minimum": 1},
        "weight": 15,
        "severity": "critical",
        "required": True,
        "enabled": True,
        "position": 10,
    },
    {
        "slug": "escalation-policy",
        "name": "Escalation policy configured",
        "description": "Service must have an active escalation policy with active rules.",
        "check_type": "escalation_policy_exists",
        "configuration": {"require_rules": True},
        "weight": 20,
        "severity": "critical",
        "required": True,
        "enabled": True,
        "position": 20,
    },
    {
        "slug": "notification-policy",
        "name": "Notification policy configured",
        "description": "Service must have an active notification policy with active channels.",
        "check_type": "notification_policy_exists",
        "configuration": {"require_rules": True, "require_channels": True},
        "weight": 20,
        "severity": "critical",
        "required": True,
        "enabled": True,
        "position": 30,
    },
    {
        "slug": "alert-route",
        "name": "Alert route configured",
        "description": "Service must have an active direct alert route or an active service match rule connected to a route.",
        "check_type": "route_exists",
        "configuration": {},
        "weight": 20,
        "severity": "critical",
        "required": True,
        "enabled": True,
        "position": 40,
    },
    {
        "slug": "runbook",
        "name": "Runbook configured",
        "description": "Service must have at least one active runbook.",
        "check_type": "runbook_exists",
        "configuration": {"minimum": 1},
        "weight": 15,
        "severity": "critical",
        "required": True,
        "enabled": True,
        "position": 50,
    },
    {
        "slug": "dependency-cycle",
        "name": "No dependency cycle",
        "description": "Service must not be part of an active dependency cycle.",
        "check_type": "dependency_cycle_absent",
        "configuration": {},
        "weight": 10,
        "severity": "critical",
        "required": True,
        "enabled": True,
        "position": 60,
    },
]


def ensure_basic_operational_standard(group, *, actor_user=None):
    database = ServiceStandard._meta.database

    with database.atomic():
        standard, standard_created = _get_or_create_standard(group, actor_user=actor_user)
        created_checks = []

        for check_data in BASIC_OPERATIONAL_CHECKS:
            check, created = _get_or_create_check(standard, check_data)

            if created:
                created_checks.append(check)

    return {
        "standard": standard,
        "standard_created": standard_created,
        "created_checks": created_checks,
    }


def _get_or_create_standard(group, *, actor_user=None):
    standard = ServiceStandard.get_or_none(
        ServiceStandard.group == group.id,
        ServiceStandard.slug == BASIC_OPERATIONAL_STANDARD["slug"],
        ServiceStandard.deleted == False,
    )

    if standard:
        return standard, False

    try:
        return ServiceStandard.create(
            group=group,
            slug=BASIC_OPERATIONAL_STANDARD["slug"],
            name=BASIC_OPERATIONAL_STANDARD["name"],
            description=BASIC_OPERATIONAL_STANDARD["description"],
            applies_to=BASIC_OPERATIONAL_STANDARD["applies_to"],
            enabled=BASIC_OPERATIONAL_STANDARD["enabled"],
            created_by=actor_user.id if actor_user else None,
            created_at=utc_now(),
            updated_at=utc_now(),
        ), True
    except IntegrityError:
        standard = ServiceStandard.get(
            ServiceStandard.group == group.id,
            ServiceStandard.slug == BASIC_OPERATIONAL_STANDARD["slug"],
            ServiceStandard.deleted == False,
        )

        return standard, False


def _get_or_create_check(standard, check_data):
    check = ServiceStandardCheck.get_or_none(
        ServiceStandardCheck.standard == standard.id,
        ServiceStandardCheck.slug == check_data["slug"],
        ServiceStandardCheck.deleted == False,
    )

    if check:
        return check, False

    try:
        return ServiceStandardCheck.create(
            standard=standard,
            slug=check_data["slug"],
            name=check_data["name"],
            description=check_data["description"],
            check_type=check_data["check_type"],
            configuration=check_data["configuration"],
            weight=check_data["weight"],
            severity=check_data["severity"],
            required=check_data["required"],
            enabled=check_data["enabled"],
            position=check_data["position"],
            created_at=utc_now(),
            updated_at=utc_now(),
        ), True
    except IntegrityError:
        check = ServiceStandardCheck.get(
            ServiceStandardCheck.standard == standard.id,
            ServiceStandardCheck.slug == check_data["slug"],
            ServiceStandardCheck.deleted == False,
        )

        return check, False
