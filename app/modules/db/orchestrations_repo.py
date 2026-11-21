import hashlib
import json
import secrets
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from peewee import IntegrityError, fn

from app.db import database_proxy
from app.modules.db.models import (
    EventOrchestration,
    EventOrchestrationRule,
    EventOrchestrationVersion,
    OrchestrationIntakeToken,
    Service,
)
from app.modules.token_hashing import hash_token
from app.modules.common import utc_now


VALID_SCOPES = {"global", "service"}
VALID_MODES = {"active", "shadow", "disabled"}
VALID_COMPATIBILITY_MODES = {"legacy", "hybrid", "orchestration"}
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
    compatibility_mode: str = "legacy",
) -> EventOrchestration:
    name = (name or "").strip()
    if not name:
        raise OrchestrationValidationError(["name is required"])
    if scope not in VALID_SCOPES:
        raise OrchestrationValidationError(["scope must be global or service"])
    if compatibility_mode not in VALID_COMPATIBILITY_MODES:
        raise OrchestrationValidationError(["invalid compatibility_mode"])
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

    existing = EventOrchestration.get_or_none(
        (EventOrchestration.group == group_id)
        & (EventOrchestration.name == name)
    )
    if existing is not None and existing.deleted:
        existing.description = description
        existing.scope = scope
        existing.service = service_id
        existing.enabled = False
        existing.mode = "disabled"
        existing.compatibility_mode = compatibility_mode
        existing.active_version_id = None
        existing.created_by = created_by_id
        existing.deleted = False
        existing.deleted_at = None
        existing.updated_at = utc_now()
        existing.save()
        return existing

    try:
        return EventOrchestration.create(
            group=group_id,
            name=name,
            description=description,
            scope=scope,
            service=service_id,
            enabled=False,
            mode="disabled",
            compatibility_mode=compatibility_mode,
            created_by=created_by_id,
        )
    except IntegrityError as exc:
        raise OrchestrationConflict(
            "An orchestration with this name already exists in the group"
        ) from exc


def get_orchestration(orchestration_id: int) -> EventOrchestration:
    """Return a non-deleted orchestration by id."""
    orchestration = _get_orchestration(orchestration_id)
    if bool(getattr(orchestration, "deleted", False)) or getattr(
        orchestration, "deleted_at", None
    ) is not None:
        raise OrchestrationNotFound("Event orchestration not found")
    return orchestration


def list_orchestrations(
    *,
    group_ids: Optional[Sequence[int]] = None,
    group_id: Optional[int] = None,
) -> List[EventOrchestration]:
    """List non-deleted orchestrations visible in the requested groups."""
    query = EventOrchestration.select().where(
        (EventOrchestration.deleted == False)  # noqa: E712
        & EventOrchestration.deleted_at.is_null(True)
    )
    if group_id is not None:
        query = query.where(EventOrchestration.group == int(group_id))
    elif group_ids is not None:
        normalized = sorted({int(value) for value in group_ids})
        if not normalized:
            return []
        query = query.where(EventOrchestration.group.in_(normalized))
    return list(
        query.order_by(
            EventOrchestration.group.asc(),
            EventOrchestration.name.asc(),
            EventOrchestration.id.asc(),
        )
    )


def update_orchestration(
    orchestration_id: int,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    description_provided: bool = False,
    scope: Optional[str] = None,
    scope_provided: bool = False,
    service_id: Optional[int] = None,
    service_provided: bool = False,
) -> EventOrchestration:
    """Update editable orchestration metadata without changing runtime state."""
    with database_proxy.atomic():
        orchestration = _locked_orchestration(orchestration_id)
        if name is not None:
            normalized_name = str(name or "").strip()
            if not normalized_name:
                raise OrchestrationValidationError(["name is required"])
            orchestration.name = normalized_name
        if description_provided:
            orchestration.description = description

        next_scope = scope if scope_provided else orchestration.scope
        next_service_id = (
            service_id if service_provided else orchestration.service_id
        )

        if next_scope not in VALID_SCOPES:
            raise OrchestrationValidationError(
                ["scope must be global or service"]
            )
        if next_scope == "global":
            if service_provided and service_id is not None:
                raise OrchestrationValidationError(
                    ["global orchestration cannot reference a service"]
                )
            next_service_id = None
        else:
            if next_service_id is None:
                raise OrchestrationValidationError(
                    ["service-scoped orchestration requires service_id"]
                )
            if _service_group_id(next_service_id) != int(orchestration.group_id):
                raise OrchestrationValidationError(
                    ["referenced service belongs to another group"]
                )

        orchestration.scope = next_scope
        orchestration.service = next_service_id
        try:
            orchestration.save()
        except IntegrityError as exc:
            raise OrchestrationConflict(
                "An orchestration with this name already exists in the group"
            ) from exc
    return get_orchestration(orchestration_id)


def list_versions(orchestration_id: int) -> List[EventOrchestrationVersion]:
    orchestration = get_orchestration(orchestration_id)
    return list(
        EventOrchestrationVersion.select()
        .where(EventOrchestrationVersion.orchestration == orchestration.id)
        .order_by(
            EventOrchestrationVersion.version_number.desc(),
            EventOrchestrationVersion.id.desc(),
        )
    )


def get_version(
    orchestration_id: int,
    version_id: int,
) -> EventOrchestrationVersion:
    orchestration = get_orchestration(orchestration_id)
    version = _get_version(version_id)
    if version.orchestration_id != orchestration.id:
        raise OrchestrationNotFound("Orchestration version not found")
    return version


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
        EventOrchestrationVersion.update(updated_at=utc_now()).where(
            EventOrchestrationVersion.id == version.id
        ).execute()
    return _get_version(version_id)


def save_draft_definition(
    orchestration_id: int,
    rules: Sequence[Dict[str, Any]],
    *,
    actor_id: Optional[int] = None,
    comment: Optional[str] = None,
) -> EventOrchestrationVersion:
    """Create/update one draft definition and its metadata atomically."""
    with database_proxy.atomic():
        draft = get_or_create_draft(
            orchestration_id,
            actor_id=actor_id,
            comment=comment,
        )
        draft = replace_draft_rules(draft.id, rules)
        if comment is not None:
            EventOrchestrationVersion.update(
                comment=comment,
                updated_at=utc_now(),
            ).where(
                EventOrchestrationVersion.id == draft.id
            ).execute()
            draft = _get_version(draft.id)
        return draft


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


def ensure_draft_with_creation_status(
    orchestration_id: int,
    *,
    actor_id: Optional[int] = None,
) -> tuple[EventOrchestrationVersion, bool]:
    """Ensure a draft under the parent lock; return (draft, newly_created).

    Using the same lock for the existence check and creation prevents two
    concurrent POST /draft requests from both claiming they created a draft.
    """
    with database_proxy.atomic():
        _locked_orchestration(orchestration_id)
        existing = get_draft(orchestration_id)
        if existing is not None:
            return existing, False
        return get_or_create_draft(orchestration_id, actor_id=actor_id), True


def archive_draft(version_id: int) -> EventOrchestrationVersion:
    with database_proxy.atomic():
        version = _locked_version(version_id)
        _assert_draft(version)
        EventOrchestrationRule.delete().where(
            EventOrchestrationRule.version == version.id
        ).execute()
        EventOrchestrationVersion.update(
            status="archived",
            updated_at=utc_now(),
        ).where(
            (EventOrchestrationVersion.id == version.id)
            & (EventOrchestrationVersion.status == "draft")
        ).execute()
    return _get_version(version_id)


def set_runtime_state(
    orchestration_id: int,
    *,
    enabled: bool,
    mode: str,
    compatibility_mode: str,
) -> EventOrchestration:
    """Enable or disable one orchestration runtime atomically."""
    if mode not in VALID_MODES:
        raise OrchestrationValidationError(["invalid orchestration mode"])
    if compatibility_mode not in VALID_COMPATIBILITY_MODES:
        raise OrchestrationValidationError(["invalid compatibility_mode"])
    if bool(enabled) != (mode != "disabled"):
        raise OrchestrationValidationError([
            "enabled must be true for active/shadow mode and false for disabled mode"
        ])
    with database_proxy.atomic():
        orchestration = _locked_orchestration(orchestration_id)
        if enabled and mode != "disabled" and orchestration.active_version_id is None:
            raise OrchestrationConflict("Published version is required before enabling runtime")
        EventOrchestration.update(
            enabled=bool(enabled),
            mode=mode,
            compatibility_mode=compatibility_mode,
            updated_at=utc_now(),
        ).where(EventOrchestration.id == orchestration.id).execute()
    return _get_orchestration(orchestration_id)


def list_runtime_orchestrations(
    *,
    group_id: int,
    scope: str,
    service_id: Optional[int] = None,
) -> List[EventOrchestration]:
    """Return enabled runtime orchestrations in deterministic order."""
    if scope not in VALID_SCOPES:
        raise OrchestrationValidationError(["scope must be global or service"])
    query = EventOrchestration.select().where(
        (EventOrchestration.group == group_id)
        & (EventOrchestration.scope == scope)
        & (EventOrchestration.enabled == True)  # noqa: E712
        & (EventOrchestration.mode.in_(("active", "shadow")))
        & EventOrchestration.active_version_id.is_null(False)
        & (EventOrchestration.deleted == False)  # noqa: E712
        & EventOrchestration.deleted_at.is_null(True)
    )
    if scope == "service":
        query = query.where(EventOrchestration.service == service_id)
    return list(query.order_by(EventOrchestration.id.asc()))


def get_published_runtime_version(orchestration: EventOrchestration) -> EventOrchestrationVersion:
    """Return and verify the exact published version selected for runtime."""
    if orchestration.active_version_id is None:
        raise OrchestrationConflict("Orchestration has no active version")
    version = _get_version(orchestration.active_version_id)
    if version.orchestration_id != orchestration.id or version.status != "published":
        raise OrchestrationConflict("Active orchestration version is not published")
    return version


def archive_orchestration(orchestration_id: int) -> EventOrchestration:
    with database_proxy.atomic():
        orchestration = _locked_orchestration(orchestration_id)
        now = utc_now()
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

        from app.modules.db.soft_delete_hardening import cancel_pending_orchestration_work
        cancel_pending_orchestration_work(
            orchestration_ids=[orchestration.id],
            now=now,
            reason="orchestration_deleted",
        )
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
    """Authenticate an intake token only for a live orchestration.

    The parent check is intentionally defensive: installations upgraded from
    versions that did not revoke intake tokens during every soft-delete path
    may contain an enabled token whose orchestration is already deleted.
    """
    if not plaintext:
        return None
    token = (
        OrchestrationIntakeToken
        .select(OrchestrationIntakeToken, EventOrchestration)
        .join(EventOrchestration)
        .where(
            (OrchestrationIntakeToken.token_hash == hash_token(plaintext))
            & (OrchestrationIntakeToken.enabled == True)  # noqa: E712
            & OrchestrationIntakeToken.revoked_at.is_null(True)
            & (EventOrchestration.deleted == False)  # noqa: E712
            & EventOrchestration.deleted_at.is_null(True)
        )
        .first()
    )
    if token is None:
        return None
    OrchestrationIntakeToken.update(last_used_at=utc_now()).where(
        OrchestrationIntakeToken.id == token.id
    ).execute()
    return token


def revoke_intake_tokens_for_scope(*, group_id=None, service_id=None, now=None) -> int:
    """Revoke every intake token owned by the selected orchestration scope.

    Unlike ``archive_orchestration`` this also covers already soft-deleted
    orchestrations, repairing legacy rows that may still carry an enabled
    credential.
    """
    if group_id is None and service_id is None:
        return 0

    query = EventOrchestration.select(EventOrchestration.id)
    if group_id is not None:
        query = query.where(EventOrchestration.group == int(group_id))
    if service_id is not None:
        query = query.where(EventOrchestration.service == int(service_id))

    now = now or utc_now()
    return (
        OrchestrationIntakeToken
        .update(enabled=False, revoked_at=now)
        .where(
            OrchestrationIntakeToken.orchestration.in_(query)
            & (
                (OrchestrationIntakeToken.enabled == True)  # noqa: E712
                | OrchestrationIntakeToken.revoked_at.is_null(True)
            )
        )
        .execute()
    )


def revoke_intake_token(token_id: int) -> OrchestrationIntakeToken:
    now = utc_now()
    updated = OrchestrationIntakeToken.update(
        enabled=False,
        revoked_at=now,
    ).where(OrchestrationIntakeToken.id == token_id).execute()
    if updated != 1:
        raise OrchestrationNotFound("Orchestration intake token not found")
    return OrchestrationIntakeToken.get_by_id(token_id)
