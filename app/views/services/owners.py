from flask import jsonify, request
from peewee import DoesNotExist, IntegrityError

from app.views.services.blueprint import services_bp
from app.api.schemas.services import ServiceOwnerCreateSchema, ServiceOwnerUpdateSchema
from app.modules.db import services_repo
from app.modules.db.common import integrity_conflict
from app.services.audit import write_audit
from app.services.rbac import require_team_write, current_user, require_team_read
from app.services.serializers.services import serialize_service_owner
from app.services.service_catalog.events import emit_service_catalog_event
from app.services.service_catalog.snapshots import service_owner_snapshot
from app.services.validation import validate_body, make_error_response


@services_bp.route("/<int:service_id>/owners", methods=["POST"])
def create_service_owner(service_id):
    """Create a service owner/default stakeholder."""
    service = services_repo.get_service(service_id)

    error = require_team_write(service.team_id)
    if error:
        return error

    payload, error = validate_body(ServiceOwnerCreateSchema)
    if error:
        return error

    try:
        owner, created = services_repo.create_service_owner(
            service_id,
            _service_owner_data_from_payload(payload),
        )
    except DoesNotExist:
        return make_error_response(
            "user_not_found",
            "User was not found",
            404,
            user_id=payload.user_id,
        )
    except IntegrityError:
        return integrity_conflict(
            "Service owner could not be saved because it conflicts with "
            "existing data"
        )

    write_audit(
        "service_owner.create" if created else "service_owner.update",
        object_type="service_owner",
        object_id=owner.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data=payload.model_dump(),
    )

    owner_snapshot = service_owner_snapshot(owner)
    emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service_owner.created" if created else "service_owner.updated",
        title="Default stakeholder added" if created else "Default stakeholder updated",
        summary=owner_snapshot.get("user_display_name") or owner_snapshot.get("user_email"),
        source_ref=f"service_owner:{owner.id}",
        actor_user=current_user(),
        payload={"owner": owner_snapshot},
        readiness_trigger="service_owner_created" if created else "service_owner_updated",
    )

    return (
        jsonify(serialize_service_owner(owner, current_user())),
        201 if created else 200,
    )


@services_bp.route("/<int:service_id>/owners/<int:owner_id>", methods=["PUT"],)
def update_service_owner(service_id, owner_id):
    """Update a service owner/default stakeholder."""
    service = services_repo.get_service(service_id)

    error = require_team_write(service.team_id)
    if error:
        return error

    owner_before = services_repo.get_service_owner_for_service(
        service_id,
        owner_id,
    )

    if not owner_before:
        return make_error_response(
            "service_owner_not_found",
            "Service owner was not found",
            404,
            owner_id=owner_id,
        )

    owner_snapshot_before = service_owner_snapshot(owner_before)

    payload, error = validate_body(ServiceOwnerUpdateSchema)
    if error:
        return error

    try:
        owner = services_repo.update_service_owner(
            owner_id,
            _service_owner_data_from_payload(payload),
        )
    except DoesNotExist:
        return make_error_response(
            "user_not_found",
            "User was not found",
            404,
            user_id=payload.user_id,
        )
    except IntegrityError:
        return integrity_conflict(
            "Service owner could not be saved because it conflicts with "
            "existing data"
        )

    write_audit(
        "service_owner.update",
        object_type="service_owner",
        object_id=owner.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data=payload.model_dump(),
    )

    owner_snapshot = service_owner_snapshot(owner)
    emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service_owner.updated",
        title="Default stakeholder updated",
        summary=owner_snapshot.get("user_display_name") or owner_snapshot.get("user_email"),
        source_ref=f"service_owner:{owner.id}",
        actor_user=current_user(),
        before=owner_snapshot_before,
        after=owner_snapshot,
        readiness_trigger="service_owner_updated",
    )

    return jsonify(serialize_service_owner(owner, current_user()))


@services_bp.route("/<int:service_id>/owners/<int:owner_id>", methods=["DELETE"],)
def delete_service_owner(service_id, owner_id):
    """Deactivate a service owner/default stakeholder."""
    service = services_repo.get_service(service_id)

    error = require_team_write(service.team_id)
    if error:
        return error

    owner_before = services_repo.get_service_owner_for_service(
        service_id,
        owner_id,
    )

    if not owner_before:
        return make_error_response(
            "service_owner_not_found",
            "Service owner was not found",
            404,
            owner_id=owner_id,
        )

    owner_snapshot_before = service_owner_snapshot(owner_before)
    owner = services_repo.deactivate_service_owner(owner_id)

    write_audit(
        "service_owner.delete",
        object_type="service_owner",
        object_id=owner.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data={"active": False},
    )

    owner_snapshot = service_owner_snapshot(owner)
    emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service_owner.deleted",
        title="Default stakeholder removed",
        summary=owner_snapshot_before.get("user_display_name") or owner_snapshot_before.get("user_email"),
        source_ref=f"service_owner:{owner.id}",
        actor_user=current_user(),
        before=owner_snapshot_before,
        after=owner_snapshot,
        readiness_trigger="service_owner_deleted",
    )

    return jsonify({"deleted": True, "id": owner.id})


def _service_owner_data_from_payload(payload):
    return {
        "user": payload.user_id,
        "role": payload.role,
        "active": payload.active,
        "notify_on_created": payload.notify_on_created,
        "notify_on_priority_change": payload.notify_on_priority_change,
        "notify_on_status_change": payload.notify_on_status_change,
        "notify_on_resolved": payload.notify_on_resolved,
        "notify_on_comment": payload.notify_on_comment,
    }


@services_bp.route("/<int:service_id>/owners", methods=["GET"])
def list_service_owners(service_id):
    """Return service owners/default stakeholders."""
    service = services_repo.get_service(service_id)

    error = require_team_read(service.team_id)
    if error:
        return error

    include_inactive = request.args.get("include_inactive") == "1"

    return jsonify([
        serialize_service_owner(owner, current_user())
        for owner in services_repo.list_service_owners(
            service_id,
            active_only=not include_inactive,
        )
    ])
