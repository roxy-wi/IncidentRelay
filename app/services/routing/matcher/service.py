from peewee import DoesNotExist

from app.modules.db import matcher_presets_repo, teams_repo
from app.services.serializers import attach_team_permissions


class MatcherPresetError(ValueError):
    """Base matcher preset domain error."""


class MatcherPresetNotFoundError(MatcherPresetError):
    """Requested matcher preset was not found."""


class MatcherPresetConflictError(MatcherPresetError):
    """Matcher preset conflicts with another resource."""


class MatcherPresetInUseError(MatcherPresetConflictError):
    """Matcher preset is still used by policy rules."""


def _payload_dict(payload):
    if hasattr(payload, "model_dump"):
        return payload.model_dump(exclude_unset=True)

    return dict(payload or {})


def _clean_name(value):
    name = str(value or "").strip()

    if not name:
        raise MatcherPresetError("matcher preset name is required")

    return name


def _require_team(team_id):
    try:
        team = teams_repo.get_team(int(team_id))
    except (DoesNotExist, TypeError, ValueError) as exc:
        raise MatcherPresetNotFoundError("team was not found") from exc

    if not team.active:
        raise MatcherPresetError("matcher preset team is inactive")

    if team.group and (not team.group.active or team.group.deleted):
        raise MatcherPresetError("matcher preset group is inactive")

    return team


def get_preset(preset_id):
    """Return an active matcher preset."""
    try:
        return matcher_presets_repo.get_matcher_preset(preset_id)
    except DoesNotExist as exc:
        raise MatcherPresetNotFoundError(
            "matcher preset was not found"
        ) from exc


def create_preset(payload):
    """Create or restore a matcher preset."""
    data = _payload_dict(payload)
    team = _require_team(data.get("team_id"))
    name = _clean_name(data.get("name"))

    existing = matcher_presets_repo.get_matcher_preset_by_team_and_name(
        team.id,
        name,
        include_deleted=True,
    )

    if existing and not existing.deleted:
        raise MatcherPresetConflictError(
            "matcher preset with this name already exists in this team"
        )

    if existing:
        return matcher_presets_repo.restore_matcher_preset(
            existing.id,
            name=name,
            description=data.get("description"),
            matchers=data.get("matchers") or {},
            enabled=data.get("enabled", True),
        )

    return matcher_presets_repo.create_matcher_preset(
        team_id=team.id,
        name=name,
        description=data.get("description"),
        matchers=data.get("matchers") or {},
        enabled=data.get("enabled", True),
    )


def update_preset(preset_id, payload):
    """Update a matcher preset and increment its version."""
    preset = get_preset(preset_id)
    data = _payload_dict(payload)

    if "name" in data:
        name = _clean_name(data["name"])

        existing = matcher_presets_repo.get_matcher_preset_by_team_and_name(
            preset.team_id,
            name,
            include_deleted=True,
            exclude_preset_id=preset.id,
        )

        if existing:
            raise MatcherPresetConflictError(
                "matcher preset with this name already exists in this team"
            )

        data["name"] = name

    changed = any(
        getattr(preset, field) != value
        for field, value in data.items()
        if field in {"name", "description", "matchers", "enabled"}
    )

    if not changed:
        return preset

    data["version"] = int(preset.version or 0) + 1
    return matcher_presets_repo.update_matcher_preset(preset.id, data)


def delete_preset(preset_id):
    """Delete a preset when it is not referenced by active rules."""
    preset = get_preset(preset_id)
    usage_count = matcher_presets_repo.count_matcher_preset_usages(preset.id)

    if usage_count:
        raise MatcherPresetInUseError(
            f"matcher preset is used by {usage_count} resource(s)"
        )

    return matcher_presets_repo.soft_delete_matcher_preset(preset.id)


def validate_preset_assignment(preset_id, *, team_id, enabled_only=True):
    """Validate a preset before assigning it to a policy rule."""
    if preset_id is None:
        return None

    preset = get_preset(preset_id)

    if preset.team_id != team_id:
        raise MatcherPresetError(
            "matcher preset belongs to another team"
        )

    if enabled_only and not preset.enabled:
        raise MatcherPresetError("matcher preset is disabled")

    return preset


def serialize_preset(preset, current_user=None, *, include_usages=False):
    """Serialize a matcher preset."""
    notification_count = matcher_presets_repo.count_notification_policy_usages(preset.id)
    priority_count = matcher_presets_repo.count_priority_policy_usages(preset.id)
    route_count = matcher_presets_repo.count_route_usages(preset.id)
    service_match_rule_count = matcher_presets_repo.count_service_match_rule_usages(preset.id)
    silence_count = matcher_presets_repo.count_silence_usages(preset.id)

    data = {
        "id": preset.id,
        "team_id": preset.team_id,
        "team_name": preset.team.name if preset.team else None,
        "team_slug": preset.team.slug if preset.team else None,
        "name": preset.name,
        "description": preset.description,
        "matchers": preset.matchers or {},
        "enabled": preset.enabled,
        "version": preset.version,
        "usage_count": (
            notification_count
            + priority_count
            + route_count
            + service_match_rule_count
            + silence_count
        ),
        "silences_count": silence_count,
        "notification_policy_rules_count": notification_count,
        "priority_policy_rules_count": priority_count,
        "routes_count": route_count,
        "service_match_rules_count": service_match_rule_count,
        "created_at": preset.created_at.isoformat() if preset.created_at else None,
        "updated_at": preset.updated_at.isoformat() if preset.updated_at else None,

    }

    if include_usages:
        usages = matcher_presets_repo.list_matcher_preset_usages(preset.id)

        data["usages"] = {
            "notification_policy_rules": [
                {
                    "id": rule.id,
                    "name": rule.name,
                    "policy_id": rule.policy_id,
                    "policy_name": rule.policy.name,
                }
                for rule in usages["notification_policy_rules"]
            ],
            "priority_policy_rules": [
                {
                    "id": rule.id,
                    "name": rule.name,
                    "policy_id": rule.policy_id,
                    "policy_name": rule.policy.name,
                }
                for rule in usages["priority_policy_rules"]
            ],
            "routes": [
                {
                    "id": route.id,
                    "name": route.name,
                    "team_id": route.team_id,
                }
                for route in usages["routes"]
            ],
            "service_match_rules": [
                {
                    "id": rule.id,
                    "name": rule.name,
                    "service_id": rule.service_id,
                    "service_name": rule.service.name,
                    "route_id": rule.route_id,
                    "route_name": rule.route.name if rule.route_id else None,
                }
                for rule in usages["service_match_rules"]
            ],
            "silences": [
                {
                    "id": silence.id,
                    "name": silence.name,
                    "team_id": silence.team_id,
                    "starts_at": silence.starts_at.isoformat() if silence.starts_at else None,
                    "ends_at": silence.ends_at.isoformat() if silence.ends_at else None,
                    "enabled": silence.enabled,
                }
                for silence in usages["silences"]
            ],
        }

    return attach_team_permissions(data, preset.team_id, current_user)


def list_presets(*, team_id=None, team_ids=None, enabled_only=False, current_user=None):
    """Return serialized matcher presets."""
    presets = matcher_presets_repo.list_matcher_presets(
        team_id=team_id,
        team_ids=team_ids,
        enabled_only=enabled_only,
    )

    return [serialize_preset(preset, current_user) for preset in presets]
