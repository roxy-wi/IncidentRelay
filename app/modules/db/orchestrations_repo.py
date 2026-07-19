import hashlib
import json
import secrets
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from peewee import IntegrityError, fn

from app.modules.db import models as db_models
from app.db import database_proxy
from app.modules.db.models import (
    EventOrchestration,
    EventOrchestrationRule,
    EventOrchestrationVersion,
    OrchestrationIntakeToken,
    Service,
)
from app.services.integrations.auth import hash_token


VALID_SCOPES = {"global", "service"}
VALID_MODES = {"active", "shadow", "disabled"}
VALID_VERSION_STATUSES = {"draft", "published", "archived"}
VALID_PROCESSING_MODES = {
    "continue",
    "stop",
    "evaluate_children",
    "children_then_continue",
}


class OrchestrationError(ValueError):
    """Base error raised for invalid orchestration state transitions."""


class OrchestrationNotFound(OrchestrationError):
    pass


class OrchestrationConflict(OrchestrationError):
    pass


class OrchestrationValidationError(OrchestrationError):
    def __init__(self, errors: Sequence[str], warnings: Optional[Sequence[str]] = None):
        self.errors = list(errors)
        self.warnings = list(warnings or [])
        super().__init__("; ".join(self.errors) or "Invalid orchestration definition")


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
}


def canonical_json(value: Any) -> str:
    """Return the stable JSON representation used for content hashing."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def definition_hash(definition: Dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(definition).encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.utcnow()


def _get_orchestration(orchestration_id: int) -> EventOrchestration:
    orchestration = EventOrchestration.get_or_none(EventOrchestration.id == orchestration_id)
    if (
        orchestration is None
        or bool(orchestration.deleted)
        or orchestration.deleted_at is not None
    ):
        raise OrchestrationNotFound("Orchestration not found")
    return orchestration


def _get_version(version_id: int) -> EventOrchestrationVersion:
    version = EventOrchestrationVersion.get_or_none(
        EventOrchestrationVersion.id == version_id
    )
    if version is None:
        raise OrchestrationNotFound("Orchestration version not found")
    return version


def _for_update(query):
    """Use row locking where supported; SQLite is protected by its transaction."""

    database = getattr(database_proxy, "obj", None)
    if database is not None and database.__class__.__name__ != "SqliteDatabase":
        return query.for_update()
    return query


def _locked_version(version_id: int) -> EventOrchestrationVersion:
    version = _for_update(
        EventOrchestrationVersion.select().where(
            EventOrchestrationVersion.id == version_id
        )
    ).first()
    if version is None:
        raise OrchestrationNotFound("Orchestration version not found")
    return version


def _locked_orchestration(orchestration_id: int) -> EventOrchestration:
    query = EventOrchestration.select().where(
        (EventOrchestration.id == orchestration_id)
        & (EventOrchestration.deleted == False)  # noqa: E712
        & EventOrchestration.deleted_at.is_null(True)
    )
    orchestration = _for_update(query).first()
    if orchestration is None:
        raise OrchestrationNotFound("Orchestration not found")
    return orchestration


def _next_version_number(orchestration_id: int) -> int:
    maximum = (
        EventOrchestrationVersion.select(
            fn.MAX(EventOrchestrationVersion.version_number)
        )
        .where(EventOrchestrationVersion.orchestration == orchestration_id)
        .scalar()
    )
    return int(maximum or 0) + 1


def _assert_draft(version: EventOrchestrationVersion) -> None:
    if version.status != "draft":
        raise OrchestrationConflict("Only draft versions can be edited")


def _service_group_id(service_id: int) -> Optional[int]:
    value = Service.select(Service.group).where(Service.id == service_id).scalar()
    return int(value) if value is not None else None


def create_orchestration(
    *,
    group_id: int,
    name: str,
    scope: str = "global",
    service_id: Optional[int] = None,
    description: Optional[str] = None,
    created_by_id: Optional[int] = None,
) -> EventOrchestration:
    name = (name or "").strip()
    if not name:
        raise OrchestrationValidationError(["name is required"])
    if scope not in VALID_SCOPES:
        raise OrchestrationValidationError(["scope must be global or service"])
    if scope == "global" and service_id is not None:
        raise OrchestrationValidationError(
            ["global orchestration cannot reference a service"]
        )
    if scope == "service":
        if service_id is None:
            raise OrchestrationValidationError(
                ["service-scoped orchestration requires service_id"]
            )
        if _service_group_id(service_id) != int(group_id):
            raise OrchestrationValidationError(
                ["referenced service belongs to another group"]
            )

    try:
        return EventOrchestration.create(
            group=group_id,
            name=name,
            description=description,
            scope=scope,
            service=service_id,
            enabled=False,
            mode="disabled",
            created_by=created_by_id,
        )
    except IntegrityError as exc:
        raise OrchestrationConflict(
            "An orchestration with this name already exists in the group"
        ) from exc


def get_draft(orchestration_id: int) -> Optional[EventOrchestrationVersion]:
    return (
        EventOrchestrationVersion.select()
        .where(
            (EventOrchestrationVersion.orchestration == orchestration_id)
            & (EventOrchestrationVersion.status == "draft")
        )
        .order_by(EventOrchestrationVersion.version_number.desc())
        .first()
    )


def _serialize_rule(rule: EventOrchestrationRule) -> Dict[str, Any]:
    children = list(
        EventOrchestrationRule.select()
        .where(EventOrchestrationRule.parent_rule == rule.id)
        .order_by(
            EventOrchestrationRule.position.asc(),
            EventOrchestrationRule.id.asc(),
        )
    )
    return {
        "name": rule.name,
        "description": rule.description,
        "enabled": bool(rule.enabled),
        "condition_tree": rule.condition_tree_json or {},
        "actions": rule.actions_json or [],
        "processing_mode": rule.processing_mode,
        "children": [_serialize_rule(child) for child in children],
    }


def export_version(version_id: int) -> Dict[str, Any]:
    version = _get_version(version_id)
    orchestration = version.orchestration
    roots = list(
        EventOrchestrationRule.select()
        .where(
            (EventOrchestrationRule.version == version.id)
            & EventOrchestrationRule.parent_rule.is_null(True)
        )
        .order_by(
            EventOrchestrationRule.position.asc(),
            EventOrchestrationRule.id.asc(),
        )
    )
    return {
        "schema_version": 1,
        "scope": orchestration.scope,
        "service_id": orchestration.service_id,
        "rules": [_serialize_rule(rule) for rule in roots],
    }


def _create_rule_tree(
    version: EventOrchestrationVersion,
    rules: Iterable[Dict[str, Any]],
    parent_rule_id: Optional[int] = None,
) -> None:
    for position, raw_rule in enumerate(rules):
        if not isinstance(raw_rule, dict):
            raise OrchestrationValidationError(["every rule must be an object"])

        children = raw_rule.get("children") or []
        if not isinstance(children, list):
            raise OrchestrationValidationError(["rule children must be a list"])

        rule = EventOrchestrationRule.create(
            version=version.id,
            parent_rule=parent_rule_id,
            position=position,
            name=(raw_rule.get("name") or "").strip() or f"Rule {position + 1}",
            description=raw_rule.get("description"),
            enabled=bool(raw_rule.get("enabled", True)),
            condition_tree_json=raw_rule.get("condition_tree") or {},
            actions_json=raw_rule.get("actions") or [],
            processing_mode=raw_rule.get("processing_mode") or "continue",
        )
        _create_rule_tree(version, children, rule.id)


def replace_draft_rules(
    version_id: int,
    rules: Sequence[Dict[str, Any]],
) -> EventOrchestrationVersion:
    if not isinstance(rules, (list, tuple)):
        raise OrchestrationValidationError(["rules must be a list"])

    with database_proxy.atomic():
        version = _locked_version(version_id)
        _assert_draft(version)
        EventOrchestrationRule.delete().where(
            EventOrchestrationRule.version == version.id
        ).execute()
        _create_rule_tree(version, rules)
        EventOrchestrationVersion.update(updated_at=_utcnow()).where(
            EventOrchestrationVersion.id == version.id
        ).execute()
    return _get_version(version_id)


def _clone_version_rules(
    source_version_id: int,
    target_version: EventOrchestrationVersion,
) -> None:
    source_definition = export_version(source_version_id)
    _create_rule_tree(target_version, source_definition.get("rules") or [])


def get_or_create_draft(
    orchestration_id: int,
    *,
    actor_id: Optional[int] = None,
    comment: Optional[str] = None,
) -> EventOrchestrationVersion:
    with database_proxy.atomic():
        orchestration = _locked_orchestration(orchestration_id)
        draft = get_draft(orchestration.id)
        if draft is not None:
            return draft

        try:
            draft = EventOrchestrationVersion.create(
                orchestration=orchestration.id,
                version_number=_next_version_number(orchestration.id),
                status="draft",
                definition_json={},
                comment=comment,
                created_by=actor_id,
            )
        except IntegrityError as exc:
            # A concurrent creator may have won the unique version-number race.
            draft = get_draft(orchestration.id)
            if draft is None:
                raise OrchestrationConflict(
                    "Could not allocate an orchestration draft version"
                ) from exc
            return draft

        if orchestration.active_version_id is not None:
            active = _get_version(orchestration.active_version_id)
            if active.orchestration_id != orchestration.id:
                raise OrchestrationConflict(
                    "Active version does not belong to the orchestration"
                )
            _clone_version_rules(active.id, draft)

        return draft


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
        value = team_model.select(team_model.group).where(team_model.id == team_id).scalar()
        return int(value) if value is not None else None

    service_id = getattr(entity, "service_id", None)
    if service_id is not None:
        return _service_group_id(service_id)

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
    version = _get_version(version_id)
    orchestration = version.orchestration
    errors: List[str] = []
    warnings: List[str] = []

    if version.status not in VALID_VERSION_STATUSES:
        errors.append("invalid version status")
    if orchestration.scope not in VALID_SCOPES:
        errors.append("invalid orchestration scope")
    if orchestration.mode not in VALID_MODES:
        errors.append("invalid orchestration mode")

    if orchestration.scope == "global" and orchestration.service_id is not None:
        errors.append("global orchestration cannot reference a service")
    if orchestration.scope == "service":
        if orchestration.service_id is None:
            errors.append("service-scoped orchestration requires a service")
        elif _service_group_id(orchestration.service_id) != orchestration.group_id:
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
        if rule.processing_mode not in VALID_PROCESSING_MODES:
            errors.append(f"{path}: invalid processing_mode")
        if not isinstance(rule.condition_tree_json, dict):
            errors.append(f"{path}: condition_tree must be an object")
        if not isinstance(rule.actions_json, list):
            errors.append(f"{path}: actions must be a list")
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

    exported = export_version(version.id)
    digest = definition_hash(exported)
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "definition": exported,
        "definition_hash": digest,
    }


def _publish_version_locked(
    orchestration: EventOrchestration,
    draft: EventOrchestrationVersion,
    *,
    actor_id: Optional[int],
    comment: Optional[str],
) -> EventOrchestrationVersion:
    if draft.orchestration_id != orchestration.id:
        raise OrchestrationConflict("Draft belongs to another orchestration")
    _assert_draft(draft)

    validation = validate_version(draft.id)
    if not validation["valid"]:
        raise OrchestrationValidationError(
            validation["errors"],
            validation["warnings"],
        )

    now = _utcnow()
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
        raise OrchestrationConflict("Draft changed while it was being published")

    EventOrchestration.update(
        active_version_id=draft.id,
        updated_at=now,
    ).where(EventOrchestration.id == orchestration.id).execute()

    return _get_version(draft.id)


def publish_draft(
    orchestration_id: int,
    *,
    actor_id: Optional[int] = None,
    comment: Optional[str] = None,
) -> EventOrchestrationVersion:
    """Validate and atomically activate the current draft."""

    with database_proxy.atomic():
        orchestration = _locked_orchestration(orchestration_id)
        draft_query = EventOrchestrationVersion.select().where(
            (EventOrchestrationVersion.orchestration == orchestration.id)
            & (EventOrchestrationVersion.status == "draft")
        ).order_by(EventOrchestrationVersion.version_number.desc())
        draft = _for_update(draft_query).first()
        if draft is None:
            raise OrchestrationConflict("Orchestration has no draft to publish")
        return _publish_version_locked(
            orchestration,
            draft,
            actor_id=actor_id,
            comment=comment,
        )


def rollback_to_version(
    orchestration_id: int,
    source_version_id: int,
    *,
    actor_id: Optional[int] = None,
    comment: Optional[str] = None,
) -> EventOrchestrationVersion:
    """Publish a new immutable version copied from an earlier version."""

    with database_proxy.atomic():
        orchestration = _locked_orchestration(orchestration_id)
        source = _get_version(source_version_id)
        if source.orchestration_id != orchestration.id:
            raise OrchestrationValidationError(
                ["rollback source belongs to another orchestration"]
            )
        if source.status not in {"published", "archived"}:
            raise OrchestrationValidationError(
                ["rollback source must be published or archived"]
            )
        if get_draft(orchestration.id) is not None:
            raise OrchestrationConflict(
                "Archive or publish the existing draft before rollback"
            )

        draft = EventOrchestrationVersion.create(
            orchestration=orchestration.id,
            version_number=_next_version_number(orchestration.id),
            status="draft",
            definition_json={},
            comment=comment or f"Rollback to version {source.version_number}",
            created_by=actor_id,
        )
        _clone_version_rules(source.id, draft)
        return _publish_version_locked(
            orchestration,
            draft,
            actor_id=actor_id,
            comment=draft.comment,
        )


def archive_draft(version_id: int) -> EventOrchestrationVersion:
    with database_proxy.atomic():
        version = _locked_version(version_id)
        _assert_draft(version)
        EventOrchestrationRule.delete().where(
            EventOrchestrationRule.version == version.id
        ).execute()
        EventOrchestrationVersion.update(
            status="archived",
            updated_at=_utcnow(),
        ).where(
            (EventOrchestrationVersion.id == version.id)
            & (EventOrchestrationVersion.status == "draft")
        ).execute()
    return _get_version(version_id)


def archive_orchestration(orchestration_id: int) -> EventOrchestration:
    with database_proxy.atomic():
        orchestration = _locked_orchestration(orchestration_id)
        now = _utcnow()
        EventOrchestration.update(
            enabled=False,
            mode="disabled",
            deleted=True,
            deleted_at=now,
            updated_at=now,
        ).where(EventOrchestration.id == orchestration.id).execute()
        OrchestrationIntakeToken.update(
            enabled=False,
            revoked_at=now,
        ).where(
            (OrchestrationIntakeToken.orchestration == orchestration.id)
            & (OrchestrationIntakeToken.enabled == True)  # noqa: E712
        ).execute()
    return EventOrchestration.get_by_id(orchestration_id)


def create_intake_token(
    orchestration_id: int,
    *,
    name: str,
    actor_id: Optional[int] = None,
) -> Tuple[OrchestrationIntakeToken, str]:
    """Create a token and return plaintext once together with the DB record."""

    name = (name or "").strip()
    if not name:
        raise OrchestrationValidationError(["token name is required"])

    with database_proxy.atomic():
        orchestration = _locked_orchestration(orchestration_id)
        plaintext = secrets.token_urlsafe(32)
        record = OrchestrationIntakeToken.create(
            orchestration=orchestration.id,
            name=name,
            token_hash=hash_token(plaintext),
            token_prefix=plaintext[:12],
            enabled=True,
            created_by=actor_id,
        )
    return record, plaintext


def authenticate_intake_token(plaintext: str) -> Optional[OrchestrationIntakeToken]:
    if not plaintext:
        return None
    token = OrchestrationIntakeToken.get_or_none(
        (OrchestrationIntakeToken.token_hash == hash_token(plaintext))
        & (OrchestrationIntakeToken.enabled == True)  # noqa: E712
        & OrchestrationIntakeToken.revoked_at.is_null(True)
    )
    if token is None:
        return None
    OrchestrationIntakeToken.update(last_used_at=_utcnow()).where(
        OrchestrationIntakeToken.id == token.id
    ).execute()
    return token


def revoke_intake_token(token_id: int) -> OrchestrationIntakeToken:
    now = _utcnow()
    updated = OrchestrationIntakeToken.update(
        enabled=False,
        revoked_at=now,
    ).where(OrchestrationIntakeToken.id == token_id).execute()
    if updated != 1:
        raise OrchestrationNotFound("Orchestration intake token not found")
    return OrchestrationIntakeToken.get_by_id(token_id)
