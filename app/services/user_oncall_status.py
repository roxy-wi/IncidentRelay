from datetime import datetime, timedelta

from app.modules.db.models import (
    EscalationPolicy,
    EscalationPolicyRule,
    Group,
    Rotation,
    RotationLayer,
    RotationLayerMember,
    RotationOverride,
    Team,
    User,
)
from app.services.calendar_service import build_rotation_calendar
from app.modules.common import as_utc_naive, utc_now
from app.services.serializers.common import serialize_utc_datetime


DEFAULT_LOOKAHEAD_DAYS = 30


def _parse_event_datetime(value):
    return as_utc_naive(value)


def _display_name(name, slug, fallback="-"):
    return name or slug or fallback


def _event_sort_key(event):
    return (
        _parse_event_datetime(event["start"]),
        _parse_event_datetime(event["end"]),
        event.get("team_name") or "",
        event.get("rotation_name") or "",
    )


def _serialize_user_oncall_event(event):
    return {
        "rotation_id": event.get("rotation_id"),
        "rotation_name": event.get("rotation_name"),

        "team_id": event.get("team_id"),
        "team_name": event.get("team_name"),
        "team_slug": event.get("team_slug"),
        "team_display": _display_name(
            event.get("team_name"),
            event.get("team_slug"),
            "Team",
        ),

        "layer_id": event.get("layer_id"),
        "layer_name": event.get("layer_name"),
        "layer_priority": event.get("layer_priority"),

        "override_id": event.get("override_id"),
        "reason": event.get("reason"),

        "type": event.get("type"),
        "timezone": event.get("timezone") or "UTC",

        "start": serialize_utc_datetime(event["start"]),
        "end": serialize_utc_datetime(event["end"]),
    }


def _list_user_rotations(user, *, start_at=None, end_at=None):
    """
    Return enabled rotations where the user actually participates.

    A user can be on-call because they are:
    - a member of a rotation layer;
    - assigned through a rotation override.

    Team membership alone is not enough to determine on-call status.
    """
    rotation_ids = set()

    layer_member_rows = (
        RotationLayerMember
        .select(RotationLayerMember.layer)
        .where(
            (RotationLayerMember.user == user.id)
            & (RotationLayerMember.active == True)
        )
    )

    layer_ids = [
        item.layer_id
        for item in layer_member_rows
    ]

    if layer_ids:
        layer_rows = (
            RotationLayer
            .select(RotationLayer.rotation)
            .where(
                (RotationLayer.id.in_(layer_ids))
                & (RotationLayer.enabled == True)
                & (RotationLayer.deleted == False)
            )
        )

        rotation_ids.update(
            item.rotation_id
            for item in layer_rows
            if item.rotation_id
        )

    override_query = (
        RotationOverride
        .select(RotationOverride.rotation)
        .where(RotationOverride.user == user.id)
    )

    if start_at is not None and end_at is not None:
        override_query = override_query.where(
            (RotationOverride.starts_at < end_at)
            & (RotationOverride.ends_at > start_at)
        )

    rotation_ids.update(
        item.rotation_id
        for item in override_query
        if item.rotation_id
    )

    if not rotation_ids:
        return []

    return list(
        Rotation
        .select(Rotation)
        .join(Team, on=(Rotation.team == Team.id))
        .join(Group, on=(Team.group == Group.id))
        .where(
            (Rotation.id.in_(rotation_ids))
            & (Rotation.enabled == True)
            & (Rotation.deleted == False)
            & (Team.active == True)
            & (Team.deleted == False)
            & (Group.active == True)
            & (Group.deleted == False)
        )
        .order_by(Rotation.id.asc())
    )


def _serialize_datetime_utc(value):
    return serialize_utc_datetime(value)


def _policy_display_name(policy):
    return getattr(policy, "name", None) or f"Escalation policy #{policy.id}"


def _rule_target_type(rule):
    if getattr(rule, "target_type", None):
        return rule.target_type

    if getattr(rule, "target_rotation_id", None):
        return "rotation"

    if getattr(rule, "target_user_id", None):
        return "user"

    return "unknown"


def _list_enabled_escalation_rules_with_levels():
    """
    Return enabled escalation rules with calculated 1-based level.

    The level is calculated by policy order, not by raw position value,
    so it works whether stored positions are 0-based or 1-based.
    """
    query = (
        EscalationPolicyRule
        .select(EscalationPolicyRule, EscalationPolicy, Team, Group)
        .join(EscalationPolicy)
        .join(Team)
        .switch(Team)
        .join(Group)
        .where(
            (EscalationPolicyRule.enabled == True)
            & (EscalationPolicy.enabled == True)
            & (EscalationPolicy.deleted == False)
            & (Team.active == True)
            & (Team.deleted == False)
            & (Group.active == True)
            & (Group.deleted == False)
        )
        .order_by(
            EscalationPolicy.id.asc(),
            EscalationPolicyRule.position.asc(),
            EscalationPolicyRule.id.asc(),
        )
    )

    current_policy_id = None
    level = 0

    for rule in query:
        policy_id = rule.policy_id

        if policy_id != current_policy_id:
            current_policy_id = policy_id
            level = 0

        level += 1

        yield rule, level


def _serialize_escalation_base(rule, level):
    policy = rule.policy
    team = policy.team if policy else None

    return {
        "policy_id": policy.id if policy else None,
        "policy_name": _policy_display_name(policy) if policy else "-",

        "team_id": team.id if team else None,
        "team_name": team.name if team else None,
        "team_slug": team.slug if team else None,
        "team_display": _display_name(
            team.name if team else None,
            team.slug if team else None,
            "Team",
        ),

        "rule_id": rule.id,
        "level": level,
        "delay_seconds": rule.delay_seconds,
        "target_type": _rule_target_type(rule),
    }


def _serialize_direct_escalation_rule(rule, level):
    item = _serialize_escalation_base(rule, level)
    item.update({
        "kind": "direct_user",
        "rotation_id": None,
        "rotation_name": None,
        "start": None,
        "end": None,
        "timezone": "UTC",
    })
    return item


def _serialize_rotation_escalation_rule(rule, level, event):
    rotation = rule.target_rotation
    item = _serialize_escalation_base(rule, level)

    item.update({
        "kind": "rotation",
        "rotation_id": rotation.id if rotation else event.get("rotation_id"),
        "rotation_name": (
            rotation.name
            if rotation
            else event.get("rotation_name")
        ),
        "layer_id": event.get("layer_id"),
        "layer_name": event.get("layer_name"),
        "layer_priority": event.get("layer_priority"),
        "override_id": event.get("override_id"),
        "reason": event.get("reason"),
        "type": event.get("type"),
        "start": _serialize_datetime_utc(event["start"]),
        "end": _serialize_datetime_utc(event["end"]),
        "timezone": event.get("timezone") or getattr(rotation, "timezone", None) or "UTC",
    })

    return item


def _dedupe_escalation_items(items):
    result = []
    seen = set()

    for item in items:
        key = (
            item.get("policy_id"),
            item.get("rule_id"),
            item.get("kind"),
            item.get("rotation_id"),
            item.get("start"),
            item.get("end"),
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(item)

    return result


def _escalation_sort_key(item):
    return (
        item.get("team_display") or "",
        item.get("policy_name") or "",
        int(item.get("level") or 0),
        item.get("start") or "",
        item.get("rotation_name") or "",
    )


def _collect_user_escalation_status(user, now, lookahead_days):
    """
    Return current and upcoming second-level+ escalation participation.

    Level 1 is intentionally skipped here: this section is about escalation
    backup, not normal primary routing.
    """
    current = []
    upcoming = []

    start_at = now - timedelta(days=max(lookahead_days, 7))
    end_at = now + timedelta(days=lookahead_days)

    for rule, level in _list_enabled_escalation_rules_with_levels():
        if level < 2:
            continue

        target_type = _rule_target_type(rule)

        if target_type == "user":
            if int(rule.target_user_id or 0) != int(user.id):
                continue

            current.append(_serialize_direct_escalation_rule(rule, level))
            continue

        if target_type != "rotation":
            continue

        rotation = getattr(rule, "target_rotation", None)

        if not rotation:
            continue

        if not rotation.enabled or rotation.deleted:
            continue

        events = build_rotation_calendar(rotation, start_at, end_at)

        for event in events:
            if int(event.get("user_id") or 0) != int(user.id):
                continue

            event_start = _parse_event_datetime(event["start"])
            event_end = _parse_event_datetime(event["end"])

            item = _serialize_rotation_escalation_rule(rule, level, event)

            if event_start <= now < event_end:
                current.append(item)
                continue

            if event_start > now:
                upcoming.append(item)

    current = sorted(
        _dedupe_escalation_items(current),
        key=_escalation_sort_key,
    )

    upcoming = sorted(
        _dedupe_escalation_items(upcoming),
        key=_escalation_sort_key,
    )

    return current, upcoming[:5]


def get_user_oncall_status(
    user,
    *,
    now=None,
    lookahead_days=DEFAULT_LOOKAHEAD_DAYS,
):
    """
    Return current and next on-call slots for a user.

    This uses the same calendar calculation as the calendar UI and future
    shift email notifications, so UI and scheduler stay consistent.
    """
    now = now or utc_now()
    lookahead_days = max(1, min(int(lookahead_days or DEFAULT_LOOKAHEAD_DAYS), 90))

    lookbehind_days = max(lookahead_days, 7)

    start_at = now - timedelta(days=lookbehind_days)
    end_at = now + timedelta(days=lookahead_days)

    current = []
    upcoming = []

    for rotation in _list_user_rotations(
            user,
            start_at=start_at,
            end_at=end_at,
    ):
        events = build_rotation_calendar(rotation, start_at, end_at)

        for event in events:
            if int(event.get("user_id") or 0) != int(user.id):
                continue

            event_start = _parse_event_datetime(event["start"])
            event_end = _parse_event_datetime(event["end"])

            if event_start <= now < event_end:
                current.append(event)
                continue

            if event_start > now:
                upcoming.append(event)

    current = sorted(current, key=_event_sort_key)
    upcoming = sorted(upcoming, key=_event_sort_key)

    next_slots = upcoming[:5]

    escalation_current, escalation_next = _collect_user_escalation_status(
        user,
        now,
        lookahead_days,
    )

    status = "idle"

    if current:
        status = "primary"
    elif escalation_current:
        status = "escalation"

    return {
        "status": status,

        "is_oncall": bool(current),
        "is_escalation_backup": bool(escalation_current),

        "current": [
            _serialize_user_oncall_event(event)
            for event in current
        ],
        "next": [
            _serialize_user_oncall_event(event)
            for event in next_slots
        ],

        "escalation_current": escalation_current,
        "escalation_next": escalation_next,

        "lookahead_days": lookahead_days,
    }
