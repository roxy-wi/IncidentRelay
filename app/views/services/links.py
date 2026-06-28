from flask import jsonify, request
from peewee import DoesNotExist

from app.views.services.blueprint import services_bp
from app.api.schemas.services import ServiceLinkCreateSchema, ServiceLinkUpdateSchema
from app.modules.db import services_repo
from app.services.audit import write_audit
from app.services.rbac import require_team_read, get_allowed_team_ids, current_user, require_team_write
from app.services.serializers import serialize_service_link
from app.services.service_catalog.events import emit_service_catalog_event
from app.services.service_catalog.snapshots import service_link_snapshot
from app.services.validation import validate_body


def _json_error(error, message, status=400, **extra):
    payload = {"error": error, "message": message}
    payload.update(extra)
    return jsonify(payload), status


def _readable_services_from_request(*, include_disabled=True):
    """
    Return services visible to the current user for aggregate
    service context endpoints.
    """
    team_id = request.args.get(
        "team_id",
        type=int,
    )
    service_id = request.args.get(
        "service_id",
        type=int,
    )

    if service_id:
        try:
            service = services_repo.get_service(
                service_id
            )
        except DoesNotExist:
            return None, _json_error(
                "service_not_found",
                "Service was not found",
                404,
                service_id=service_id,
            )

        if (
            not include_disabled
            and not services_repo.is_service_active(
                service
            )
        ):
            return None, _json_error(
                "service_not_found",
                "Service was not found",
                404,
                service_id=service_id,
            )

        error = require_team_read(
            service.team_id
        )
        if error:
            return None, error

        return [service], None

    if team_id:
        error = require_team_read(team_id)
        if error:
            return None, error

        return (
            services_repo.list_services(
                team_id=team_id,
                include_disabled=include_disabled,
            ),
            None,
        )

    allowed_team_ids = get_allowed_team_ids(
        active_only=True,
    )

    return (
        services_repo.list_services(
            team_ids=allowed_team_ids,
            include_disabled=include_disabled,
        ),
        None,
    )


@services_bp.route("/<int:service_id>/links", methods=["GET"])
def list_service_links(service_id):
    """Return service links."""
    service = services_repo.get_service(service_id)

    error = require_team_read(service.team_id)
    if error:
        return error

    return jsonify([
        serialize_service_link(link, current_user())
        for link in services_repo.list_service_links(service_id)
    ])


@services_bp.route("/<int:service_id>/links", methods=["POST"])
def create_service_link(service_id):
    """Create a service link."""
    service = services_repo.get_service(service_id)

    error = require_team_write(service.team_id)
    if error:
        return error

    payload, error = validate_body(ServiceLinkCreateSchema)
    if error:
        return error

    link = services_repo.create_service_link(
        service_id,
        payload.model_dump(),
    )

    write_audit(
        "service_link.create",
        object_type="service_link",
        object_id=link.id,
        group_id=service.group_id,
        team_id=service.team_id,
        data=payload.model_dump(),
    )

    link_snapshot = service_link_snapshot(link)
    emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service_link.created",
        title="Service link created",
        summary=link.label or link.url,
        source_ref=f"service_link:{link.id}",
        external_url=link.url,
        actor_user=current_user(),
        payload={"link": link_snapshot},
        readiness_trigger="service_link_created",
    )

    return jsonify(serialize_service_link(link, current_user())), 201


@services_bp.route("/links/<int:link_id>", methods=["PUT"])
def update_service_link(link_id):
    """Update a service link."""
    link_before = services_repo.get_service_link(link_id)
    service = link_before.service

    error = require_team_write(link_before.service.team_id)
    if error:
        return error

    link_snapshot_before = service_link_snapshot(link_before)

    payload, error = validate_body(ServiceLinkUpdateSchema)
    if error:
        return error

    link = services_repo.update_service_link(
        link_id,
        payload.model_dump(),
    )

    write_audit(
        "service_link.update",
        object_type="service_link",
        object_id=link.id,
        group_id=link.service.group_id,
        team_id=link.service.team_id,
        data=payload.model_dump(),
    )

    link_snapshot = service_link_snapshot(link)
    emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service_link.updated",
        title="Service link updated",
        summary=link.label or link.url,
        source_ref=f"service_link:{link.id}",
        external_url=link.url,
        actor_user=current_user(),
        before=link_snapshot_before,
        after=link_snapshot,
        readiness_trigger="service_link_updated",
    )

    return jsonify(serialize_service_link(link, current_user()))


@services_bp.route("/links/<int:link_id>", methods=["DELETE"])
def delete_service_link(link_id):
    """Delete a service link."""
    link_before = services_repo.get_service_link(link_id)
    service = link_before.service

    error = require_team_write(link_before.service.team_id)
    if error:
        return error

    link_snapshot_before = service_link_snapshot(link_before)
    link = services_repo.soft_delete_service_link(link_id)

    write_audit(
        "service_link.delete",
        object_type="service_link",
        object_id=link.id,
        group_id=link.service.group_id,
        team_id=link.service.team_id,
        data={"deleted": True},
    )

    link_snapshot = service_link_snapshot(link)
    emit_service_catalog_event(
        service,
        category="configuration",
        event_type="service_link.deleted",
        title="Service link deleted",
        summary=link_snapshot_before.get("label") or link_snapshot_before.get("url"),
        source_ref=f"service_link:{link.id}",
        external_url=link_snapshot_before.get("url"),
        actor_user=current_user(),
        before=link_snapshot_before,
        after=link_snapshot,
        readiness_trigger="service_link_deleted",
    )

    return jsonify({"deleted": True, "id": link.id})


@services_bp.route("/links", methods=["GET"])
def list_all_service_links():
    """Return links for all readable services in current scope."""
    services, error = _readable_services_from_request()
    if error:
        return error

    service_ids = [service.id for service in services]

    return jsonify([
        serialize_service_link(link, current_user())
        for link in services_repo.list_service_links(service_ids=service_ids)
    ])
