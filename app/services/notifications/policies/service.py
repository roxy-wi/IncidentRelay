from peewee import DoesNotExist

from app.db import database_proxy
from app.modules.db import (
    channels_repo,
    notification_policies_repo,
    teams_repo,
)
from app.services.serializers.common import attach_team_permissions
from app.services.routing.matcher import service as matcher_preset_service


class NotificationPolicyError(ValueError):
    """Base notification policy domain error."""


class NotificationPolicyNotFoundError(NotificationPolicyError):
    """Requested policy resource was not found."""


class NotificationPolicyConflictError(NotificationPolicyError):
    """Policy configuration conflicts with another resource."""


class NotificationPolicyInUseError(NotificationPolicyConflictError):
    """Policy cannot be deleted because services use it."""


def _payload_dict(payload):
    """Convert Pydantic schema or mapping to a mutable dict."""
    if hasattr(payload, "model_dump"):
        return payload.model_dump(exclude_unset=True)

    return dict(payload or {})


def _clean_name(value):
    """Normalize and validate a resource name."""
    name = str(value or "").strip()

    if not name:
        raise NotificationPolicyError(
            "notification policy name is required"
        )

    return name


def _require_team(team_id):
    """Return active, non-deleted team."""
    try:
        team = teams_repo.get_team(int(team_id))
    except (DoesNotExist, TypeError, ValueError) as exc:
        raise NotificationPolicyNotFoundError(
            "team was not found"
        ) from exc

    if not team.active:
        raise NotificationPolicyError(
            "notification policy team is inactive"
        )

    group = getattr(team, "group", None)

    if group and (
        not group.active
        or group.deleted
    ):
        raise NotificationPolicyError(
            "notification policy group is inactive"
        )

    return team


def get_policy(policy_id):
    """Return active notification policy."""
    try:
        return (
            notification_policies_repo
            .get_notification_policy(policy_id)
        )
    except DoesNotExist as exc:
        raise NotificationPolicyNotFoundError(
            "notification policy was not found"
        ) from exc


def get_rule(rule_id):
    """Return active notification policy rule."""
    try:
        return notification_policies_repo.get_policy_rule(rule_id)
    except DoesNotExist as exc:
        raise NotificationPolicyNotFoundError(
            "notification policy rule was not found"
        ) from exc


def _validate_channel_ids(team_id, channel_ids):
    """Validate that channels exist and belong to policy team."""
    normalized_ids = []

    for raw_channel_id in channel_ids or []:
        try:
            channel_id = int(raw_channel_id)
        except (TypeError, ValueError) as exc:
            raise NotificationPolicyError(
                "notification policy channel id is invalid"
            ) from exc

        if channel_id < 1:
            raise NotificationPolicyError("notification policy channel id must be greater than 0")

        if channel_id in normalized_ids:
            continue

        try:
            channel = channels_repo.get_channel(channel_id)
        except DoesNotExist as exc:
            raise NotificationPolicyNotFoundError(
                f"notification channel {channel_id} was not found"
            ) from exc

        if channel.team_id != team_id:
            raise NotificationPolicyError(
                f"notification channel {channel_id} "
                "belongs to another team"
            )

        normalized_ids.append(channel_id)

    return normalized_ids


def _validate_rule_delivery(enabled, channel_ids):
    """Validate final delivery configuration of one rule."""
    if enabled and not channel_ids:
        raise NotificationPolicyError("enabled notification policy rule requires at least one channel")


def serialize_channel(channel):
    """Serialize notification channel reference."""
    return {
        "id": channel.id,
        "team_id": channel.team_id,
        "name": channel.name,
        "channel_type": channel.channel_type,
        "enabled": channel.enabled,
    }


def serialize_rule(rule):
    """Serialize notification policy rule."""
    channels = notification_policies_repo.list_rule_channels(rule.id)
    preset = rule.matcher_preset if rule.matcher_preset_id else None

    return {
        "id": rule.id,
        "policy_id": rule.policy_id,
        "name": rule.name,
        "description": rule.description,
        "position": rule.position,
        "event_types": rule.event_types or [],
        "matchers": rule.matchers or {},
        "matcher_preset": (
            {
                "id": preset.id,
                "name": preset.name,
                "version": preset.version,
                "enabled": preset.enabled,
            }
            if preset
            else None
        ),
        "continue_matching": rule.continue_matching,
        "enabled": rule.enabled,
        "channel_ids": [
            channel.id
            for channel in channels
        ],
        "channels": [
            serialize_channel(channel)
            for channel in channels
        ],
        "created_at": (
            rule.created_at.isoformat()
            if rule.created_at
            else None
        ),
        "updated_at": (
            rule.updated_at.isoformat()
            if rule.updated_at
            else None
        ),
    }


def serialize_policy(policy, current_user=None, *, include_rules=False):
    """Serialize notification policy."""
    data = {
        "id": policy.id,
        "team_id": policy.team_id,
        "team_name": policy.team.name if policy.team else None,
        "team_slug": policy.team.slug if policy.team else None,
        "name": policy.name,
        "description": policy.description,
        "enabled": policy.enabled,
        "rules_count": notification_policies_repo.count_policy_rules(policy.id),
        "services_count": notification_policies_repo.count_policy_services(
            policy.id
        ),
        "created_at": (
            policy.created_at.isoformat() if policy.created_at else None
        ),
        "updated_at": (
            policy.updated_at.isoformat() if policy.updated_at else None
        ),
    }

    if include_rules:
        data["rules"] = [
            serialize_rule(rule)
            for rule in notification_policies_repo.list_policy_rules(policy.id)
        ]

    return attach_team_permissions(data, policy.team_id, current_user)


def list_policies(
    *,
    team_id=None,
    team_ids=None,
    enabled_only=False,
    current_user=None,
):
    """Return serialized notification policies."""
    policies = notification_policies_repo.list_notification_policies(
        team_id=team_id,
        team_ids=team_ids,
        enabled_only=enabled_only,
    )

    return [
        serialize_policy(policy, current_user)
        for policy in policies
    ]


def create_policy(payload):
    """Create or restore a notification policy."""
    data = _payload_dict(payload)
    team = _require_team(data.get("team_id"))
    name = _clean_name(data.get("name"))
    existing = (
        notification_policies_repo
        .get_notification_policy_by_team_and_name(
            team.id,
            name,
            include_deleted=True,
        )
    )

    if existing and not existing.deleted:
        raise NotificationPolicyConflictError(
            "notification policy with this name "
            "already exists in this team"
        )

    with database_proxy.atomic():
        if existing and existing.deleted:
            return (
                notification_policies_repo
                .restore_notification_policy(
                    existing.id,
                    name=name,
                    description=data.get("description"),
                    enabled=data.get("enabled", True),
                )
            )

        return (
            notification_policies_repo
            .create_notification_policy(
                team_id=team.id,
                name=name,
                description=data.get("description"),
                enabled=data.get("enabled", True),
            )
        )


def update_policy(policy_id, payload):
    """Update notification policy."""
    policy = get_policy(policy_id)
    data = _payload_dict(payload)

    if "name" in data:
        name = _clean_name(data["name"])

        existing = (
            notification_policies_repo
            .get_notification_policy_by_team_and_name(
                policy.team_id,
                name,
                exclude_policy_id=policy.id,
                include_deleted=True,
            )
        )

        if existing:
            raise NotificationPolicyConflictError("notification policy with this name already exists in this team")

        data["name"] = name

    return notification_policies_repo.update_notification_policy(policy.id, data)


def delete_policy(policy_id):
    """Delete policy when no active Service uses it."""
    policy = get_policy(policy_id)

    services_count = (
        notification_policies_repo
        .count_policy_services(policy.id)
    )

    if services_count:
        raise NotificationPolicyInUseError(
            "notification policy is assigned to "
            f"{services_count} service(s)"
        )

    return (
        notification_policies_repo
        .soft_delete_notification_policy(policy.id)
    )


def validate_policy_assignment(
    policy_id,
    *,
    team_id,
    enabled_only=True,
):
    """Validate policy before assigning it to a Service."""
    if policy_id is None:
        return None

    policy = get_policy(policy_id)

    if policy.team_id != team_id:
        raise NotificationPolicyError(
            "notification policy belongs to another team"
        )

    if enabled_only and not policy.enabled:
        raise NotificationPolicyError(
            "notification policy is disabled"
        )

    return policy


def create_rule(policy_id, payload):
    """Create rule and its channel links atomically."""
    policy = get_policy(policy_id)
    data = _payload_dict(payload)

    preset = matcher_preset_service.validate_preset_assignment(
        data.get("matcher_preset_id"),
        team_id=policy.team_id,
    )

    channel_ids = _validate_channel_ids(
        policy.team_id,
        data.get("channel_ids", []),
    )

    enabled = data.get("enabled", True)

    _validate_rule_delivery(enabled, channel_ids)
    existing_rules = notification_policies_repo.list_policy_rules(policy.id)
    requested_position = data.get("position")

    if requested_position is None:
        target_position = len(existing_rules) + 1
    else:
        target_position = max(
            1,
            min(
                int(requested_position),
                len(existing_rules) + 1,
            ),
        )

    with database_proxy.atomic():
        rule = (
            notification_policies_repo
            .create_policy_rule(
                policy_id=policy.id,
                name=_clean_name(data.get("name")),
                description=data.get("description"),
                position=len(existing_rules) + 1,
                event_types=data.get("event_types") or [],
                matchers=data.get("matchers") or {},
                matcher_preset_id=preset.id if preset else None,
                continue_matching=data.get(
                    "continue_matching",
                    False,
                ),
                enabled=enabled,
            )
        )

        notification_policies_repo.replace_rule_channels(rule.id, channel_ids)

        ordered_rule_ids = [
            existing_rule.id
            for existing_rule in existing_rules
        ]

        ordered_rule_ids.insert(target_position - 1, rule.id)

        notification_policies_repo.reorder_policy_rules(policy.id, ordered_rule_ids)

    return get_rule(rule.id)


def update_rule(rule_id, payload):
    """Update rule, channel links and position atomically."""
    rule = get_rule(rule_id)
    policy = get_policy(rule.policy_id)
    data = _payload_dict(payload)

    current_channel_ids = notification_policies_repo.list_rule_channel_ids(rule.id)

    if "channel_ids" in data:
        final_channel_ids = _validate_channel_ids(policy.team_id, data["channel_ids"])
    else:
        final_channel_ids = current_channel_ids

    final_enabled = data.get("enabled", rule.enabled)

    _validate_rule_delivery(final_enabled, final_channel_ids)

    if "name" in data:
        data["name"] = _clean_name(data["name"])

    requested_position = data.pop("position", None)
    data.pop("channel_ids", None)

    if "matcher_preset_id" in data:
        preset = matcher_preset_service.validate_preset_assignment(data.pop("matcher_preset_id"), team_id=policy.team_id)
        data["matcher_preset"] = preset.id if preset else None

    with database_proxy.atomic():
        updated_rule = notification_policies_repo.update_policy_rule(rule.id, data)

        if final_channel_ids != current_channel_ids:
            notification_policies_repo.replace_rule_channels(rule.id, final_channel_ids)

        if requested_position is not None:
            rules = notification_policies_repo.list_policy_rules(policy.id)

            ordered_rule_ids = [
                existing_rule.id
                for existing_rule in rules
                if existing_rule.id != rule.id
            ]

            target_position = max(
                1,
                min(
                    int(requested_position),
                    len(ordered_rule_ids) + 1,
                ),
            )

            ordered_rule_ids.insert(target_position - 1, rule.id)
            notification_policies_repo.reorder_policy_rules(policy.id, ordered_rule_ids)

    return get_rule(updated_rule.id)


def delete_rule(rule_id):
    """Delete rule and normalize remaining positions."""
    rule = get_rule(rule_id)
    policy_id = rule.policy_id

    with database_proxy.atomic():
        deleted_rule = notification_policies_repo.soft_delete_policy_rule(rule.id)
        remaining_rule_ids = [
            remaining_rule.id
            for remaining_rule in (
                notification_policies_repo
                .list_policy_rules(policy_id)
            )
        ]

        notification_policies_repo.reorder_policy_rules(policy_id, remaining_rule_ids)

    return deleted_rule


def reorder_rules(policy_id, rule_ids):
    """Apply explicit rule order."""
    policy = get_policy(policy_id)

    normalized_ids = []

    for raw_rule_id in rule_ids or []:
        rule_id = int(raw_rule_id)

        if rule_id in normalized_ids:
            raise NotificationPolicyError(
                "notification policy rule order "
                "contains duplicate ids"
            )

        normalized_ids.append(rule_id)

    existing_ids = [
        rule.id
        for rule in (
            notification_policies_repo
            .list_policy_rules(policy.id)
        )
    ]

    if set(normalized_ids) != set(existing_ids):
        raise NotificationPolicyError("notification policy rule order must contain every active rule exactly once")

    return notification_policies_repo.reorder_policy_rules(policy.id, normalized_ids)
