from flask import jsonify, request
from peewee import DoesNotExist, IntegrityError

from app.api.schemas.services import (
    ServiceStandardCheckCreateSchema,
    ServiceStandardCheckUpdateSchema,
    ServiceStandardCreateSchema,
    ServiceStandardPresetApplySchema,
    ServiceStandardUpdateSchema,
)
from app.modules.db.common import unique_field_conflict
from app.modules.db.models import Group
from app.services.audit import write_audit
from app.services.rbac import (
    current_user,
    get_allowed_group_ids,
    require_group_read,
    require_group_write,
)
from app.services.serializers import (
    serialize_service_standard,
    serialize_service_standard_check,
)
from app.services.service_catalog import standards as service_standards
from app.services.service_catalog.events import emit_group_service_catalog_event
from app.services.service_catalog.presets import ensure_basic_operational_standard
from app.services.service_catalog.snapshots import (
    service_standard_check_snapshot,
    service_standard_snapshot,
)
from app.services.validation import make_error_response, validate_body
from app.views.services.blueprint import services_bp


def _standard_data_from_payload(payload):
    return {
        "slug": payload.slug,
        "name": payload.name,
        "description": payload.description,
        "applies_to": payload.applies_to,
        "enabled": payload.enabled,
    }


def _standard_check_data_from_payload(payload):
    return {
        "slug": payload.slug,
        "name": payload.name,
        "description": payload.description,
        "check_type": payload.check_type,
        "configuration": payload.configuration,
        "weight": payload.weight,
        "severity": payload.severity,
        "required": payload.required,
        "enabled": payload.enabled,
        "position": payload.position,
    }


def _serialize_standard_with_checks(standard, include_disabled=False):
    checks = service_standards.list_standard_checks(
        standard.id,
        include_disabled=include_disabled,
    )

    return serialize_service_standard(
        standard,
        current_user(),
        checks=checks,
    )


def _get_accessible_standard(standard_id, write_required=False):
    try:
        standard = service_standards.get_service_standard(standard_id)
    except DoesNotExist:
        return None, make_error_response(
            "service_standard_not_found",
            "Service standard was not found",
            404,
            standard_id=standard_id,
        )

    if write_required:
        error = require_group_write(standard.group_id)
    else:
        error = require_group_read(standard.group_id)

    if error:
        return None, error

    return standard, None


def _get_accessible_standard_check(standard, check_id):
    try:
        check = service_standards.get_standard_check(standard.id, check_id)
    except DoesNotExist:
        return None, make_error_response(
            "service_standard_check_not_found",
            "Service standard check was not found",
            404,
            standard_id=standard.id,
            check_id=check_id,
        )

    return check, None


def _standard_validation_error(exc):
    return make_error_response(
        "service_standard_invalid",
        str(exc),
        400,
    )


def _standard_check_validation_error(exc):
    return make_error_response(
        "service_standard_check_invalid",
        str(exc),
        400,
    )


def _emit_standard_group_event(
    group_id,
    *,
    event_type,
    title,
    actor_user,
    payload=None,
    before=None,
    after=None,
    readiness_trigger=None,
):
    return emit_group_service_catalog_event(
        group_id,
        category="readiness",
        event_type=event_type,
        title=title,
        actor_user=actor_user,
        payload=payload,
        before=before,
        after=after,
        readiness_trigger=readiness_trigger or event_type,
    )


@services_bp.route("/standards", methods=["GET"])
def list_service_standards():
    """Return service standards visible to the current principal."""

    group_id = request.args.get("group_id", type=int)
    include_disabled = request.args.get("include_disabled") == "1"

    if group_id:
        error = require_group_read(group_id)

        if error:
            return error

        group_ids = [group_id]
    else:
        group_ids = get_allowed_group_ids(use_active_group=False)

    standards = service_standards.list_service_standards(
        group_ids,
        include_disabled=include_disabled,
    )

    return jsonify([
        _serialize_standard_with_checks(
            standard,
            include_disabled=include_disabled,
        )
        for standard in standards
    ])


@services_bp.route("/standards/presets/basic-operational", methods=["POST"])
def apply_basic_operational_standard():
    """Create or restore the built-in basic operational readiness standard."""

    payload, error = validate_body(ServiceStandardPresetApplySchema)

    if error:
        return error

    error = require_group_write(payload.group_id)

    if error:
        return error

    try:
        group = Group.get_by_id(payload.group_id)
    except DoesNotExist:
        return make_error_response(
            "group_not_found",
            "Group was not found",
            404,
            group_id=payload.group_id,
        )

    actor_user = current_user()
    result = ensure_basic_operational_standard(group, actor_user=actor_user)
    standard = result["standard"]
    created_checks = result["created_checks"]

    write_audit(
        "service_standard_preset.apply",
        object_type="service_standard",
        object_id=standard.id,
        group_id=group.id,
        data={
            "preset": "basic-operational",
            "standard_created": result["standard_created"],
            "created_check_ids": [check.id for check in created_checks],
        },
    )

    _emit_standard_group_event(
        group.id,
        event_type="service_standard_preset.applied",
        title="Basic service standard applied",
        actor_user=actor_user,
        payload={
            "preset": "basic-operational",
            "standard_created": result["standard_created"],
            "standard": service_standard_snapshot(standard),
            "created_checks": [
                service_standard_check_snapshot(check)
                for check in created_checks
            ],
        },
        readiness_trigger="standard_preset_applied",
    )

    return jsonify(_serialize_standard_with_checks(standard, include_disabled=True))


@services_bp.route("/standards/<int:standard_id>", methods=["GET"])
def get_service_standard(standard_id):
    """Return one service standard."""

    standard, error = _get_accessible_standard(standard_id)

    if error:
        return error

    include_disabled = request.args.get("include_disabled") == "1"

    return jsonify(
        _serialize_standard_with_checks(
            standard,
            include_disabled=include_disabled,
        )
    )


@services_bp.route("/standards", methods=["POST"])
def create_service_standard():
    """Create a service standard."""

    payload, error = validate_body(ServiceStandardCreateSchema)

    if error:
        return error

    error = require_group_write(payload.group_id)

    if error:
        return error

    data = _standard_data_from_payload(payload)
    data["group"] = payload.group_id
    actor_user = current_user()

    try:
        standard = service_standards.create_service_standard(
            data,
            actor_user=actor_user,
        )
    except service_standards.ServiceStandardValidationError as exc:
        return _standard_validation_error(exc)
    except IntegrityError:
        return unique_field_conflict(
            "slug",
            payload.slug,
            "Service standard with this slug already exists in this group",
        )

    write_audit(
        "service_standard.create",
        object_type="service_standard",
        object_id=standard.id,
        group_id=standard.group_id,
        data=payload.model_dump(),
    )

    _emit_standard_group_event(
        standard.group_id,
        event_type="service_standard.created",
        title="Service standard created",
        actor_user=actor_user,
        payload={"standard": service_standard_snapshot(standard)},
        readiness_trigger="standard_created",
    )

    return jsonify(_serialize_standard_with_checks(standard)), 201


@services_bp.route("/standards/<int:standard_id>", methods=["PUT"])
def update_service_standard(standard_id):
    """Update a service standard."""

    standard, error = _get_accessible_standard(standard_id, write_required=True)

    if error:
        return error

    payload, error = validate_body(ServiceStandardUpdateSchema)

    if error:
        return error

    before = service_standard_snapshot(standard)
    actor_user = current_user()

    try:
        standard = service_standards.update_service_standard(
            standard,
            _standard_data_from_payload(payload),
        )
    except service_standards.ServiceStandardValidationError as exc:
        return _standard_validation_error(exc)
    except IntegrityError:
        return unique_field_conflict(
            "slug",
            payload.slug,
            "Service standard with this slug already exists in this group",
        )

    after = service_standard_snapshot(standard)

    write_audit(
        "service_standard.update",
        object_type="service_standard",
        object_id=standard.id,
        group_id=standard.group_id,
        data=payload.model_dump(),
    )

    _emit_standard_group_event(
        standard.group_id,
        event_type="service_standard.updated",
        title="Service standard updated",
        actor_user=actor_user,
        before=before,
        after=after,
        readiness_trigger="standard_updated",
    )

    return jsonify(_serialize_standard_with_checks(standard, include_disabled=True))


@services_bp.route("/standards/<int:standard_id>", methods=["DELETE"])
def delete_service_standard(standard_id):
    """Soft-delete a service standard and its checks."""

    standard, error = _get_accessible_standard(standard_id, write_required=True)

    if error:
        return error

    group_id = standard.group_id
    before = service_standard_snapshot(standard)
    actor_user = current_user()
    standard = service_standards.delete_service_standard(standard)
    after = service_standard_snapshot(standard)

    write_audit(
        "service_standard.delete",
        object_type="service_standard",
        object_id=standard.id,
        group_id=standard.group_id,
        data={"deleted": True},
    )

    _emit_standard_group_event(
        group_id,
        event_type="service_standard.deleted",
        title="Service standard deleted",
        actor_user=actor_user,
        before=before,
        after=after,
        readiness_trigger="standard_deleted",
    )

    return jsonify({
        "deleted": True,
        "id": standard.id,
    })


@services_bp.route("/standards/<int:standard_id>/checks", methods=["GET"])
def list_service_standard_checks(standard_id):
    """Return checks belonging to a service standard."""

    standard, error = _get_accessible_standard(standard_id)

    if error:
        return error

    include_disabled = request.args.get("include_disabled") == "1"
    checks = service_standards.list_standard_checks(
        standard.id,
        include_disabled=include_disabled,
    )

    return jsonify([
        serialize_service_standard_check(check)
        for check in checks
    ])


@services_bp.route("/standards/<int:standard_id>/checks/<int:check_id>", methods=["GET"])
def get_service_standard_check(standard_id, check_id):
    """Return one service standard check."""

    standard, error = _get_accessible_standard(standard_id)

    if error:
        return error

    check, error = _get_accessible_standard_check(standard, check_id)

    if error:
        return error

    return jsonify(serialize_service_standard_check(check))


@services_bp.route("/standards/<int:standard_id>/checks", methods=["POST"])
def create_service_standard_check(standard_id):
    """Create a service standard check."""

    standard, error = _get_accessible_standard(standard_id, write_required=True)

    if error:
        return error

    payload, error = validate_body(ServiceStandardCheckCreateSchema)

    if error:
        return error

    actor_user = current_user()

    try:
        check = service_standards.create_standard_check(
            standard,
            _standard_check_data_from_payload(payload),
        )
    except service_standards.ServiceStandardValidationError as exc:
        return _standard_check_validation_error(exc)
    except IntegrityError:
        return unique_field_conflict(
            "slug",
            payload.slug,
            "Check with this slug already exists in this standard",
        )

    write_audit(
        "service_standard_check.create",
        object_type="service_standard_check",
        object_id=check.id,
        group_id=standard.group_id,
        data={
            "standard_id": standard.id,
            **payload.model_dump(),
        },
    )

    _emit_standard_group_event(
        standard.group_id,
        event_type="service_standard_check.created",
        title="Service standard check created",
        actor_user=actor_user,
        payload={
            "standard": service_standard_snapshot(standard),
            "check": service_standard_check_snapshot(check),
        },
        readiness_trigger="standard_check_created",
    )

    return jsonify(serialize_service_standard_check(check)), 201


@services_bp.route("/standards/<int:standard_id>/checks/<int:check_id>", methods=["PUT"])
def update_service_standard_check(standard_id, check_id):
    """Update a service standard check."""

    standard, error = _get_accessible_standard(standard_id, write_required=True)

    if error:
        return error

    check, error = _get_accessible_standard_check(standard, check_id)

    if error:
        return error

    payload, error = validate_body(ServiceStandardCheckUpdateSchema)

    if error:
        return error

    before = service_standard_check_snapshot(check)
    actor_user = current_user()

    try:
        check = service_standards.update_standard_check(
            check,
            _standard_check_data_from_payload(payload),
        )
    except service_standards.ServiceStandardValidationError as exc:
        return _standard_check_validation_error(exc)
    except IntegrityError:
        return unique_field_conflict(
            "slug",
            payload.slug,
            "Check with this slug already exists in this standard",
        )

    after = service_standard_check_snapshot(check)

    write_audit(
        "service_standard_check.update",
        object_type="service_standard_check",
        object_id=check.id,
        group_id=standard.group_id,
        data={
            "standard_id": standard.id,
            **payload.model_dump(),
        },
    )

    _emit_standard_group_event(
        standard.group_id,
        event_type="service_standard_check.updated",
        title="Service standard check updated",
        actor_user=actor_user,
        payload={"standard": service_standard_snapshot(standard)},
        before=before,
        after=after,
        readiness_trigger="standard_check_updated",
    )

    return jsonify(serialize_service_standard_check(check))


@services_bp.route(
    "/standards/<int:standard_id>/checks/<int:check_id>",
    methods=["DELETE"],
)
def delete_service_standard_check(standard_id, check_id):
    """Soft-delete a service standard check."""

    standard, error = _get_accessible_standard(standard_id, write_required=True)

    if error:
        return error

    check, error = _get_accessible_standard_check(standard, check_id)

    if error:
        return error

    before = service_standard_check_snapshot(check)
    actor_user = current_user()
    check = service_standards.delete_standard_check(check)
    after = service_standard_check_snapshot(check)

    write_audit(
        "service_standard_check.delete",
        object_type="service_standard_check",
        object_id=check.id,
        group_id=standard.group_id,
        data={
            "standard_id": standard.id,
            "deleted": True,
        },
    )

    _emit_standard_group_event(
        standard.group_id,
        event_type="service_standard_check.deleted",
        title="Service standard check deleted",
        actor_user=actor_user,
        payload={"standard": service_standard_snapshot(standard)},
        before=before,
        after=after,
        readiness_trigger="standard_check_deleted",
    )

    return jsonify({
        "deleted": True,
        "id": check.id,
    })
