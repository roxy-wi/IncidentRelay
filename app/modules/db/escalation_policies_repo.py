
from peewee import IntegrityError

from app.modules.db.models import (
    Alert,
    AlertGroup,
    AlertRoute,
    EscalationPolicy,
    EscalationPolicyRule,
    IncidentResponder,
    Rotation,
    Service,
    Team,
    TeamUser,
    User,
)
from app.modules.common import utc_now


def list_policies(team_id=None, team_ids=None, enabled_only=False, include_deleted=False):
    """Return escalation policies."""
    query = EscalationPolicy.select().join(Team).switch(EscalationPolicy)

    if not include_deleted:
        query = query.where(EscalationPolicy.deleted == False)

    if team_id:
        query = query.where(EscalationPolicy.team == team_id)
    elif team_ids is not None:
        if not team_ids:
            return []
        query = query.where(EscalationPolicy.team.in_(team_ids))

    if enabled_only:
        query = query.where(EscalationPolicy.enabled == True)

    return list(query.order_by(EscalationPolicy.id.asc()))


def get_policy(policy_id, include_deleted=False):
    """Return an escalation policy by id."""
    query = EscalationPolicy.select().where(EscalationPolicy.id == policy_id)

    if not include_deleted:
        query = query.where(EscalationPolicy.deleted == False)

    return query.get()


def get_policy_or_none(policy_id, include_deleted=False):
    """Return an escalation policy or None."""
    if not policy_id:
        return None

    query = EscalationPolicy.select().where(EscalationPolicy.id == policy_id)

    if not include_deleted:
        query = query.where(EscalationPolicy.deleted == False)

    return query.first()


def create_policy(team_id, name, description=None, enabled=True, repeat_count=0):
    """Create or restore an escalation policy by team/name."""
    existing = EscalationPolicy.get_or_none(
        (EscalationPolicy.team == team_id)
        & (EscalationPolicy.name == name)
    )
    if existing is not None and existing.deleted:
        existing.description = description
        existing.enabled = enabled
        existing.repeat_count = repeat_count
        existing.deleted = False
        existing.deleted_at = None
        existing.updated_at = utc_now()
        existing.save()
        return existing

    return EscalationPolicy.create(
        team=team_id,
        name=name,
        description=description,
        enabled=enabled,
        repeat_count=repeat_count,
    )


def update_policy(policy_id, data):
    """Update an escalation policy."""
    policy = get_policy(policy_id)

    for field in ["name", "description", "enabled", "repeat_count"]:
        if field in data:
            setattr(policy, field, data[field])

    policy.updated_at = utc_now()
    policy.save()
    return policy


def soft_delete_policy(policy_id):
    """Soft-delete a policy and detach it from active configuration."""
    policy = get_policy(policy_id)
    now = utc_now()
    database = EscalationPolicy._meta.database

    with database.atomic():
        EscalationPolicyRule.update(
            enabled=False,
            updated_at=now,
        ).where(EscalationPolicyRule.policy == policy.id).execute()

        AlertRoute.update(escalation_policy=None).where(
            AlertRoute.escalation_policy == policy.id
        ).execute()
        Service.update(default_escalation_policy=None, updated_at=now).where(
            Service.default_escalation_policy == policy.id
        ).execute()
        Alert.update(
            escalation_policy=None,
            escalation_rule=None,
            next_escalation_at=None,
        ).where(
            (Alert.escalation_policy == policy.id)
            & (Alert.status != "resolved")
        ).execute()
        AlertGroup.update(
            escalation_policy=None,
            escalation_rule=None,
            next_escalation_at=None,
            updated_at=now,
        ).where(
            (AlertGroup.escalation_policy == policy.id)
            & (~AlertGroup.status.in_(("resolved", "merged")))
        ).execute()
        IncidentResponder.update(
            status="expired",
            response_message="Escalation policy was deleted",
            responded_at=now,
            updated_at=now,
        ).where(
            (IncidentResponder.target_escalation_policy == policy.id)
            & (IncidentResponder.status == "requested")
        ).execute()

        policy.enabled = False
        policy.deleted = True
        policy.deleted_at = now
        policy.updated_at = now
        policy.save()

    return policy


def list_rules(policy_id, enabled_only=False):
    """Return policy rules ordered by position."""
    query = EscalationPolicyRule.select().where(
        EscalationPolicyRule.policy == policy_id
    )

    if enabled_only:
        query = query.where(EscalationPolicyRule.enabled == True)

    return list(query.order_by(EscalationPolicyRule.position.asc(), EscalationPolicyRule.id.asc()))


def get_rule(rule_id):
    """Return a policy rule by id."""
    return EscalationPolicyRule.get_by_id(rule_id)


def get_first_rule(policy_id):
    """Return the first enabled rule for a policy."""
    return (
        EscalationPolicyRule.select()
        .where(
            (EscalationPolicyRule.policy == policy_id)
            & (EscalationPolicyRule.enabled == True)
        )
        .order_by(EscalationPolicyRule.position.asc(), EscalationPolicyRule.id.asc())
        .first()
    )


def get_next_rule(policy_id, current_position):
    """Return the next enabled rule after current position."""
    return (
        EscalationPolicyRule.select()
        .where(
            (EscalationPolicyRule.policy == policy_id)
            & (EscalationPolicyRule.enabled == True)
            & (EscalationPolicyRule.position > current_position)
        )
        .order_by(EscalationPolicyRule.position.asc(), EscalationPolicyRule.id.asc())
        .first()
    )


def create_rule(
    policy_id,
    position,
    delay_seconds,
    target_type,
    target_id,
    enabled=True,
):
    """Create an escalation policy rule."""
    get_policy(policy_id)

    data = {
        "policy": policy_id,
        "position": position,
        "delay_seconds": delay_seconds,
        "target_type": target_type,
        "enabled": enabled,
    }

    if target_type == "rotation":
        data["target_rotation"] = target_id
    elif target_type == "user":
        data["target_user"] = target_id
    else:
        raise ValueError("unsupported escalation rule target type")

    try:
        return EscalationPolicyRule.create(**data)
    except IntegrityError as exc:
        raise ValueError("rule position already exists in this policy") from exc


def update_rule(rule_id, data):
    """Update an escalation policy rule."""
    rule = get_rule(rule_id)

    for field in ["position", "delay_seconds", "enabled"]:
        if field in data:
            setattr(rule, field, data[field])

    target_type = data.get("target_type")
    target_id = data.get("target_id")

    if target_type is not None:
        rule.target_type = target_type
        rule.target_rotation = None
        rule.target_user = None

        if target_type == "rotation":
            rule.target_rotation = target_id
        elif target_type == "user":
            rule.target_user = target_id
        else:
            raise ValueError("unsupported escalation rule target type")
    elif target_id is not None:
        if rule.target_type == "rotation":
            rule.target_rotation = target_id
        elif rule.target_type == "user":
            rule.target_user = target_id

    rule.updated_at = utc_now()
    rule.save()
    return rule


def delete_rule(rule_id):
    """Delete an escalation policy rule."""
    rule = get_rule(rule_id)
    rule.delete_instance()
    return rule


def rotation_belongs_to_team(rotation_id, team_id):
    """Return true when rotation belongs to team."""
    return (
        Rotation.select()
        .where(
            (Rotation.id == rotation_id)
            & (Rotation.team == team_id)
            & (Rotation.deleted == False)
        )
        .exists()
    )


def user_belongs_to_team(user_id, team_id):
    """Return true when user is active member of team."""
    return (
        TeamUser.select()
        .join(User)
        .where(
            (TeamUser.team == team_id)
            & (TeamUser.user == user_id)
            & (TeamUser.active == True)
            & (User.active == True)
            & (User.deleted == False)
        )
        .exists()
    )
