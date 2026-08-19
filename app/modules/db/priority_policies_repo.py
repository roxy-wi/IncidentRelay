
from peewee import fn

from app.db import database_proxy
from app.modules.db.models import (
    IncidentPriority,
    PriorityPolicy,
    PriorityPolicyRule,
    Service,
)
from app.modules.common import utc_now


def list_priority_policies(
    *,
    team_id=None,
    team_ids=None,
    enabled_only=False,
    include_deleted=False,
):
    """Return priority policies ordered by team and name."""
    query = PriorityPolicy.select()

    if not include_deleted:
        query = query.where(PriorityPolicy.deleted == False)

    if team_id is not None:
        query = query.where(PriorityPolicy.team == team_id)

    if team_ids is not None:
        team_ids = list(team_ids)

        if not team_ids:
            return []

        query = query.where(PriorityPolicy.team.in_(team_ids))

    if enabled_only:
        query = query.where(PriorityPolicy.enabled == True)

    return list(
        query.order_by(
            PriorityPolicy.default_for_team.desc(),
            PriorityPolicy.name.asc(),
            PriorityPolicy.id.asc(),
        )
    )


def get_priority_policy(policy_id, include_deleted=False):
    """Return one priority policy."""
    query = PriorityPolicy.select().where(PriorityPolicy.id == policy_id)

    if not include_deleted:
        query = query.where(PriorityPolicy.deleted == False)

    return query.get()


def get_priority_policy_or_none(policy_id, include_deleted=False):
    """Return one priority policy or None."""
    if not policy_id:
        return None

    query = PriorityPolicy.select().where(PriorityPolicy.id == policy_id)

    if not include_deleted:
        query = query.where(PriorityPolicy.deleted == False)

    return query.first()


def get_priority_policy_by_team_and_name(
    team_id,
    name,
    *,
    include_deleted=False,
    exclude_policy_id=None,
):
    """Return policy with a case-insensitive name inside one team."""
    query = PriorityPolicy.select().where(
        PriorityPolicy.team == team_id,
        fn.LOWER(PriorityPolicy.name) == name.lower(),
    )

    if not include_deleted:
        query = query.where(PriorityPolicy.deleted == False)

    if exclude_policy_id is not None:
        query = query.where(PriorityPolicy.id != exclude_policy_id)

    return query.first()


def get_default_priority_policy(team_id, *, enabled_only=True):
    """Return the default priority policy for a team."""
    query = PriorityPolicy.select().where(
        PriorityPolicy.team == team_id,
        PriorityPolicy.default_for_team == True,
        PriorityPolicy.deleted == False,
    )

    if enabled_only:
        query = query.where(PriorityPolicy.enabled == True)

    return query.order_by(PriorityPolicy.id.asc()).first()


def create_priority_policy(
    *,
    team_id,
    name,
    description=None,
    enabled=True,
    default_for_team=False,
    update_mode="raise_only",
    source_priority_mode="ignore",
    fallback_mode="severity_mapping",
    fallback_priority_id=None,
):
    """Create a priority policy."""
    return PriorityPolicy.create(
        team=team_id,
        name=name,
        description=description,
        enabled=enabled,
        default_for_team=default_for_team,
        update_mode=update_mode,
        source_priority_mode=source_priority_mode,
        fallback_mode=fallback_mode,
        fallback_priority=fallback_priority_id,
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def restore_priority_policy(
    policy_id,
    *,
    name,
    description=None,
    enabled=True,
    default_for_team=False,
    update_mode="raise_only",
    source_priority_mode="ignore",
    fallback_mode="severity_mapping",
    fallback_priority_id=None,
):
    """Restore a previously soft-deleted priority policy."""
    policy = get_priority_policy(policy_id, include_deleted=True)

    policy.name = name
    policy.description = description
    policy.enabled = enabled
    policy.default_for_team = default_for_team
    policy.update_mode = update_mode
    policy.source_priority_mode = source_priority_mode
    policy.fallback_mode = fallback_mode
    policy.fallback_priority = fallback_priority_id
    policy.deleted = False
    policy.deleted_at = None
    policy.updated_at = utc_now()
    policy.save()

    return policy


def update_priority_policy(policy_id, data):
    """Update a priority policy."""
    policy = get_priority_policy(policy_id)

    allowed_fields = {
        "name",
        "description",
        "enabled",
        "default_for_team",
        "update_mode",
        "source_priority_mode",
        "fallback_mode",
        "fallback_priority",
    }

    for field, value in data.items():
        if field in allowed_fields:
            setattr(policy, field, value)

    policy.updated_at = utc_now()
    policy.save()

    return policy


def clear_default_priority_policies(team_id, *, exclude_policy_id=None):
    """Clear the default flag from policies owned by a team."""
    query = PriorityPolicy.update(
        default_for_team=False,
        updated_at=utc_now(),
    ).where(
        PriorityPolicy.team == team_id,
        PriorityPolicy.default_for_team == True,
        PriorityPolicy.deleted == False,
    )

    if exclude_policy_id is not None:
        query = query.where(PriorityPolicy.id != exclude_policy_id)

    return query.execute()


def soft_delete_priority_policy(policy_id):
    """Soft-delete a policy and all of its rules."""
    policy = get_priority_policy(policy_id)
    now = utc_now()

    with database_proxy.atomic():
        rules = list_priority_policy_rules(policy.id)

        for rule in rules:
            rule.enabled = False
            rule.deleted = True
            rule.deleted_at = now
            rule.position = -abs(rule.id)
            rule.updated_at = now
            rule.save()

        policy.enabled = False
        policy.default_for_team = False
        policy.deleted = True
        policy.deleted_at = now
        policy.updated_at = now
        policy.save()

    return policy


def count_priority_policy_services(policy_id):
    """Return number of non-deleted services using a policy."""
    return (
        Service.select(Service.id)
        .where(
            Service.priority_policy == policy_id,
            Service.deleted == False,
        )
        .count()
    )


def count_priority_policy_rules(policy_id):
    """Return number of active rules in a policy."""
    return (
        PriorityPolicyRule.select(PriorityPolicyRule.id)
        .where(
            PriorityPolicyRule.policy == policy_id,
            PriorityPolicyRule.deleted == False,
        )
        .count()
    )


def get_incident_priority(priority_id, *, enabled_only=True):
    """Return an incident priority."""
    query = IncidentPriority.select().where(IncidentPriority.id == priority_id)

    if enabled_only:
        query = query.where(IncidentPriority.enabled == True)

    return query.get()


def get_incident_priority_or_none(priority_id, *, enabled_only=True):
    """Return an incident priority or None."""
    if not priority_id:
        return None

    query = IncidentPriority.select().where(IncidentPriority.id == priority_id)

    if enabled_only:
        query = query.where(IncidentPriority.enabled == True)

    return query.first()


def list_priority_policy_rules(policy_id, *, enabled_only=False):
    """Return active policy rules in evaluation order."""
    query = (
        PriorityPolicyRule.select(PriorityPolicyRule, IncidentPriority)
        .join(IncidentPriority)
        .where(
            PriorityPolicyRule.policy == policy_id,
            PriorityPolicyRule.deleted == False,
        )
    )

    if enabled_only:
        query = query.where(PriorityPolicyRule.enabled == True)

    return list(
        query.order_by(
            PriorityPolicyRule.position.asc(),
            PriorityPolicyRule.id.asc(),
        )
    )


def get_priority_policy_rule(rule_id):
    """Return one active priority policy rule."""
    return (
        PriorityPolicyRule.select(PriorityPolicyRule, IncidentPriority)
        .join(IncidentPriority)
        .where(
            PriorityPolicyRule.id == rule_id,
            PriorityPolicyRule.deleted == False,
        )
        .get()
    )


def get_priority_policy_rule_or_none(rule_id):
    """Return one active priority policy rule or None."""
    if not rule_id:
        return None

    return (
        PriorityPolicyRule.select(PriorityPolicyRule, IncidentPriority)
        .join(IncidentPriority)
        .where(
            PriorityPolicyRule.id == rule_id,
            PriorityPolicyRule.deleted == False,
        )
        .first()
    )


def get_next_priority_policy_rule_position(policy_id):
    """Return the next position for a policy rule."""
    maximum = (
        PriorityPolicyRule.select(fn.MAX(PriorityPolicyRule.position))
        .where(
            PriorityPolicyRule.policy == policy_id,
            PriorityPolicyRule.deleted == False,
        )
        .scalar()
    )

    return int(maximum or 0) + 1


def create_priority_policy_rule(
    *,
    policy_id,
    name,
    priority_id,
    description=None,
    position=None,
    matchers=None,
    matcher_preset_id=None,
    enabled=True,
):
    """Create a priority policy rule."""
    if position is None:
        position = get_next_priority_policy_rule_position(policy_id)

    return PriorityPolicyRule.create(
        policy=policy_id,
        name=name,
        description=description,
        position=position,
        matchers=matchers or {},
        matcher_preset=matcher_preset_id,
        priority=priority_id,
        enabled=enabled,
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def update_priority_policy_rule(rule_id, data):
    """Update a priority policy rule."""
    rule = get_priority_policy_rule(rule_id)

    allowed_fields = {
        "name",
        "description",
        "position",
        "matchers",
        "matcher_preset",
        "priority",
        "enabled",
    }

    for field, value in data.items():
        if field in allowed_fields:
            setattr(rule, field, value)

    rule.updated_at = utc_now()
    rule.save()

    return rule


def soft_delete_priority_policy_rule(rule_id):
    """Soft-delete one priority policy rule."""
    rule = get_priority_policy_rule(rule_id)
    now = utc_now()

    rule.enabled = False
    rule.deleted = True
    rule.deleted_at = now
    rule.position = -abs(rule.id)
    rule.updated_at = now
    rule.save()

    return rule


def reorder_priority_policy_rules(policy_id, ordered_rule_ids):
    """Assign contiguous positions to policy rules."""
    ordered_rule_ids = [int(rule_id) for rule_id in ordered_rule_ids]

    if not ordered_rule_ids:
        return []

    temporary_position = 1_000_000

    with database_proxy.atomic():
        for index, rule_id in enumerate(ordered_rule_ids, start=1):
            (
                PriorityPolicyRule.update(
                    position=temporary_position + index,
                    updated_at=utc_now(),
                )
                .where(
                    PriorityPolicyRule.id == rule_id,
                    PriorityPolicyRule.policy == policy_id,
                    PriorityPolicyRule.deleted == False,
                )
                .execute()
            )

        for position, rule_id in enumerate(ordered_rule_ids, start=1):
            (
                PriorityPolicyRule.update(
                    position=position,
                    updated_at=utc_now(),
                )
                .where(
                    PriorityPolicyRule.id == rule_id,
                    PriorityPolicyRule.policy == policy_id,
                    PriorityPolicyRule.deleted == False,
                )
                .execute()
            )

    return list_priority_policy_rules(policy_id)
