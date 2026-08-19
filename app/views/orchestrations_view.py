"""Event Orchestration control-plane, simulator and replay APIs."""

from __future__ import annotations


from flask import Blueprint, jsonify, request
from peewee import IntegrityError

from app.api.schemas.orchestrations import (
    OrchestrationCreateSchema,
    OrchestrationDraftSchema,
    OrchestrationPublishSchema,
    OrchestrationReplaySchema,
    OrchestrationRollbackSchema,
    OrchestrationRuntimeSchema,
    OrchestrationSimulationSchema,
    OrchestrationUpdateSchema,
    OrchestrationWebhookActionCreateSchema,
    OrchestrationWebhookActionUpdateSchema,
)
from app.modules.db import orchestrations_repo
from app.modules.db.models import (
    AlertRoute,
    AutomationExecution,
    EscalationPolicy,
    EventOrchestrationVersion,
    Group,
    NotificationPolicy,
    OrchestrationWebhookAction,
    PriorityPolicy,
    Service,
    Team,
)
from app.services.audit import write_audit
from app.services.orchestration import simulator, webhooks
from app.services.integrations.normalizers.registry import SUPPORTED_NORMALIZER_SOURCES
from app.services.orchestration.permissions import (
    CREATE,
    DELETE,
    EDIT,
    MANAGE_ACTIONS,
    PUBLISH,
    REPLAY,
    SIMULATE,
    VIEW,
    VIEW_EXECUTIONS,
    has_orchestration_permission,
)
from app.services.rbac import current_user, get_allowed_group_ids
from app.services.validation import make_error_response, validate_body


orchestrations_bp = Blueprint("event_orchestrations_api", __name__)
orchestration_webhook_actions_bp = Blueprint(
    "orchestration_webhook_actions_api",
    __name__,
)


def _iso(value):
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


def _serialize_webhook_action(action):
    payload = webhooks.serialize_webhook_action(action)
    payload["created_at"] = _iso(payload.get("created_at"))
    payload["updated_at"] = _iso(payload.get("updated_at"))
    return payload


def _permission_map(user, group_id: int) -> dict[str, bool]:
    return {
        "view": has_orchestration_permission(user, group_id, VIEW),
        "create": has_orchestration_permission(user, group_id, CREATE),
        "edit": has_orchestration_permission(user, group_id, EDIT),
        "publish": has_orchestration_permission(user, group_id, PUBLISH),
        "delete": has_orchestration_permission(user, group_id, DELETE),
        "simulate": has_orchestration_permission(user, group_id, SIMULATE),
        "replay": has_orchestration_permission(user, group_id, REPLAY),
        "view_executions": has_orchestration_permission(
            user,
            group_id,
            VIEW_EXECUTIONS,
        ),
        "manage_actions": has_orchestration_permission(
            user,
            group_id,
            MANAGE_ACTIONS,
        ),
    }


def _serialize_version(version, *, include_definition=False):
    payload = {
        "id": version.id,
        "orchestration_id": version.orchestration_id,
        "version_number": version.version_number,
        "status": version.status,
        "definition_hash": version.definition_hash,
        "comment": version.comment,
        "created_by_id": version.created_by_id,
        "published_by_id": version.published_by_id,
        "created_at": _iso(version.created_at),
        "updated_at": _iso(version.updated_at),
        "published_at": _iso(version.published_at),
    }
    if include_definition:
        payload["definition"] = orchestrations_repo.export_version(version.id)
    return payload


def _serialize_orchestration(orchestration, *, include_definition=False):
    user = current_user()
    draft = orchestrations_repo.get_draft(orchestration.id)
    active = None
    if orchestration.active_version_id:
        active = EventOrchestrationVersion.get_or_none(
            EventOrchestrationVersion.id == orchestration.active_version_id
        )
    payload = {
        "id": orchestration.id,
        "uid": str(orchestration.uid),
        "group_id": orchestration.group_id,
        "name": orchestration.name,
        "description": orchestration.description,
        "scope": orchestration.scope,
        "service_id": orchestration.service_id,
        "enabled": bool(orchestration.enabled),
        "mode": orchestration.mode,
        "compatibility_mode": orchestration.compatibility_mode,
        "active_version_id": orchestration.active_version_id,
        "active_version": _serialize_version(active) if active else None,
        "draft": _serialize_version(draft, include_definition=include_definition)
        if draft
        else None,
        "created_by_id": orchestration.created_by_id,
        "created_at": _iso(orchestration.created_at),
        "updated_at": _iso(orchestration.updated_at),
        "permissions": _permission_map(user, orchestration.group_id),
    }
    if include_definition and active:
        payload["active_definition"] = orchestrations_repo.export_version(active.id)
    return payload


def _require_group_permission(group_id: int, permission: str):
    user = current_user()
    if user is None or not has_orchestration_permission(user, group_id, permission):
        return None, make_error_response(
            "forbidden",
            "You do not have permission to perform this orchestration action.",
            403,
        )
    return user, None


def _require_permission(orchestration_id, permission):
    try:
        orchestration = orchestrations_repo.get_orchestration(orchestration_id)
    except orchestrations_repo.OrchestrationNotFound:
        return None, make_error_response(
            "orchestration_not_found",
            "Event orchestration was not found.",
            404,
        )
    user, error = _require_group_permission(orchestration.group_id, permission)
    if error:
        return None, error
    return orchestration, None


def _repo_error_response(error):
    if isinstance(error, orchestrations_repo.OrchestrationNotFound):
        return make_error_response(
            "orchestration_not_found",
            "Event orchestration was not found.",
            404,
        )
    if isinstance(error, orchestrations_repo.OrchestrationConflict):
        return make_error_response(
            "orchestration_conflict",
            "Event orchestration conflicts with the current state.",
            409,
        )
    if isinstance(error, orchestrations_repo.OrchestrationValidationError):
        return make_error_response(
            "orchestration_validation_error",
            "Event orchestration definition is invalid.",
            400,
            errors=error.errors,
            warnings=error.warnings,
        )
    return make_error_response("invalid_request", "Invalid request.", 400)


@orchestrations_bp.errorhandler(simulator.OrchestrationSimulationError)
def handle_orchestration_simulation_error(error):
    if isinstance(error, simulator.OrchestrationSimulationNotFound):
        code = "orchestration_not_found"
        status = 404
    elif isinstance(error, simulator.OrchestrationSimulationConflict):
        code = "orchestration_conflict"
        status = 409
    else:
        code = "orchestration_simulation_invalid"
        status = 400
    return jsonify({"error": code, "message": "Orchestration simulation failed."}), status


@orchestrations_bp.route("", methods=["GET"])
@orchestrations_bp.route("/", methods=["GET"])
def list_orchestrations():
    user = current_user()
    allowed_group_ids = get_allowed_group_ids(user=user, use_active_group=False)
    group_id = request.args.get("group_id", type=int)
    if group_id is not None:
        if group_id not in allowed_group_ids or not has_orchestration_permission(
            user,
            group_id,
            VIEW,
        ):
            return make_error_response("forbidden", "Access to this group is denied", 403)
        group_ids = [group_id]
    else:
        group_ids = [
            value
            for value in allowed_group_ids
            if has_orchestration_permission(user, value, VIEW)
        ]
    items = orchestrations_repo.list_orchestrations(group_ids=group_ids)
    return jsonify(
        {
            "items": [_serialize_orchestration(item) for item in items],
            "count": len(items),
        }
    )


@orchestrations_bp.route("", methods=["POST"])
@orchestrations_bp.route("/", methods=["POST"])
def create_orchestration():
    payload, error = validate_body(OrchestrationCreateSchema)
    if error:
        return error
    user, error = _require_group_permission(payload.group_id, CREATE)
    if error:
        return error
    try:
        orchestration = orchestrations_repo.create_orchestration(
            group_id=payload.group_id,
            name=payload.name,
            description=payload.description,
            scope=payload.scope,
            service_id=payload.service_id,
            compatibility_mode=payload.compatibility_mode,
            created_by_id=user.id,
        )
        draft = orchestrations_repo.get_or_create_draft(
            orchestration.id,
            actor_id=user.id,
            comment="Initial draft",
        )
    except orchestrations_repo.OrchestrationError as exc:
        return _repo_error_response(exc)
    write_audit(
        "event_orchestration.create",
        object_type="event_orchestration",
        object_id=orchestration.id,
        group_id=orchestration.group_id,
        data={"scope": orchestration.scope, "draft_version_id": draft.id},
    )
    return jsonify(_serialize_orchestration(orchestration, include_definition=True)), 201


@orchestrations_bp.route("/<int:orchestration_id>", methods=["GET"])
def get_orchestration(orchestration_id):
    orchestration, error = _require_permission(orchestration_id, VIEW)
    if error:
        return error
    return jsonify(_serialize_orchestration(orchestration, include_definition=True))


@orchestrations_bp.route("/<int:orchestration_id>", methods=["PATCH"])
def update_orchestration(orchestration_id):
    orchestration, error = _require_permission(orchestration_id, EDIT)
    if error:
        return error
    payload, error = validate_body(OrchestrationUpdateSchema)
    if error:
        return error
    values = payload.model_dump(exclude_unset=True)
    try:
        orchestration = orchestrations_repo.update_orchestration(
            orchestration.id,
            name=values.get("name"),
            description=values.get("description"),
            description_provided="description" in values,
            scope=values.get("scope"),
            scope_provided="scope" in values,
            service_id=values.get("service_id"),
            service_provided="service_id" in values,
        )
    except orchestrations_repo.OrchestrationError as exc:
        return _repo_error_response(exc)
    write_audit(
        "event_orchestration.update",
        object_type="event_orchestration",
        object_id=orchestration.id,
        group_id=orchestration.group_id,
        data={"fields": sorted(values)},
    )
    return jsonify(_serialize_orchestration(orchestration, include_definition=True))


@orchestrations_bp.route("/<int:orchestration_id>", methods=["DELETE"])
def delete_orchestration(orchestration_id):
    orchestration, error = _require_permission(orchestration_id, DELETE)
    if error:
        return error
    try:
        archived = orchestrations_repo.archive_orchestration(orchestration.id)
    except orchestrations_repo.OrchestrationError as exc:
        return _repo_error_response(exc)
    write_audit(
        "event_orchestration.delete",
        object_type="event_orchestration",
        object_id=archived.id,
        group_id=archived.group_id,
    )
    return jsonify({"deleted": True, "id": archived.id})


@orchestrations_bp.route("/<int:orchestration_id>/draft", methods=["POST"])
def create_orchestration_draft(orchestration_id):
    orchestration, error = _require_permission(orchestration_id, EDIT)
    if error:
        return error
    user = current_user()
    try:
        draft = orchestrations_repo.get_or_create_draft(
            orchestration.id,
            actor_id=user.id,
        )
    except orchestrations_repo.OrchestrationError as exc:
        return _repo_error_response(exc)
    return jsonify(_serialize_version(draft, include_definition=True))


@orchestrations_bp.route("/<int:orchestration_id>/draft", methods=["PUT"])
def save_orchestration_draft(orchestration_id):
    orchestration, error = _require_permission(orchestration_id, EDIT)
    if error:
        return error
    payload, error = validate_body(OrchestrationDraftSchema)
    if error:
        return error
    user = current_user()
    try:
        draft = orchestrations_repo.save_draft_definition(
            orchestration.id,
            payload.rules,
            actor_id=user.id,
            comment=payload.comment,
        )
    except orchestrations_repo.OrchestrationError as exc:
        return _repo_error_response(exc)
    write_audit(
        "event_orchestration.draft_saved",
        object_type="event_orchestration_version",
        object_id=draft.id,
        group_id=orchestration.group_id,
        data={"orchestration_id": orchestration.id, "rule_count": len(payload.rules)},
    )
    return jsonify(_serialize_version(draft, include_definition=True))


@orchestrations_bp.route("/<int:orchestration_id>/validate", methods=["POST"])
def validate_orchestration(orchestration_id):
    orchestration, error = _require_permission(orchestration_id, EDIT)
    if error:
        return error
    draft = orchestrations_repo.get_draft(orchestration.id)
    if draft is None:
        return make_error_response(
            "orchestration_conflict",
            "Orchestration has no draft to validate.",
            409,
        )
    result = orchestrations_repo.validate_version(draft.id)
    return jsonify(result)


@orchestrations_bp.route("/<int:orchestration_id>/publish", methods=["POST"])
def publish_orchestration(orchestration_id):
    orchestration, error = _require_permission(orchestration_id, PUBLISH)
    if error:
        return error
    payload, error = validate_body(OrchestrationPublishSchema)
    if error:
        return error
    user = current_user()
    try:
        version = orchestrations_repo.publish_draft(
            orchestration.id,
            actor_id=user.id,
            comment=payload.comment,
            confirm_catch_all_drop=payload.confirm_catch_all_drop,
        )
    except orchestrations_repo.OrchestrationError as exc:
        return _repo_error_response(exc)
    write_audit(
        "event_orchestration.publish",
        object_type="event_orchestration_version",
        object_id=version.id,
        group_id=orchestration.group_id,
        data={"orchestration_id": orchestration.id, "version": version.version_number},
    )
    return jsonify(_serialize_version(version, include_definition=True))


@orchestrations_bp.route("/<int:orchestration_id>/rollback", methods=["POST"])
def rollback_orchestration(orchestration_id):
    orchestration, error = _require_permission(orchestration_id, PUBLISH)
    if error:
        return error
    payload, error = validate_body(OrchestrationRollbackSchema)
    if error:
        return error
    user = current_user()
    try:
        version = orchestrations_repo.rollback_to_version(
            orchestration.id,
            payload.version_id,
            actor_id=user.id,
            comment=payload.comment,
            confirm_catch_all_drop=payload.confirm_catch_all_drop,
        )
    except orchestrations_repo.OrchestrationError as exc:
        return _repo_error_response(exc)
    write_audit(
        "event_orchestration.rollback",
        object_type="event_orchestration_version",
        object_id=version.id,
        group_id=orchestration.group_id,
        data={"orchestration_id": orchestration.id, "source_version_id": payload.version_id},
    )
    return jsonify(_serialize_version(version, include_definition=True))


@orchestrations_bp.route("/<int:orchestration_id>/runtime", methods=["PATCH"])
def update_orchestration_runtime(orchestration_id):
    orchestration, error = _require_permission(orchestration_id, PUBLISH)
    if error:
        return error
    payload, error = validate_body(OrchestrationRuntimeSchema)
    if error:
        return error
    try:
        orchestration = orchestrations_repo.set_runtime_state(
            orchestration.id,
            enabled=payload.enabled,
            mode=payload.mode,
            compatibility_mode=payload.compatibility_mode,
        )
    except orchestrations_repo.OrchestrationError as exc:
        return _repo_error_response(exc)
    write_audit(
        "event_orchestration.runtime_update",
        object_type="event_orchestration",
        object_id=orchestration.id,
        group_id=orchestration.group_id,
        data={"mode": orchestration.mode, "compatibility_mode": orchestration.compatibility_mode},
    )
    return jsonify(_serialize_orchestration(orchestration, include_definition=True))


@orchestrations_bp.route("/<int:orchestration_id>/versions", methods=["GET"])
def list_orchestration_versions(orchestration_id):
    orchestration, error = _require_permission(orchestration_id, VIEW)
    if error:
        return error
    versions = orchestrations_repo.list_versions(orchestration.id)
    return jsonify({"items": [_serialize_version(item) for item in versions]})


@orchestrations_bp.route(
    "/<int:orchestration_id>/versions/<int:version_id>",
    methods=["GET"],
)
def get_orchestration_version(orchestration_id, version_id):
    orchestration, error = _require_permission(orchestration_id, VIEW)
    if error:
        return error
    try:
        version = orchestrations_repo.get_version(orchestration.id, version_id)
    except orchestrations_repo.OrchestrationError as exc:
        return _repo_error_response(exc)
    return jsonify(_serialize_version(version, include_definition=True))


def _simple_entity(item, *, team_id=None):
    return {
        "id": item.id,
        "name": getattr(item, "name", None) or getattr(item, "slug", None) or str(item.id),
        "team_id": team_id if team_id is not None else getattr(item, "team_id", None),
        "enabled": bool(getattr(item, "enabled", getattr(item, "active", True))),
    }


@orchestrations_bp.route("/catalog", methods=["GET"])
def orchestration_catalog():
    group_id = request.args.get("group_id", type=int)
    if group_id is None:
        return make_error_response("validation_error", "group_id is required", 400)
    user, error = _require_group_permission(group_id, VIEW)
    if error:
        return error
    group = Group.get_or_none(Group.id == group_id)
    if group is None:
        return make_error_response("group_not_found", "Group was not found.", 404)
    team_query = Team.select().where(
        (Team.group == group_id)
        & (Team.deleted == False)  # noqa: E712
        & Team.deleted_at.is_null(True)
    ).order_by(Team.name.asc())
    teams = list(team_query)
    team_ids = [team.id for team in teams]

    service_query = Service.select().where(
        (Service.group == group_id)
        & (Service.deleted == False)  # noqa: E712
        & Service.deleted_at.is_null(True)
    ).order_by(Service.name.asc())
    routes = []
    escalation = []
    notification = []
    priority = []
    if team_ids:
        routes = list(
            AlertRoute.select()
            .where(
                (AlertRoute.team.in_(team_ids))
                & (AlertRoute.deleted == False)  # noqa: E712
                & AlertRoute.deleted_at.is_null(True)
            )
            .order_by(AlertRoute.name.asc())
        )
        escalation = list(
            EscalationPolicy.select()
            .where(
                (EscalationPolicy.team.in_(team_ids))
                & (EscalationPolicy.deleted == False)  # noqa: E712
                & EscalationPolicy.deleted_at.is_null(True)
            )
            .order_by(EscalationPolicy.name.asc())
        )
        notification = list(
            NotificationPolicy.select()
            .where(
                (NotificationPolicy.team.in_(team_ids))
                & (NotificationPolicy.deleted == False)  # noqa: E712
                & NotificationPolicy.deleted_at.is_null(True)
            )
            .order_by(NotificationPolicy.name.asc())
        )
        priority = list(
            PriorityPolicy.select()
            .where(
                (PriorityPolicy.team.in_(team_ids))
                & (PriorityPolicy.deleted == False)  # noqa: E712
                & PriorityPolicy.deleted_at.is_null(True)
            )
            .order_by(PriorityPolicy.name.asc())
        )
    actions = list(
        OrchestrationWebhookAction.select()
        .where(
            (OrchestrationWebhookAction.group == group_id)
            & (OrchestrationWebhookAction.deleted == False)  # noqa: E712
            & OrchestrationWebhookAction.deleted_at.is_null(True)
        )
        .order_by(OrchestrationWebhookAction.name.asc())
    )
    return jsonify(
        {
            "group": {"id": group_id, "name": group.name if group else str(group_id)},
            "permissions": _permission_map(user, group_id),
            "teams": [_simple_entity(item) for item in teams],
            "services": [_simple_entity(item) for item in service_query],
            "routes": [_simple_entity(item) for item in routes],
            "escalation_policies": [_simple_entity(item) for item in escalation],
            "notification_policies": [_simple_entity(item) for item in notification],
            "priority_policies": [_simple_entity(item) for item in priority],
            "webhook_actions": [_serialize_webhook_action(item) for item in actions],
            "normalizer_sources": list(SUPPORTED_NORMALIZER_SOURCES),
        }
    )


@orchestrations_bp.route("/<int:orchestration_id>/simulate", methods=["POST"])
def simulate_orchestration(orchestration_id):
    orchestration, error = _require_permission(orchestration_id, SIMULATE)
    if error:
        return error
    payload, error = validate_body(OrchestrationSimulationSchema)
    if error:
        return error
    if payload.normalized_event is not None:
        event = simulator.prepare_normalized_event(payload.normalized_event)
        selected_normalizer = "normalized"
        normalized_event_count = 1
    else:
        selected_normalizer, event, normalized_event_count = (
            simulator.normalize_simulation_payload(
                source=payload.source,
                payload=payload.payload,
                headers=payload.headers,
                event_index=payload.event_index,
            )
        )
    result = simulator.simulate_event(
        orchestration.id,
        event,
        version_id=payload.version_id,
        compare_with_active=payload.compare_with_active,
        selected_normalizer=selected_normalizer,
        normalized_event_count=normalized_event_count,
    )
    write_audit(
        "event_orchestration.simulate",
        object_type="event_orchestration",
        object_id=orchestration.id,
        group_id=orchestration.group_id,
        data={
            "version_id": result.get("version_id"),
            "source": event.get("source"),
            "compare_with_active": payload.compare_with_active,
        },
    )
    return jsonify(result)


@orchestrations_bp.route("/<int:orchestration_id>/replay", methods=["POST"])
def replay_orchestration(orchestration_id):
    orchestration, error = _require_permission(orchestration_id, REPLAY)
    if error:
        return error
    payload, error = validate_body(OrchestrationReplaySchema)
    if error:
        return error
    result = simulator.replay_events(
        orchestration.id,
        alert_ids=payload.alert_ids,
        execution_ids=payload.execution_ids,
        version_id=payload.version_id,
        compare_with_active=payload.compare_with_active,
    )
    write_audit(
        "event_orchestration.replay",
        object_type="event_orchestration",
        object_id=orchestration.id,
        group_id=orchestration.group_id,
        data={
            "alert_ids": payload.alert_ids,
            "execution_ids": payload.execution_ids,
            "version_id": payload.version_id,
            "count": result.get("count"),
        },
    )
    return jsonify(result)


@orchestrations_bp.route("/<int:orchestration_id>/executions", methods=["GET"])
def list_orchestration_executions(orchestration_id):
    orchestration, error = _require_permission(orchestration_id, VIEW_EXECUTIONS)
    if error:
        return error
    limit = request.args.get("limit", default=50, type=int)
    include_trace = request.args.get("include_trace") == "1"
    return jsonify(
        simulator.list_executions(
            orchestration.id,
            limit=limit,
            include_trace=include_trace,
        )
    )


@orchestrations_bp.route("/<int:orchestration_id>/shadow-metrics", methods=["GET"])
def get_orchestration_shadow_metrics(orchestration_id):
    orchestration, error = _require_permission(orchestration_id, VIEW_EXECUTIONS)
    if error:
        return error
    limit = request.args.get("limit", default=None, type=int)
    return jsonify(simulator.shadow_metrics(orchestration.id, limit=limit))


def _get_webhook_action(action_id):
    return OrchestrationWebhookAction.get_or_none(
        (OrchestrationWebhookAction.id == action_id)
        & (OrchestrationWebhookAction.deleted == False)  # noqa: E712
        & OrchestrationWebhookAction.deleted_at.is_null(True)
    )


@orchestration_webhook_actions_bp.route("", methods=["GET"])
@orchestration_webhook_actions_bp.route("/", methods=["GET"])
def list_webhook_actions():
    group_id = request.args.get("group_id", type=int)
    if group_id is None:
        return make_error_response("validation_error", "group_id is required", 400)
    _, error = _require_group_permission(group_id, VIEW)
    if error:
        return error
    items = list(
        OrchestrationWebhookAction.select()
        .where(
            (OrchestrationWebhookAction.group == group_id)
            & (OrchestrationWebhookAction.deleted == False)  # noqa: E712
            & OrchestrationWebhookAction.deleted_at.is_null(True)
        )
        .order_by(OrchestrationWebhookAction.name.asc())
    )
    return jsonify({"items": [_serialize_webhook_action(item) for item in items]})


@orchestration_webhook_actions_bp.route("", methods=["POST"])
@orchestration_webhook_actions_bp.route("/", methods=["POST"])
def create_webhook_action():
    payload, error = validate_body(OrchestrationWebhookActionCreateSchema)
    if error:
        return error
    user, error = _require_group_permission(payload.group_id, MANAGE_ACTIONS)
    if error:
        return error
    try:
        action = webhooks.create_webhook_action(
            **payload.model_dump(),
            actor_id=user.id,
        )
    except IntegrityError:
        return make_error_response(
            "webhook_action_conflict",
            "A webhook action with this name already exists in the group.",
            409,
        )
    except (webhooks.WebhookValidationError, ValueError):
        return make_error_response(
            "webhook_action_invalid",
            "Webhook action configuration is invalid.",
            400,
        )
    write_audit(
        "event_orchestration.webhook_action_create",
        object_type="orchestration_webhook_action",
        object_id=action.id,
        group_id=action.group_id,
    )
    return jsonify(_serialize_webhook_action(action)), 201


@orchestration_webhook_actions_bp.route("/<int:action_id>", methods=["PATCH"])
def update_webhook_action(action_id):
    action = _get_webhook_action(action_id)
    if action is None:
        return make_error_response("webhook_action_not_found", "Webhook action was not found.", 404)
    _, error = _require_group_permission(action.group_id, MANAGE_ACTIONS)
    if error:
        return error
    payload, error = validate_body(OrchestrationWebhookActionUpdateSchema)
    if error:
        return error
    changes = payload.model_dump(exclude_unset=True)
    try:
        action = webhooks.update_webhook_action(action.id, **changes)
    except IntegrityError:
        return make_error_response(
            "webhook_action_conflict",
            "A webhook action with this name already exists in the group.",
            409,
        )
    except (webhooks.WebhookValidationError, ValueError):
        return make_error_response(
            "webhook_action_invalid",
            "Webhook action configuration is invalid.",
            400,
        )
    write_audit(
        "event_orchestration.webhook_action_update",
        object_type="orchestration_webhook_action",
        object_id=action.id,
        group_id=action.group_id,
        data={"fields": sorted(changes)},
    )
    return jsonify(_serialize_webhook_action(action))


@orchestration_webhook_actions_bp.route("/<int:action_id>", methods=["DELETE"])
def delete_webhook_action(action_id):
    action = _get_webhook_action(action_id)
    if action is None:
        return make_error_response("webhook_action_not_found", "Webhook action was not found.", 404)
    _, error = _require_group_permission(action.group_id, MANAGE_ACTIONS)
    if error:
        return error
    action.enabled = False
    action.deleted = True
    from app.modules.common import utc_now

    action.deleted_at = utc_now()
    action.save()
    write_audit(
        "event_orchestration.webhook_action_delete",
        object_type="orchestration_webhook_action",
        object_id=action.id,
        group_id=action.group_id,
    )
    return jsonify({"deleted": True, "id": action.id})


@orchestration_webhook_actions_bp.route("/<int:action_id>/executions", methods=["GET"])
def list_webhook_action_executions(action_id):
    action = _get_webhook_action(action_id)
    if action is None:
        return make_error_response("webhook_action_not_found", "Webhook action was not found.", 404)
    _, error = _require_group_permission(action.group_id, VIEW_EXECUTIONS)
    if error:
        return error
    limit = max(1, min(request.args.get("limit", default=50, type=int), 200))
    rows = list(
        AutomationExecution.select()
        .where(AutomationExecution.action == action.id)
        .order_by(AutomationExecution.created_at.desc())
        .limit(limit)
    )
    return jsonify(
        {
            "items": [
                {
                    "id": row.id,
                    "status": row.status,
                    "attempts": row.attempts,
                    "response_status": row.response_status,
                    "response_excerpt": row.response_excerpt_safe,
                    "error": row.error_safe,
                    "created_at": _iso(row.created_at),
                    "started_at": _iso(row.started_at),
                    "finished_at": _iso(row.finished_at),
                }
                for row in rows
            ]
        }
    )
