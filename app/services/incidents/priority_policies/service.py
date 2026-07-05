from peewee import DoesNotExist

from app.db import database_proxy
from app.modules.db import priority_policies_repo, teams_repo
from app.services.incidents.priority_policies.constants import FALLBACK_FIXED_PRIORITY, FALLBACK_SEVERITY_MAPPING
from app.services.routing.matcher import service as matcher_preset_service
from app.services.serializers.common import attach_team_permissions


class PriorityPolicyError(ValueError):
    """Base priority policy domain error."""


class PriorityPolicyNotFoundError(PriorityPolicyError):
    """Requested priority policy resource was not found."""


class PriorityPolicyConflictError(PriorityPolicyError):
    """Priority policy conflicts with another resource."""


class PriorityPolicyInUseError(PriorityPolicyConflictError):
    """Priority policy is still assigned to a service."""


def _payload_dict(payload):
    if hasattr(payload, "model_dump"):
        return payload.model_dump(exclude_unset=True)

    return dict(payload or {})


def _clean_name(value):
    name = str(value or "").strip()

    if not name:
        raise PriorityPolicyError("priority policy name is required")

    return name


def _require_team(team_id):
    try:
        team = teams_repo.get_team(int(team_id))
    except (DoesNotExist, TypeError, ValueError) as exc:
        raise PriorityPolicyNotFoundError("team was not found") from exc

    if not team.active:
        raise PriorityPolicyError("priority policy team is inactive")

    if team.group and (not team.group.active or team.group.deleted):
        raise PriorityPolicyError("priority policy group is inactive")

    return team


def _require_priority(priority_id):
    try:
        return priority_policies_repo.get_incident_priority(priority_id)
    except (DoesNotExist, TypeError, ValueError) as exc:
        raise PriorityPolicyNotFoundError(
            "incident priority was not found or is disabled"
        ) from exc


def _validate_matcher_preset_assignment(preset_id, team_id):
    try:
        return matcher_preset_service.validate_preset_assignment(preset_id, team_id=team_id)
    except matcher_preset_service.MatcherPresetNotFoundError as exc:
        raise PriorityPolicyNotFoundError(str(exc)) from exc
    except matcher_preset_service.MatcherPresetError as exc:
        raise PriorityPolicyError(str(exc)) from exc


def get_policy(policy_id):
    try:
        return priority_policies_repo.get_priority_policy(policy_id)
    except DoesNotExist as exc:
        raise PriorityPolicyNotFoundError(
            "priority policy was not found"
        ) from exc


def get_rule(rule_id):
    try:
        return priority_policies_repo.get_priority_policy_rule(rule_id)
    except DoesNotExist as exc:
        raise PriorityPolicyNotFoundError(
            "priority policy rule was not found"
        ) from exc


def _validate_policy_state(enabled, default_for_team):
    if default_for_team and not enabled:
        raise PriorityPolicyError(
            "default priority policy must be enabled"
        )


def _resolve_fallback_priority(fallback_mode, fallback_priority_id):
    if fallback_mode == FALLBACK_SEVERITY_MAPPING:
        return None

    if fallback_mode != FALLBACK_FIXED_PRIORITY:
        raise PriorityPolicyError(
            "unsupported priority policy fallback mode"
        )

    if not fallback_priority_id:
        raise PriorityPolicyError(
            "fixed priority fallback requires fallback_priority_id"
        )

    return _require_priority(fallback_priority_id)


def create_policy(payload):
    """Create or restore a priority policy."""
    data = _payload_dict(payload)
    team = _require_team(data.get("team_id"))
    name = _clean_name(data.get("name"))

    enabled = data.get("enabled", True)
    default_for_team = data.get("default_for_team", False)
    fallback_mode = data.get("fallback_mode", FALLBACK_SEVERITY_MAPPING)

    _validate_policy_state(enabled, default_for_team)

    fallback_priority = _resolve_fallback_priority(
        fallback_mode,
        data.get("fallback_priority_id"),
    )

    existing = priority_policies_repo.get_priority_policy_by_team_and_name(
        team.id,
        name,
        include_deleted=True,
    )

    if existing and not existing.deleted:
        raise PriorityPolicyConflictError(
            "priority policy with this name already exists in this team"
        )

    with database_proxy.atomic():
        if default_for_team:
            priority_policies_repo.clear_default_priority_policies(team.id)

        if existing:
            return priority_policies_repo.restore_priority_policy(
                existing.id,
                name=name,
                description=data.get("description"),
                enabled=enabled,
                default_for_team=default_for_team,
                update_mode=data.get("update_mode", "raise_only"),
                source_priority_mode=data.get(
                    "source_priority_mode",
                    "ignore",
                ),
                fallback_mode=fallback_mode,
                fallback_priority_id=(
                    fallback_priority.id if fallback_priority else None
                ),
            )

        return priority_policies_repo.create_priority_policy(
            team_id=team.id,
            name=name,
            description=data.get("description"),
            enabled=enabled,
            default_for_team=default_for_team,
            update_mode=data.get("update_mode", "raise_only"),
            source_priority_mode=data.get("source_priority_mode", "ignore"),
            fallback_mode=fallback_mode,
            fallback_priority_id=(
                fallback_priority.id if fallback_priority else None
            ),
        )


def update_policy(policy_id, payload):
    """Update a priority policy."""
    policy = get_policy(policy_id)
    data = _payload_dict(payload)

    if "name" in data:
        name = _clean_name(data["name"])

        existing = priority_policies_repo.get_priority_policy_by_team_and_name(
            policy.team_id,
            name,
            include_deleted=True,
            exclude_policy_id=policy.id,
        )

        if existing:
            raise PriorityPolicyConflictError(
                "priority policy with this name already exists in this team"
            )

        data["name"] = name

    final_enabled = data.get("enabled", policy.enabled)
    final_default = data.get(
        "default_for_team",
        policy.default_for_team,
    )

    if not final_enabled:
        if data.get("default_for_team") is True:
            raise PriorityPolicyError(
                "disabled priority policy cannot be the team default"
            )

        final_default = False
        data["default_for_team"] = False

    _validate_policy_state(final_enabled, final_default)

    final_fallback_mode = data.get(
        "fallback_mode",
        policy.fallback_mode,
    )

    if "fallback_priority_id" in data:
        final_fallback_priority_id = data["fallback_priority_id"]
    else:
        final_fallback_priority_id = policy.fallback_priority_id

    fallback_priority = _resolve_fallback_priority(
        final_fallback_mode,
        final_fallback_priority_id,
    )

    data.pop("fallback_priority_id", None)
    data["fallback_priority"] = (
        fallback_priority.id if fallback_priority else None
    )

    with database_proxy.atomic():
        if final_default:
            priority_policies_repo.clear_default_priority_policies(
                policy.team_id,
                exclude_policy_id=policy.id,
            )

        return priority_policies_repo.update_priority_policy(
            policy.id,
            data,
        )


def delete_policy(policy_id):
    """Delete a policy when no service uses it."""
    policy = get_policy(policy_id)
    services_count = (
        priority_policies_repo.count_priority_policy_services(policy.id)
    )

    if services_count:
        raise PriorityPolicyInUseError(
            "priority policy is assigned to "
            f"{services_count} service(s)"
        )

    return priority_policies_repo.soft_delete_priority_policy(policy.id)


def validate_policy_assignment(
    policy_id,
    *,
    team_id,
    enabled_only=True,
):
    """Validate a policy before assigning it to a service."""
    if policy_id is None:
        return None

    policy = get_policy(policy_id)

    if policy.team_id != team_id:
        raise PriorityPolicyError(
            "priority policy belongs to another team"
        )

    if enabled_only and not policy.enabled:
        raise PriorityPolicyError("priority policy is disabled")

    return policy


def get_effective_policy(*, team_id, service=None):
    """Return Service policy override or the team's default policy."""
    if service and getattr(service, "priority_policy_id", None):
        policy = priority_policies_repo.get_priority_policy_or_none(
            service.priority_policy_id
        )

        if policy and policy.enabled and policy.team_id == team_id:
            return policy

    return priority_policies_repo.get_default_priority_policy(team_id)


def create_rule(policy_id, payload):
    """Create one ordered priority policy rule."""
    policy = get_policy(policy_id)
    data = _payload_dict(payload)
    priority = _require_priority(data.get("priority_id"))
    preset = _validate_matcher_preset_assignment(data.get("matcher_preset_id"), policy.team_id)

    rules = priority_policies_repo.list_priority_policy_rules(policy.id)
    requested_position = data.get("position")

    if requested_position is None:
        target_position = len(rules) + 1
    else:
        target_position = max(
            1,
            min(int(requested_position), len(rules) + 1),
        )

    with database_proxy.atomic():
        rule = priority_policies_repo.create_priority_policy_rule(
            policy_id=policy.id,
            name=_clean_name(data.get("name")),
            description=data.get("description"),
            position=len(rules) + 1,
            matchers=data.get("matchers") or {},
            matcher_preset_id=preset.id if preset else None,
            priority_id=priority.id,
            enabled=data.get("enabled", True),
        )

        ordered_ids = [existing.id for existing in rules]
        ordered_ids.insert(target_position - 1, rule.id)

        priority_policies_repo.reorder_priority_policy_rules(policy.id, ordered_ids)

    return get_rule(rule.id)


def update_rule(rule_id, payload):
    """Update a priority policy rule."""
    rule = get_rule(rule_id)
    data = _payload_dict(payload)

    if "matcher_preset_id" in data:
        preset = _validate_matcher_preset_assignment(data.pop("matcher_preset_id"), rule.policy.team_id)
        data["matcher_preset"] = preset.id if preset else None

    if "name" in data:
        data["name"] = _clean_name(data["name"])

    if "priority_id" in data:
        priority = _require_priority(data.pop("priority_id"))
        data["priority"] = priority.id

    requested_position = data.pop("position", None)

    with database_proxy.atomic():
        updated_rule = priority_policies_repo.update_priority_policy_rule(rule.id, data)

        if requested_position is not None:
            rules = priority_policies_repo.list_priority_policy_rules(rule.policy_id)

            ordered_ids = [
                existing.id
                for existing in rules
                if existing.id != rule.id
            ]

            target_position = max(1, min(int(requested_position), len(ordered_ids) + 1))

            ordered_ids.insert(target_position - 1, rule.id)

            priority_policies_repo.reorder_priority_policy_rules(rule.policy_id, ordered_ids)

    return get_rule(updated_rule.id)


def delete_rule(rule_id):
    """Delete a rule and normalize remaining positions."""
    rule = get_rule(rule_id)
    policy_id = rule.policy_id

    with database_proxy.atomic():
        deleted_rule = (
            priority_policies_repo.soft_delete_priority_policy_rule(rule.id)
        )

        remaining_ids = [
            remaining.id
            for remaining in (
                priority_policies_repo.list_priority_policy_rules(policy_id)
            )
        ]

        priority_policies_repo.reorder_priority_policy_rules(
            policy_id,
            remaining_ids,
        )

    return deleted_rule


def reorder_rules(policy_id, rule_ids):
    """Replace the complete rule order."""
    policy = get_policy(policy_id)
    normalized_ids = []

    for raw_rule_id in rule_ids or []:
        rule_id = int(raw_rule_id)

        if rule_id in normalized_ids:
            raise PriorityPolicyError(
                "priority policy rule order contains duplicate ids"
            )

        normalized_ids.append(rule_id)

    existing_ids = [
        rule.id
        for rule in priority_policies_repo.list_priority_policy_rules(
            policy.id
        )
    ]

    if set(normalized_ids) != set(existing_ids):
        raise PriorityPolicyError(
            "priority policy rule order must contain "
            "every active rule exactly once"
        )

    return priority_policies_repo.reorder_priority_policy_rules(
        policy.id,
        normalized_ids,
    )


def serialize_rule(rule):
    """Serialize a priority policy rule."""
    preset = rule.matcher_preset if rule.matcher_preset_id else None
    priority = rule.priority if rule.priority_id else None

    return {
        "id": rule.id,
        "policy_id": rule.policy_id,
        "name": rule.name,
        "description": rule.description,
        "position": rule.position,
        "matchers": rule.matchers or {},
        "matcher_preset_id": preset.id if preset else None,
        "matcher_preset": {
            "id": preset.id,
            "name": preset.name,
            "version": preset.version,
            "enabled": preset.enabled,
        } if preset else None,
        "priority_id": priority.id if priority else None,
        "priority": {
            "id": priority.id,
            "slug": priority.slug,
            "name": priority.name,
            "level": priority.level,
            "enabled": priority.enabled,
        } if priority else None,
        "enabled": rule.enabled,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


def serialize_policy(policy, current_user=None, *, include_rules=False):
    """Serialize a priority policy."""
    fallback_priority = policy.fallback_priority if policy.fallback_priority_id else None

    data = {
        "id": policy.id,
        "team_id": policy.team_id,
        "team_name": policy.team.name if policy.team else None,
        "team_slug": policy.team.slug if policy.team else None,
        "name": policy.name,
        "description": policy.description,
        "enabled": policy.enabled,
        "default_for_team": policy.default_for_team,
        "update_mode": policy.update_mode,
        "source_priority_mode": policy.source_priority_mode,
        "fallback_mode": policy.fallback_mode,
        "fallback_priority_id": fallback_priority.id if fallback_priority else None,
        "fallback_priority": {
            "id": fallback_priority.id,
            "slug": fallback_priority.slug,
            "name": fallback_priority.name,
            "level": fallback_priority.level,
            "enabled": fallback_priority.enabled,
        } if fallback_priority else None,
        "rules_count": priority_policies_repo.count_priority_policy_rules(policy.id),
        "services_count": priority_policies_repo.count_priority_policy_services(policy.id),
        "created_at": policy.created_at.isoformat() if policy.created_at else None,
        "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
    }

    if include_rules:
        data["rules"] = [serialize_rule(rule) for rule in priority_policies_repo.list_priority_policy_rules(policy.id)]

    return attach_team_permissions(data, policy.team_id, current_user)


def list_policies(*, team_id=None, team_ids=None, enabled_only=False, current_user=None):
    """Return serialized priority policies."""
    policies = priority_policies_repo.list_priority_policies(team_id=team_id, team_ids=team_ids, enabled_only=enabled_only)
    return [serialize_policy(policy, current_user) for policy in policies]
