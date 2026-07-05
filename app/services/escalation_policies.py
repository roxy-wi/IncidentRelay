import logging

from datetime import datetime, timedelta

from app.services.rbac import current_user
from app.services.serializers.common import attach_team_permissions
from app.modules.db import escalation_policies_repo
from app.modules.db import alerts_repo
from app.modules.db.models import EscalationPolicyRule
from app.services.oncall import get_current_oncall_user

logger = logging.getLogger("oncall.escalation_policies")


def list_enabled_rules(policy):
    """Return enabled policy rules ordered by position."""
    if not policy:
        return []

    return list(
        EscalationPolicyRule.select()
        .where(
            (EscalationPolicyRule.policy == policy)
            & (EscalationPolicyRule.enabled == True)  # noqa: E712
        )
        .order_by(EscalationPolicyRule.position.asc(), EscalationPolicyRule.id.asc())
    )


def get_first_enabled_rule(policy):
    """Return first enabled rule for a policy."""
    rules = list_enabled_rules(policy)

    return rules[0] if rules else None


def get_rule_delay_seconds(rule):
    """Return normalized rule delay in seconds."""
    if not rule:
        return 0

    return max(0, int(rule.delay_seconds or 0))


def get_next_escalation_at(rule, now):
    """Return next escalation timestamp for a rule."""
    if not rule:
        return None

    return now + timedelta(seconds=get_rule_delay_seconds(rule))


def resolve_rule_user(rule):
    """Resolve policy rule target to a user."""
    if not rule:
        return None

    if rule.target_type == "user":
        return rule.target_user

    if rule.target_type == "rotation" and rule.target_rotation:
        return get_current_oncall_user(rule.target_rotation)

    return None


def get_next_rule_for_alert(alert):
    """
    Return next policy rule and repeat counter for the alert.

    repeat_count means how many full extra cycles are allowed after the
    first pass through the rules.
    """
    policy = alert.escalation_policy

    if not policy or not policy.enabled:
        return None, alert.escalation_repeat_count or 0

    rules = list_enabled_rules(policy)

    if not rules:
        return None, alert.escalation_repeat_count or 0

    current_repeat = alert.escalation_repeat_count or 0
    current_rule_id = alert.escalation_rule_id

    if not current_rule_id:
        return rules[0], current_repeat

    for index, rule in enumerate(rules):
        if rule.id != current_rule_id:
            continue

        if index + 1 < len(rules):
            return rules[index + 1], current_repeat

        if current_repeat < (policy.repeat_count or 0):
            return rules[0], current_repeat + 1

        return None, current_repeat

    return rules[0], current_repeat


def serialize_policy(policy, include_rules=False, request_user=None):
    """Serialize escalation policy."""
    data = {
        "id": policy.id,
        "team_id": policy.team.id,
        "team_slug": policy.team.slug,
        "team_name": policy.team.name,
        "name": policy.name,
        "description": policy.description,
        "enabled": policy.enabled,
        "repeat_count": policy.repeat_count,
        "created_at": policy.created_at.isoformat() if policy.created_at else None,
        "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
        "group_id": policy.team.group.id if policy.team and policy.team.group else None,
        "group_slug": policy.team.group.slug if policy.team and policy.team.group else None,
    }

    if include_rules:
        data["rules"] = [serialize_rule(rule) for rule in escalation_policies_repo.list_rules(policy.id)]

    return attach_team_permissions(
        data,
        policy.team.id if policy.team else None,
        request_user or current_user(),
    )


def serialize_rule(rule):
    """Serialize escalation policy rule."""
    target_id = None
    target_name = None

    if rule.target_type == "rotation" and rule.target_rotation:
        target_id = rule.target_rotation.id
        target_name = rule.target_rotation.name
    elif rule.target_type == "user" and rule.target_user:
        target_id = rule.target_user.id
        target_name = rule.target_user.username

    return {
        "id": rule.id,
        "policy_id": rule.policy.id,
        "position": rule.position,
        "delay_seconds": rule.delay_seconds,
        "target_type": rule.target_type,
        "target_id": target_id,
        "target_name": target_name,
        "enabled": rule.enabled,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


def get_first_enabled_rule(policy):
    """Return the first enabled rule for a policy object."""
    if not policy or not policy.enabled:
        return None

    return escalation_policies_repo.get_first_rule(policy.id)


def resolve_rule_user(rule):
    """Resolve the user that should receive the rule notification."""
    if not rule or not rule.enabled:
        return None

    if rule.target_type == "user":
        return rule.target_user if rule.target_user and rule.target_user.active else None

    if rule.target_type == "rotation":
        return get_current_oncall_user(rule.target_rotation) if rule.target_rotation else None

    return None


def get_rule_delay_seconds(rule):
    """Return a safe delay for the rule."""
    if not rule:
        return 0

    return max(int(rule.delay_seconds or 0), 0)


def get_policy_reminder_interval(alert):
    """Return reminder interval for a policy-driven alert."""
    if not alert.escalation_policy:
        return 0

    if alert.escalation_rule:
        return max(get_rule_delay_seconds(alert.escalation_rule), 60)

    first_rule = get_first_enabled_rule(alert.escalation_policy)
    return max(get_rule_delay_seconds(first_rule), 60) if first_rule else 0


def _next_rule_for_alert(alert):
    policy = alert.escalation_policy

    if not policy or not policy.enabled:
        return None, False

    current_rule = alert.escalation_rule

    if not current_rule:
        return get_first_enabled_rule(policy), False

    next_rule = escalation_policies_repo.get_next_rule(policy.id, current_rule.position)

    if next_rule:
        return next_rule, False

    if alert.escalation_repeat_count < policy.repeat_count:
        return get_first_enabled_rule(policy), True

    return None, False


def maybe_escalate_policy_alert(alert, notify_alert_func):
    """Advance a firing alert to the next policy rule when it is due."""
    if not alert.escalation_policy:
        return False

    now = datetime.utcnow()

    if alert.next_escalation_at and alert.next_escalation_at > now:
        return False

    next_rule, repeated = _next_rule_for_alert(alert)

    if not next_rule:
        alert.next_escalation_at = None
        alert.save()
        return False

    target_user = resolve_rule_user(next_rule)

    if not target_user:
        logger.info(
            "policy escalation skipped because rule target is unavailable",
            extra={
                "extra": {
                    "alert_id": alert.id,
                    "policy_id": alert.escalation_policy.id,
                    "rule_id": next_rule.id,
                    "target_type": next_rule.target_type,
                }
            },
        )
        alert.escalation_rule = next_rule
        alert.next_escalation_at = now + timedelta(seconds=get_rule_delay_seconds(next_rule))
        alert.save()
        return False

    if next_rule.target_type == "rotation" and next_rule.target_rotation:
        alert.rotation = next_rule.target_rotation

    alert.assignee = target_user
    alert.escalation_rule = next_rule
    alert.escalation_level += 1
    alert.reminder_count = 0
    alert.last_escalated_at = now

    if repeated:
        alert.escalation_repeat_count += 1

    alert.next_escalation_at = now + timedelta(seconds=get_rule_delay_seconds(next_rule))
    alert.save()

    alerts_repo.create_alert_event(
        alert.id,
        "escalated",
        f"Escalated to {target_user.username} by policy rule {next_rule.position}",
    )

    notify_alert_func(alert, event_type="escalation")
    return True
