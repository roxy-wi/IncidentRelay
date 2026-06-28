from flask import jsonify
from peewee import DoesNotExist

from app.views.services.blueprint import services_bp
from app.api.schemas.services import ServiceDependencyCreateSchema, ServiceDependencyUpdateSchema
from app.modules.db import services_repo
from app.services.audit import write_audit
from app.services.rbac import require_team_read, current_user, require_team_write
from app.services.serializers import serialize_service_dependency
from app.services.service_catalog.events import (
    READINESS_SCOPE_DEPENDENCY_COMPONENT,
    READINESS_SCOPE_NONE,
    emit_service_catalog_event,
)
from app.services.service_catalog.snapshots import service_dependency_snapshot
from app.services.validation import make_error_response, validate_body
from app.views.services.links import _readable_services_from_request


def _validate_dependency_service(service, depends_on_service_id):
    """Validate dependency target.

    Cross-team dependencies are allowed.
    User must be able to edit source service and read target service.
    """
    if service.id == depends_on_service_id:
        return make_error_response(
            "dependency_self_reference",
            "Service cannot depend on itself",
            400,
            service_id=service.id,
        )

    try:
        depends_on = services_repo.get_service(depends_on_service_id)
    except DoesNotExist:
        return make_error_response(
            "dependency_service_not_found",
            "Dependency service was not found",
            400,
            depends_on_service_id=depends_on_service_id,
        )

    if not depends_on.enabled:
        return make_error_response(
            "dependency_service_disabled",
            "Dependency service is disabled",
            400,
            depends_on_service_id=depends_on.id,
        )

    error = require_team_read(depends_on.team_id)
    if error:
        return error

    return None


def _dependency_service_label(snapshot, *, target=True):
    name_key = "depends_on_service_name" if target else "service_name"
    slug_key = "depends_on_service_slug" if target else "service_slug"

    return snapshot.get(name_key) or snapshot.get(slug_key) or "service"


def _dependency_summary(snapshot):
    return "Depends on " + _dependency_service_label(snapshot, target=True)


def _downstream_dependency_summary(snapshot):
    return _dependency_service_label(snapshot, target=False) + " depends on this service"


@services_bp.route("/<int:service_id>/dependencies", methods=["GET"])
def list_service_dependencies(service_id):
    """Return service dependencies."""
    service = services_repo.get_service(service_id)

    error = require_team_read(service.team_id)
    if error:
        return error

    return jsonify([
        serialize_service_dependency(dependency, current_user())
        for dependency in services_repo.list_service_dependencies(service_id)
    ])


@services_bp.route("/<int:service_id>/dependencies", methods=["POST"])
def create_service_dependency(service_id):
    """Create a service dependency."""
    service = services_repo.get_service(service_id)

    error = require_team_write(service.team_id)
    if error:
        return error

    payload, error = validate_body(ServiceDependencyCreateSchema)
    if error:
        return error

    validation_error = _validate_dependency_service(
        service,
        payload.depends_on_service_id,
    )
    if validation_error:
        return validation_error

    dependency = services_repo.create_service_dependency(
        service_id,
        {
            "depends_on_service": payload.depends_on_service_id,
            "dependency_type": payload.dependency_type,
            "criticality": payload.criticality,
            "description": payload.description,
            "enabled": payload.enabled,
        },
    )

    write_audit(
        "service_dependency.create",
        object_type="service_dependency",
        object_id=dependency.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data=payload.model_dump(),
    )

    actor_user = current_user()
    dependency_snapshot = service_dependency_snapshot(dependency)
    emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service_dependency.created",
        title="Service dependency created",
        summary=_dependency_summary(dependency_snapshot),
        source_ref=f"service_dependency:{dependency.id}",
        actor_user=actor_user,
        payload={"dependency": dependency_snapshot},
        readiness_scope=READINESS_SCOPE_DEPENDENCY_COMPONENT,
        readiness_trigger="service_dependency_created",
        affected_service_ids=[dependency.depends_on_service_id],
    )
    emit_service_catalog_event(
        dependency.depends_on_service,
        category="configuration",
        event_type="service_dependency.downstream_created",
        title="Downstream dependency created",
        summary=_downstream_dependency_summary(dependency_snapshot),
        source_ref=f"service_dependency:{dependency.id}",
        actor_user=actor_user,
        payload={"dependency": dependency_snapshot},
        readiness_scope=READINESS_SCOPE_NONE,
    )

    return jsonify(serialize_service_dependency(dependency, current_user())), 201


@services_bp.route("/dependencies/<int:dependency_id>", methods=["PUT"])
def update_service_dependency(dependency_id):
    """Update a service dependency."""
    dependency_before = services_repo.get_service_dependency(dependency_id)
    service = dependency_before.service
    old_depends_on_service_id = dependency_before.depends_on_service_id

    error = require_team_write(service.team_id)
    if error:
        return error

    dependency_snapshot_before = service_dependency_snapshot(dependency_before)
    old_depends_on_service = dependency_before.depends_on_service

    payload, error = validate_body(ServiceDependencyUpdateSchema)
    if error:
        return error

    validation_error = _validate_dependency_service(
        service,
        payload.depends_on_service_id,
    )
    if validation_error:
        return validation_error

    dependency = services_repo.update_service_dependency(
        dependency_id,
        {
            "depends_on_service": payload.depends_on_service_id,
            "dependency_type": payload.dependency_type,
            "criticality": payload.criticality,
            "description": payload.description,
            "enabled": payload.enabled,
        },
    )

    write_audit(
        "service_dependency.update",
        object_type="service_dependency",
        object_id=dependency.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data=payload.model_dump(),
    )

    actor_user = current_user()
    dependency_snapshot = service_dependency_snapshot(dependency)
    emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service_dependency.updated",
        title="Service dependency updated",
        summary=_dependency_summary(dependency_snapshot),
        source_ref=f"service_dependency:{dependency.id}",
        actor_user=actor_user,
        before=dependency_snapshot_before,
        after=dependency_snapshot,
        readiness_scope=READINESS_SCOPE_DEPENDENCY_COMPONENT,
        readiness_trigger="service_dependency_updated",
        affected_service_ids=[
            old_depends_on_service_id,
            dependency.depends_on_service_id,
        ],
    )

    if old_depends_on_service_id != dependency.depends_on_service_id:
        emit_service_catalog_event(
            old_depends_on_service,
            category="configuration",
            event_type="service_dependency.downstream_deleted",
            title="Downstream dependency removed",
            summary=_downstream_dependency_summary(dependency_snapshot_before),
            source_ref=f"service_dependency:{dependency.id}",
            actor_user=actor_user,
            before=dependency_snapshot_before,
            readiness_scope=READINESS_SCOPE_NONE,
        )
        emit_service_catalog_event(
            dependency.depends_on_service,
            category="configuration",
            event_type="service_dependency.downstream_created",
            title="Downstream dependency created",
            summary=_downstream_dependency_summary(dependency_snapshot),
            source_ref=f"service_dependency:{dependency.id}",
            actor_user=actor_user,
            payload={"dependency": dependency_snapshot},
            readiness_scope=READINESS_SCOPE_NONE,
        )
    else:
        emit_service_catalog_event(
            dependency.depends_on_service,
            category="configuration",
            event_type="service_dependency.downstream_updated",
            title="Downstream dependency updated",
            summary=_downstream_dependency_summary(dependency_snapshot),
            source_ref=f"service_dependency:{dependency.id}",
            actor_user=actor_user,
            before=dependency_snapshot_before,
            after=dependency_snapshot,
            readiness_scope=READINESS_SCOPE_NONE,
        )

    return jsonify(serialize_service_dependency(dependency, current_user()))


@services_bp.route("/dependencies/<int:dependency_id>", methods=["DELETE"])
def delete_service_dependency(dependency_id):
    """Delete a service dependency."""
    dependency_before = services_repo.get_service_dependency(dependency_id)
    service = dependency_before.service
    depends_on_service_id = dependency_before.depends_on_service_id

    error = require_team_write(service.team_id)
    if error:
        return error

    dependency_snapshot_before = service_dependency_snapshot(dependency_before)
    depends_on_service = dependency_before.depends_on_service
    dependency = services_repo.soft_delete_service_dependency(dependency_id)

    write_audit(
        "service_dependency.delete",
        object_type="service_dependency",
        object_id=dependency.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data={"deleted": True},
    )

    actor_user = current_user()
    dependency_snapshot = service_dependency_snapshot(dependency)
    emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service_dependency.deleted",
        title="Service dependency deleted",
        summary=_dependency_summary(dependency_snapshot_before),
        source_ref=f"service_dependency:{dependency.id}",
        actor_user=actor_user,
        before=dependency_snapshot_before,
        after=dependency_snapshot,
        readiness_scope=READINESS_SCOPE_DEPENDENCY_COMPONENT,
        readiness_trigger="service_dependency_deleted",
        affected_service_ids=[depends_on_service_id],
    )
    emit_service_catalog_event(
        depends_on_service,
        category="configuration",
        event_type="service_dependency.downstream_deleted",
        title="Downstream dependency removed",
        summary=_downstream_dependency_summary(dependency_snapshot_before),
        source_ref=f"service_dependency:{dependency.id}",
        actor_user=actor_user,
        before=dependency_snapshot_before,
        readiness_scope=READINESS_SCOPE_NONE,
    )

    return jsonify({"deleted": True, "id": dependency.id})


@services_bp.route("/dependencies", methods=["GET"])
def list_all_service_dependencies():
    """Return dependencies for all readable services in current scope."""
    services, error = _readable_services_from_request()
    if error:
        return error

    service_ids = [service.id for service in services]

    return jsonify([
        serialize_service_dependency(dependency, current_user())
        for dependency in services_repo.list_service_dependencies(service_ids=service_ids)
    ])
