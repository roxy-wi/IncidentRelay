"""Validate and publish orchestration versions under the existing row locks.

This service owns the operation and its transaction; repositories must not
import it. HTTP, worker and import callers use these entry points.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.db import database_proxy
from app.modules.common import utc_now
from app.modules.db import models as db_models
from app.modules.db import orchestrations_repo
from app.modules.db.models import (
    EventOrchestration,
    EventOrchestrationRule,
    EventOrchestrationVersion,
)
from app.services.orchestration.validation import (
    issues_to_messages,
    validate_rule_definition,
)

_REFERENCE_ACTIONS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "set_team": ("Team", ("team_id", "value")),
    "set_route": ("AlertRoute", ("route_id", "value")),
    "set_service": ("Service", ("service_id", "value")),
    "set_escalation_policy": (
        "EscalationPolicy",
        ("escalation_policy_id", "policy_id", "value"),
    ),
    "set_notification_policy": (
        "NotificationPolicy",
        ("notification_policy_id", "policy_id", "value"),
    ),
    "set_priority_policy": (
        "PriorityPolicy",
        ("priority_policy_id", "policy_id", "value"),
    ),
    "enqueue_webhook": (
        "OrchestrationWebhookAction",
        ("action_id", "webhook_action_id"),
    ),
}


def _walk_json(value: Any):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _extract_reference_id(action: Dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in action and action[key] not in (None, ""):
            return action[key]
    params = action.get("params")
    if isinstance(params, dict):
        for key in keys:
            if key in params and params[key] not in (None, ""):
                return params[key]
    return None


def _entity_group_id(entity: Any) -> Optional[int]:
    direct = getattr(entity, "group_id", None)
    if direct is not None:
        return int(direct)

    team_id = getattr(entity, "team_id", None)
    if team_id is not None:
        team_model = getattr(db_models, "Team", None)
        if team_model is None:
            return None
        value = (
            team_model.select(team_model.group).where(team_model.id == team_id).scalar()
        )
        return int(value) if value is not None else None

    service_id = getattr(entity, "service_id", None)
    if service_id is not None:
        return orchestrations_repo._service_group_id(service_id)

    return None


def _validate_action_references(
    actions: Any,
    orchestration_group_id: int,
    rule_path: str,
) -> List[str]:
    errors: List[str] = []
    for node in _walk_json(actions):
        if not isinstance(node, dict):
            continue
        action_type = node.get("type") or node.get("action")
        reference_spec = _REFERENCE_ACTIONS.get(action_type)
        if reference_spec is None:
            continue

        model_name, id_keys = reference_spec
        reference_id = _extract_reference_id(node, id_keys)
        if reference_id in (None, ""):
            if action_type in {"set_team", "set_service"} and "label_key" in node:
                # Rule validation checks the key. Its value is known only at intake.
                continue
            errors.append(f"{rule_path}: {action_type} requires a reference id")
            continue

        model = getattr(db_models, model_name, None)
        if model is None:
            errors.append(
                f"{rule_path}: action {action_type} references unsupported model {model_name}"
            )
            continue

        try:
            reference_id = int(reference_id)
        except (TypeError, ValueError):
            errors.append(f"{rule_path}: {action_type} reference id must be an integer")
            continue

        entity = model.get_or_none(model.id == reference_id)
        if entity is None:
            errors.append(f"{rule_path}: referenced {model_name} does not exist")
            continue
        if action_type == "enqueue_webhook" and (
            not bool(getattr(entity, "enabled", False))
            or bool(getattr(entity, "deleted", False))
            or getattr(entity, "deleted_at", None) is not None
        ):
            errors.append(f"{rule_path}: referenced webhook action is disabled")
            continue

        entity_group_id = _entity_group_id(entity)
        if entity_group_id is None:
            errors.append(
                f"{rule_path}: could not determine group for referenced {model_name}"
            )
        elif entity_group_id != int(orchestration_group_id):
            errors.append(
                f"{rule_path}: referenced {model_name} belongs to another group"
            )

    return errors


def validate_version(version_id: int) -> Dict[str, Any]:
    """Validate a persisted version without changing or publishing its rules.

    Publication calls this while holding its orchestration and draft locks;
    standalone validation is advisory and does not reserve the version.
    """
    version = orchestrations_repo._get_version(version_id)
    orchestration = version.orchestration
    errors: List[str] = []
    warnings: List[str] = []

    if version.status not in orchestrations_repo.VALID_VERSION_STATUSES:
        errors.append("invalid version status")
    if orchestration.scope not in orchestrations_repo.VALID_SCOPES:
        errors.append("invalid orchestration scope")
    if orchestration.mode not in orchestrations_repo.VALID_MODES:
        errors.append("invalid orchestration mode")
    if (
        orchestration.compatibility_mode
        not in orchestrations_repo.VALID_COMPATIBILITY_MODES
    ):
        errors.append("invalid orchestration compatibility mode")

    if orchestration.scope == "global" and orchestration.service_id is not None:
        errors.append("global orchestration cannot reference a service")
    if orchestration.scope == "service":
        if orchestration.service_id is None:
            errors.append("service-scoped orchestration requires a service")
        elif (
            orchestrations_repo._service_group_id(orchestration.service_id)
            != orchestration.group_id
        ):
            errors.append("service-scoped orchestration references another group")

    rules = list(
        EventOrchestrationRule.select()
        .where(EventOrchestrationRule.version == version.id)
        .order_by(EventOrchestrationRule.id.asc())
    )
    if not rules:
        warnings.append("orchestration version has no rules")

    positions: Dict[Tuple[Optional[int], int], int] = {}
    for rule in rules:
        path = f"rule {rule.id} ({rule.name})"
        if rule.processing_mode not in orchestrations_repo.VALID_PROCESSING_MODES:
            errors.append(f"{path}: invalid processing_mode")
        if not isinstance(rule.condition_tree_json, dict):
            errors.append(f"{path}: condition_tree must be an object")
        if not isinstance(rule.actions_json, list):
            errors.append(f"{path}: actions must be a list")

        # EVENT_ORCHESTRATION_WS2_VALIDATION
        if isinstance(rule.condition_tree_json, dict) and isinstance(
            rule.actions_json, list
        ):
            rule_validation = validate_rule_definition(
                rule.condition_tree_json,
                rule.actions_json,
                path=path,
            )
            errors.extend(issues_to_messages(rule_validation["errors"]))
            warnings.extend(issues_to_messages(rule_validation["warnings"]))

            if orchestration.scope == "service" and any(
                isinstance(action, dict)
                and (action.get("type") or action.get("action")) == "set_trace_level"
                for action in rule.actions_json
            ):
                errors.append(
                    f"{path}: set_trace_level is only supported in global orchestrations"
                )
        if rule.parent_rule_id is not None:
            parent_version_id = (
                EventOrchestrationRule.select(EventOrchestrationRule.version)
                .where(EventOrchestrationRule.id == rule.parent_rule_id)
                .scalar()
            )
            if parent_version_id != version.id:
                errors.append(f"{path}: parent belongs to another version")

        position_key = (rule.parent_rule_id, rule.position)
        positions[position_key] = positions.get(position_key, 0) + 1
        if positions[position_key] > 1:
            errors.append(f"{path}: duplicate sibling position {rule.position}")

        errors.extend(
            _validate_action_references(
                rule.actions_json,
                orchestration.group_id,
                path,
            )
        )

    exported = orchestrations_repo.export_version(version.id)
    digest = orchestrations_repo.definition_hash(exported)
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "definition": exported,
        "definition_hash": digest,
    }


def _constant_condition_value(condition: Any) -> Optional[bool]:
    """Return True/False for statically constant condition trees."""
    if not isinstance(condition, dict):
        return None
    if not condition:
        return True

    logical = [key for key in ("all", "any", "none") if key in condition]
    if len(logical) != 1 or len(condition) != 1:
        return None

    key = logical[0]
    children = condition.get(key)
    if not isinstance(children, list):
        return None
    values = [_constant_condition_value(child) for child in children]

    if key == "all":
        if any(value is False for value in values):
            return False
        if all(value is True for value in values):
            return True
        return None

    if key == "any":
        if any(value is True for value in values):
            return True
        if all(value is False for value in values):
            return False
        return None

    # none is the negation of any(children).
    if any(value is True for value in values):
        return False
    if all(value is False for value in values):
        return True
    return None


def _definition_has_catch_all_drop(definition: Dict[str, Any]) -> bool:
    def walk(rules):
        for rule in rules or []:
            if not isinstance(rule, dict) or not bool(rule.get("enabled", True)):
                continue
            actions = rule.get("actions") or []
            if _constant_condition_value(
                rule.get("condition_tree") or {}
            ) is True and any(
                isinstance(action, dict)
                and (action.get("type") or action.get("action")) == "drop"
                for action in actions
            ):
                return True
            if walk(rule.get("children") or []):
                return True
        return False

    return walk(definition.get("rules") or [])


def _publish_version_locked(
    orchestration: EventOrchestration,
    draft: EventOrchestrationVersion,
    *,
    actor_id: Optional[int],
    comment: Optional[str],
    confirm_catch_all_drop: bool = False,
) -> EventOrchestrationVersion:
    if draft.orchestration_id != orchestration.id:
        raise orchestrations_repo.OrchestrationConflict(
            "Draft belongs to another orchestration"
        )
    orchestrations_repo._assert_draft(draft)

    validation = validate_version(draft.id)
    if not validation["valid"]:
        raise orchestrations_repo.OrchestrationValidationError(
            validation["errors"],
            validation["warnings"],
        )
    if (
        _definition_has_catch_all_drop(validation["definition"])
        and not confirm_catch_all_drop
    ):
        raise orchestrations_repo.OrchestrationValidationError(
            ["catch-all drop requires explicit publish confirmation"],
            validation["warnings"],
        )

    now = utc_now()
    EventOrchestrationVersion.update(
        status="archived",
        updated_at=now,
    ).where(
        (EventOrchestrationVersion.orchestration == orchestration.id)
        & (EventOrchestrationVersion.status == "published")
        & (EventOrchestrationVersion.id != draft.id)
    ).execute()

    update_values: Dict[str, Any] = {
        "status": "published",
        "definition_hash": validation["definition_hash"],
        "definition_json": validation["definition"],
        "published_by": actor_id,
        "published_at": now,
        "updated_at": now,
    }
    if comment is not None:
        update_values["comment"] = comment

    updated = (
        EventOrchestrationVersion.update(**update_values)
        .where(
            (EventOrchestrationVersion.id == draft.id)
            & (EventOrchestrationVersion.status == "draft")
        )
        .execute()
    )
    if updated != 1:
        raise orchestrations_repo.OrchestrationConflict(
            "Draft changed while it was being published"
        )

    EventOrchestration.update(
        active_version_id=draft.id,
        updated_at=now,
    ).where(EventOrchestration.id == orchestration.id).execute()

    return orchestrations_repo._get_version(draft.id)


def publish_draft(
    orchestration_id: int,
    *,
    actor_id: Optional[int] = None,
    comment: Optional[str] = None,
    confirm_catch_all_drop: bool = False,
) -> EventOrchestrationVersion:
    """Validate and atomically activate the current draft."""

    with database_proxy.atomic():
        orchestration = orchestrations_repo._locked_orchestration(orchestration_id)
        draft_query = (
            EventOrchestrationVersion.select()
            .where(
                (EventOrchestrationVersion.orchestration == orchestration.id)
                & (EventOrchestrationVersion.status == "draft")
            )
            .order_by(EventOrchestrationVersion.version_number.desc())
        )
        draft = orchestrations_repo._for_update(draft_query).first()
        if draft is None:
            raise orchestrations_repo.OrchestrationConflict(
                "Orchestration has no draft to publish"
            )
        return _publish_version_locked(
            orchestration,
            draft,
            actor_id=actor_id,
            comment=comment,
            confirm_catch_all_drop=confirm_catch_all_drop,
        )


def rollback_to_version(
    orchestration_id: int,
    source_version_id: int,
    *,
    actor_id: Optional[int] = None,
    comment: Optional[str] = None,
    confirm_catch_all_drop: bool = False,
) -> EventOrchestrationVersion:
    """Publish a new immutable version copied from an earlier version."""

    with database_proxy.atomic():
        orchestration = orchestrations_repo._locked_orchestration(orchestration_id)
        source = orchestrations_repo._get_version(source_version_id)
        if source.orchestration_id != orchestration.id:
            raise orchestrations_repo.OrchestrationValidationError(
                ["rollback source belongs to another orchestration"]
            )
        if source.status not in {"published", "archived"}:
            raise orchestrations_repo.OrchestrationValidationError(
                ["rollback source must be published or archived"]
            )
        if orchestrations_repo.get_draft(orchestration.id) is not None:
            raise orchestrations_repo.OrchestrationConflict(
                "Archive or publish the existing draft before rollback"
            )

        draft = EventOrchestrationVersion.create(
            orchestration=orchestration.id,
            version_number=orchestrations_repo._next_version_number(orchestration.id),
            status="draft",
            definition_json={},
            comment=comment or f"Rollback to version {source.version_number}",
            created_by=actor_id,
        )
        orchestrations_repo._clone_version_rules(source.id, draft)
        return _publish_version_locked(
            orchestration,
            draft,
            actor_id=actor_id,
            comment=draft.comment,
            confirm_catch_all_drop=confirm_catch_all_drop,
        )
