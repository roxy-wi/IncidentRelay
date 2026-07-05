from flask import request, jsonify
from peewee import IntegrityError, DoesNotExist

from app.views.services.blueprint import services_bp
from app.api.schemas.services import ServiceCreateSchema, ServiceUpdateSchema
from app.modules.db import services_repo, rotations_repo, escalation_policies_repo
from app.modules.db.common import unique_field_conflict, integrity_conflict
from app.services.audit import write_audit
from app.services.incidents.priority_policies import service as priority_policy_service
from app.services.notifications.policies import service as notification_policy_service
from app.services.rbac import require_team_read, get_allowed_team_ids, current_user, require_team_write
from app.services.serializers.services import serialize_service
from app.services.service_catalog import readiness as service_readiness
from app.services.service_catalog.events import (
    READINESS_SCOPE_NONE,
    READINESS_SCOPE_SERVICE,
    emit_service_catalog_event,
)
from app.services.validation import validate_body, make_error_response

SERVICE_TIMELINE_CONFIGURATION_FIELDS = (
    "name",
    "slug",
    "description",
    "service_type",
    "environment",
    "criticality",
    "tier",
    "kind",
    "lifecycle",
    "team_id",
    "group_id",
    "default_rotation_id",
    "default_escalation_policy_id",
    "notification_policy_id",
    "priority_policy_id",
    "labels",
    "tags",
    "metadata",
    "enabled",
    "public",
    "public_name",
    "public_description",
    "public_order",
)


def _service_timeline_snapshot(service):
    return {field: getattr(service, field, None) for field in SERVICE_TIMELINE_CONFIGURATION_FIELDS}


def _service_status_snapshot(service):
    return {
        "status": service.status,
        "source": service.status_source,
        "message": service.status_message,
    }


def _service_changed_values(before, after):
    changes = {}

    for field, old_value in before.items():
        new_value = after.get(field)

        if old_value != new_value:
            changes[field] = {
                "old": old_value,
                "new": new_value,
            }

    return changes


def _emit_service_update_events(service, *, configuration_before, status_before, actor_user):
    configuration_after = _service_timeline_snapshot(service)
    status_after = _service_status_snapshot(service)
    configuration_changes = _service_changed_values(configuration_before, configuration_after)
    status_changes = _service_changed_values(status_before, status_after)
    readiness_result = None

    if configuration_changes:
        result = emit_service_catalog_event(
            service,
            category="configuration",
            event_type="service.updated",
            title="Service configuration updated",
            actor_user=actor_user,
            payload={"changes": configuration_changes},
            readiness_scope=READINESS_SCOPE_SERVICE,
            readiness_trigger="service_updated",
        )
        readiness_result = result.readiness_results[0] if result.readiness_results else None

    readiness_scope = READINESS_SCOPE_NONE if readiness_result else READINESS_SCOPE_SERVICE

    if status_before["status"] != status_after["status"]:
        result = emit_service_catalog_event(
            service,
            category="status",
            event_type="service.status_changed",
            title=f'Service status changed from {status_before["status"]} to {status_after["status"]}',
            summary=status_after["message"],
            source=status_after["source"] or "manual",
            actor_user=actor_user,
            status=status_after["status"],
            payload={
                "old_status": status_before["status"],
                "new_status": status_after["status"],
                "old_source": status_before["source"],
                "new_source": status_after["source"],
                "old_message": status_before["message"],
                "new_message": status_after["message"],
            },
            readiness_scope=readiness_scope,
            readiness_trigger="service_updated",
        )

        if not readiness_result and result.readiness_results:
            readiness_result = result.readiness_results[0]

    elif status_changes:
        result = emit_service_catalog_event(
            service,
            category="status",
            event_type="service.status_updated",
            title=f'Service status details updated for {status_after["status"]}',
            summary=status_after["message"],
            source=status_after["source"] or "manual",
            actor_user=actor_user,
            status=status_after["status"],
            payload={"changes": status_changes},
            readiness_scope=readiness_scope,
            readiness_trigger="service_updated",
        )

        if not readiness_result and result.readiness_results:
            readiness_result = result.readiness_results[0]

    return readiness_result


def _service_data_from_payload(payload):
    return {
        "team": payload.team_id,
        "slug": payload.slug,
        "name": payload.name,
        "description": payload.description,
        "service_type": payload.service_type,
        "environment": payload.environment,
        "criticality": payload.criticality,
        "tier": payload.tier,
        "status": payload.status,
        "status_source": payload.status_source,
        "status_message": payload.status_message,
        "default_rotation": payload.default_rotation_id,
        "default_escalation_policy": payload.default_escalation_policy_id,
        "notification_policy": payload.notification_policy_id,
        "priority_policy": payload.priority_policy_id,
        "labels": payload.labels,
        "tags": payload.tags,
        "metadata": payload.metadata,
        "enabled": payload.enabled,
        "public": payload.public,
        "public_name": payload.public_name,
        "public_description": payload.public_description,
        "public_order": payload.public_order,
        "kind": payload.kind,
        "lifecycle": payload.lifecycle,
    }


@services_bp.route("", methods=["GET"])
def list_services():
    """Return services visible to current user."""

    team_id = request.args.get("team_id", type=int)

    if team_id:
        error = require_team_read(team_id)

        if error:
            return error

        services = services_repo.list_services(team_id=team_id)
    else:
        services = services_repo.list_services(
            team_ids=get_allowed_team_ids()
        )

    readiness_states = service_readiness.list_service_readiness_states(
        [service.id for service in services]
    )

    return jsonify([
        serialize_service(
            service,
            current_user(),
            readiness_state=readiness_states.get(service.id),
        )
        for service in services
    ])


@services_bp.route("/<int:service_id>", methods=["GET"])
def get_service(service_id):
    """Return one service."""
    service = services_repo.get_service(service_id)

    error = require_team_read(service.team_id)
    if error:
        return error

    readiness_state = service_readiness.get_service_readiness_state(service.id)

    return jsonify(
        serialize_service(
            service,
            current_user(),
            readiness_state=readiness_state,
        )
    )


@services_bp.route("", methods=["POST"])
def create_service():
    """Create a service."""
    payload, error = validate_body(ServiceCreateSchema)
    if error:
        return error

    error = require_team_write(payload.team_id)
    if error:
        return error

    validation_error = _validate_service_payload(payload)
    if validation_error:
        return validation_error

    try:
        service = services_repo.create_service(_service_data_from_payload(payload))
    except IntegrityError as exc:
        error_text = str(exc).lower()
        if "slug" in error_text:
            return unique_field_conflict(
                "slug",
                payload.slug,
                "Service with this slug already exists in this team",
            )
        return integrity_conflict(
            "Service could not be saved because it conflicts with existing data"
        )

    write_audit(
        "service.create",
        object_type="service",
        object_id=service.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data=payload.model_dump(),
    )

    event_result = emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service.created",
        title="Service created",
        actor_user=current_user(),
        payload={
            "configuration": _service_timeline_snapshot(service),
            "status": _service_status_snapshot(service),
        },
        readiness_scope=READINESS_SCOPE_SERVICE,
        readiness_trigger="service_created",
    )
    readiness_state = event_result.readiness_results[0]["state"]

    return jsonify(
        serialize_service(
            service,
            current_user(),
            readiness_state=readiness_state,
        )
    ), 201


@services_bp.route("/<int:service_id>", methods=["PUT"])
def update_service(service_id):
    """Update a service."""
    service_before = services_repo.get_service(service_id)
    configuration_before = _service_timeline_snapshot(service_before)
    status_before = _service_status_snapshot(service_before)
    error = require_team_write(service_before.team_id)
    if error:
        return error

    payload, error = validate_body(ServiceUpdateSchema)
    if error:
        return error

    error = require_team_write(payload.team_id)
    if error:
        return error

    validation_error = _validate_service_payload(payload)
    if validation_error:
        return validation_error

    try:
        service = services_repo.update_service(
            service_id,
            _service_data_from_payload(payload),
        )
    except IntegrityError as exc:
        error_text = str(exc).lower()
        if "slug" in error_text:
            return unique_field_conflict(
                "slug",
                payload.slug,
                "Service with this slug already exists in this team",
            )
        return integrity_conflict(
            "Service could not be saved because it conflicts with existing data"
        )

    write_audit(
        "service.update",
        object_type="service",
        object_id=service.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data=payload.model_dump(),
    )

    readiness_result = _emit_service_update_events(
        service,
        configuration_before=configuration_before,
        status_before=status_before,
        actor_user=current_user(),
    )
    readiness_state = (
        readiness_result["state"]
        if readiness_result
        else service_readiness.get_service_readiness_state(service.id)
    )

    return jsonify(
        serialize_service(
            service,
            current_user(),
            readiness_state=readiness_state,
        )
    )


@services_bp.route("/<int:service_id>", methods=["DELETE"])
def delete_service(service_id):
    """Soft-delete a service."""
    service_before = services_repo.get_service(service_id)

    error = require_team_write(service_before.team_id)
    if error:
        return error

    actor_user = current_user()
    service = services_repo.soft_delete_service(service_id)

    write_audit(
        "service.delete",
        object_type="service",
        object_id=service.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data={"deleted": True},
    )

    emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service.deleted",
        title="Service deleted",
        actor_user=actor_user,
        payload={"enabled": service.enabled, "deleted": service.deleted},
        readiness_scope=READINESS_SCOPE_NONE,
    )

    return jsonify({"deleted": True, "id": service.id})


def _validate_rotation(team_id, rotation_id):
    if not rotation_id:
        return None

    try:
        rotation = rotations_repo.get_rotation(rotation_id)
    except DoesNotExist:
        return make_error_response(
            "rotation_not_found",
            "Default rotation was not found",
            400,
            rotation_id=rotation_id,
        )

    if rotation.team_id != team_id:
        return make_error_response(
            "rotation_team_mismatch",
            "Default rotation does not belong to service team",
            400,
            rotation_id=rotation_id,
            rotation_team_id=rotation.team_id,
            team_id=team_id,
        )

    return None


def _validate_escalation_policy(team_id, policy_id):
    if not policy_id:
        return None

    try:
        policy = escalation_policies_repo.get_policy(policy_id)
    except DoesNotExist:
        return make_error_response(
            "escalation_policy_not_found",
            "Default escalation policy was not found",
            400,
            escalation_policy_id=policy_id,
        )

    if policy.team_id != team_id:
        return make_error_response(
            "escalation_policy_team_mismatch",
            "Default escalation policy does not belong to service team",
            400,
            escalation_policy_id=policy_id,
            policy_team_id=policy.team_id,
            team_id=team_id,
        )

    return None


def _validate_notification_policy(team_id, policy_id):
    if not policy_id:
        return None

    try:
        policy = notification_policy_service.get_policy(policy_id)
    except notification_policy_service.NotificationPolicyNotFoundError:
        return make_error_response(
            "notification_policy_not_found",
            "Notification policy was not found",
            400,
            notification_policy_id=policy_id,
        )

    if policy.team_id != team_id:
        return make_error_response(
            "notification_policy_team_mismatch",
            "Notification policy does not belong to service team",
            400,
            notification_policy_id=policy_id,
            policy_team_id=policy.team_id,
            team_id=team_id,
        )

    if not policy.enabled:
        return make_error_response(
            "notification_policy_disabled",
            "Notification policy is disabled",
            400,
            notification_policy_id=policy_id,
        )

    return None


def _validate_priority_policy(team_id, policy_id):
    if not policy_id:
        return None

    try:
        policy = priority_policy_service.get_policy(policy_id)
    except priority_policy_service.PriorityPolicyNotFoundError:
        return make_error_response(
            "priority_policy_not_found",
            "Priority policy was not found",
            400,
            priority_policy_id=policy_id,
        )

    if policy.team_id != team_id:
        return make_error_response(
            "priority_policy_team_mismatch",
            "Priority policy does not belong to service team",
            400,
            priority_policy_id=policy_id,
            policy_team_id=policy.team_id,
            team_id=team_id,
        )

    if not policy.enabled:
        return make_error_response(
            "priority_policy_disabled",
            "Priority policy is disabled",
            400,
            priority_policy_id=policy_id,
        )

    return None


def _validate_service_payload(payload):
    rotation_error = _validate_rotation(payload.team_id, payload.default_rotation_id)
    if rotation_error:
        return rotation_error

    policy_error = _validate_escalation_policy(
        payload.team_id,
        payload.default_escalation_policy_id,
    )
    if policy_error:
        return policy_error

    notification_policy_error = _validate_notification_policy(
        payload.team_id,
        payload.notification_policy_id,
    )

    if notification_policy_error:
        return notification_policy_error

    priority_policy_error = _validate_priority_policy(
        payload.team_id,
        payload.priority_policy_id,
    )

    if priority_policy_error:
        return priority_policy_error

    return None
