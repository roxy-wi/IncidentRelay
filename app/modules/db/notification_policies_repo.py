
from peewee import fn

from app.db import database_proxy
from app.modules.db.models import (
    NotificationChannel,
    NotificationPolicy,
    NotificationPolicyRule,
    NotificationPolicyRuleChannel,
    Service,
    Team,
)
from app.modules.common import utc_now


def list_notification_policies(
    team_id=None,
    team_ids=None,
    enabled_only=False,
    include_deleted=False,
):
    """Return notification policies filtered by team visibility."""
    query = (
        NotificationPolicy
        .select(NotificationPolicy, Team)
        .join(Team)
    )

    if not include_deleted:
        query = query.where(
            NotificationPolicy.deleted == False
        )

    if enabled_only:
        query = query.where(
            NotificationPolicy.enabled == True
        )

    if team_id is not None:
        query = query.where(
            NotificationPolicy.team == team_id
        )

    elif team_ids is not None:
        team_ids = list(team_ids)

        if not team_ids:
            return []

        query = query.where(
            NotificationPolicy.team.in_(team_ids)
        )

    return list(
        query.order_by(
            Team.slug.asc(),
            NotificationPolicy.name.asc(),
            NotificationPolicy.id.asc(),
        )
    )


def get_notification_policy(
    policy_id,
    *,
    include_deleted=False,
):
    """Return notification policy by id."""
    query = NotificationPolicy.select().where(
        NotificationPolicy.id == policy_id
    )

    if not include_deleted:
        query = query.where(
            NotificationPolicy.deleted == False
        )

    return query.get()


def get_notification_policy_or_none(
    policy_id,
    *,
    include_deleted=False,
):
    """Return notification policy or None."""
    if not policy_id:
        return None

    query = NotificationPolicy.select().where(
        NotificationPolicy.id == policy_id
    )

    if not include_deleted:
        query = query.where(
            NotificationPolicy.deleted == False
        )

    return query.first()


def get_notification_policy_by_team_and_name(
    team_id,
    name,
    *,
    exclude_policy_id=None,
    include_deleted=True,
):
    """Return policy occupying the same team/name unique key."""
    query = NotificationPolicy.select().where(
        (NotificationPolicy.team == team_id)
        & (NotificationPolicy.name == name)
    )

    if exclude_policy_id is not None:
        query = query.where(
            NotificationPolicy.id != exclude_policy_id
        )

    if not include_deleted:
        query = query.where(
            NotificationPolicy.deleted == False
        )

    return query.first()


def create_notification_policy(
    *,
    team_id,
    name,
    description=None,
    enabled=True,
):
    """Create notification policy."""
    now = utc_now()

    return NotificationPolicy.create(
        team=team_id,
        name=name,
        description=description,
        enabled=enabled,
        created_at=now,
        updated_at=now,
    )


def restore_notification_policy(
    policy_id,
    *,
    name,
    description=None,
    enabled=True,
):
    """Restore and reconfigure a soft-deleted policy."""
    policy = get_notification_policy(
        policy_id,
        include_deleted=True,
    )

    policy.name = name
    policy.description = description
    policy.enabled = enabled
    policy.deleted = False
    policy.deleted_at = None
    policy.updated_at = utc_now()
    policy.save()

    return policy


def update_notification_policy(policy_id, data):
    """Update notification policy."""
    policy = get_notification_policy(policy_id)

    for field in (
        "name",
        "description",
        "enabled",
    ):
        if field in data:
            setattr(policy, field, data[field])

    policy.updated_at = utc_now()
    policy.save()

    return policy


def soft_delete_notification_policy(policy_id):
    """Soft-delete policy and its active rules."""
    policy = get_notification_policy(policy_id)
    now = utc_now()

    with database_proxy.atomic():
        (
            NotificationPolicyRule
            .update(
                enabled=False,
                deleted=True,
                updated_at=now,
            )
            .where(
                (NotificationPolicyRule.policy == policy.id)
                & (NotificationPolicyRule.deleted == False)
            )
            .execute()
        )

        policy.enabled = False
        policy.deleted = True
        policy.deleted_at = now
        policy.updated_at = now
        policy.save()

    return policy


def policy_belongs_to_team(policy_id, team_id):
    """Return True when policy belongs to team."""
    policy = get_notification_policy_or_none(policy_id)

    return bool(
        policy
        and policy.team_id == team_id
    )


def count_policy_services(policy_id):
    """Return number of active services using policy."""
    return (
        Service
        .select(Service.id)
        .where(
            (Service.notification_policy == policy_id)
            & (Service.deleted == False)
        )
        .count()
    )


def count_policy_rules(policy_id):
    """Return number of active rules in a policy."""
    return (
        NotificationPolicyRule
        .select(NotificationPolicyRule.id)
        .where(
            (NotificationPolicyRule.policy == policy_id)
            & (NotificationPolicyRule.deleted == False)
        )
        .count()
    )


def list_policy_rules(
    policy_id,
    *,
    enabled_only=False,
    include_deleted=False,
):
    """Return ordered rules for a notification policy."""
    query = NotificationPolicyRule.select().where(
        NotificationPolicyRule.policy == policy_id
    )

    if not include_deleted:
        query = query.where(
            NotificationPolicyRule.deleted == False
        )

    if enabled_only:
        query = query.where(
            NotificationPolicyRule.enabled == True
        )

    return list(
        query.order_by(
            NotificationPolicyRule.position.asc(),
            NotificationPolicyRule.id.asc(),
        )
    )


def get_policy_rule(
    rule_id,
    *,
    include_deleted=False,
):
    """Return notification policy rule by id."""
    query = NotificationPolicyRule.select().where(
        NotificationPolicyRule.id == rule_id
    )

    if not include_deleted:
        query = query.where(
            NotificationPolicyRule.deleted == False
        )

    return query.get()


def get_policy_rule_or_none(
    rule_id,
    *,
    include_deleted=False,
):
    """Return notification policy rule or None."""
    if not rule_id:
        return None

    query = NotificationPolicyRule.select().where(
        NotificationPolicyRule.id == rule_id
    )

    if not include_deleted:
        query = query.where(
            NotificationPolicyRule.deleted == False
        )

    return query.first()


def get_next_rule_position(policy_id):
    """Return next available position for policy."""
    max_position = (
        NotificationPolicyRule
        .select(
            fn.MAX(
                NotificationPolicyRule.position
            )
        )
        .where(
            (NotificationPolicyRule.policy == policy_id)
            & (NotificationPolicyRule.deleted == False)
        )
        .scalar()
    )

    return int(max_position or 0) + 1


def create_policy_rule(
    *,
    policy_id,
    name,
    description=None,
    position=None,
    event_types=None,
    matchers=None,
    matcher_preset_id=None,
    continue_matching=False,
    enabled=True,
):
    """Create notification policy rule."""
    now = utc_now()

    if position is None:
        position = get_next_rule_position(policy_id)

    return NotificationPolicyRule.create(
        policy=policy_id,
        name=name,
        description=description,
        position=position,
        event_types=event_types or [],
        matchers=matchers or {},
        matcher_preset=matcher_preset_id,
        continue_matching=continue_matching,
        enabled=enabled,
        created_at=now,
        updated_at=now,
    )


def update_policy_rule(rule_id, data):
    """Update notification policy rule."""
    rule = get_policy_rule(rule_id)

    for field in (
        "name",
        "description",
        "position",
        "event_types",
        "matchers",
        "matcher_preset",
        "continue_matching",
        "enabled",
    ):
        if field in data:
            setattr(rule, field, data[field])

    rule.updated_at = utc_now()
    rule.save()

    return rule


def soft_delete_policy_rule(rule_id):
    """Soft-delete notification policy rule."""
    rule = get_policy_rule(rule_id)
    now = utc_now()

    with database_proxy.atomic():
        (
            NotificationPolicyRuleChannel
            .delete()
            .where(NotificationPolicyRuleChannel.rule == rule.id)
            .execute()
        )

        rule.enabled = False
        rule.deleted = True
        rule.deleted_at = now
        rule.position = -abs(rule.id)
        rule.updated_at = now
        rule.save()

    return rule


def list_rule_channels(rule_id, *, enabled_only=False):
    """Return channels assigned to a rule."""
    query = (
        NotificationChannel
        .select(NotificationChannel)
        .join(
            NotificationPolicyRuleChannel,
            on=(NotificationPolicyRuleChannel.channel == NotificationChannel.id),
        ).where(NotificationPolicyRuleChannel.rule == rule_id)
    )

    query = query.where(NotificationChannel.deleted == False)

    if enabled_only:
        query = query.where(NotificationChannel.enabled == True)

    return list(
        query.order_by(
            NotificationChannel.name.asc(),
            NotificationChannel.id.asc(),
        )
    )


def list_rule_channel_ids(rule_id):
    """Return channel ids assigned to a rule."""
    return [
        channel.id
        for channel in list_rule_channels(rule_id)
    ]


def replace_rule_channels(rule_id, channel_ids):
    """Replace all channel links for a policy rule."""
    channel_ids = list(
        dict.fromkeys(
            int(channel_id)
            for channel_id in (channel_ids or [])
        )
    )

    with database_proxy.atomic():
        (
            NotificationPolicyRuleChannel
            .delete()
            .where(
                NotificationPolicyRuleChannel.rule
                == rule_id
            )
            .execute()
        )

        if channel_ids:
            (
                NotificationPolicyRuleChannel
                .insert_many(
                    [
                        {
                            "rule": rule_id,
                            "channel": channel_id,
                        }
                        for channel_id in channel_ids
                    ]
                )
                .execute()
            )

    return list_rule_channels(rule_id)


def reorder_policy_rules(policy_id, ordered_rule_ids):
    """Assign contiguous positions to policy rules.

    Two-phase updates preserve compatibility with databases where
    (policy_id, position) is still protected by a unique index.
    """
    ordered_rule_ids = [
        int(rule_id)
        for rule_id in ordered_rule_ids
    ]

    if not ordered_rule_ids:
        return []

    temporary_base = 1_000_000

    with database_proxy.atomic():
        for index, rule_id in enumerate(
            ordered_rule_ids,
            start=1,
        ):
            (
                NotificationPolicyRule
                .update(
                    position=temporary_base + index,
                    updated_at=utc_now(),
                )
                .where(
                    (NotificationPolicyRule.id == rule_id)
                    & (NotificationPolicyRule.policy == policy_id)
                    & (NotificationPolicyRule.deleted == False)
                )
                .execute()
            )

        for position, rule_id in enumerate(
            ordered_rule_ids,
            start=1,
        ):
            (
                NotificationPolicyRule
                .update(
                    position=position,
                    updated_at=utc_now(),
                )
                .where(
                    (NotificationPolicyRule.id == rule_id)
                    & (NotificationPolicyRule.policy == policy_id)
                    & (NotificationPolicyRule.deleted == False)
                )
                .execute()
            )

    return list_policy_rules(policy_id)
