from flask import Blueprint, jsonify, request

from app.api.schemas.maintenance_windows import (
    MaintenanceWindowCancelSchema,
    MaintenanceWindowCreateSchema,
    MaintenanceWindowUpdateSchema,
)
from app.modules.db import maintenance_repo
from app.services.audit import write_audit
from app.services.maintenance import (
    cancel_maintenance_window,
    create_maintenance_window,
    delete_maintenance_window,
    update_maintenance_window,
)
from app.services.rbac import (
    current_user,
    require_team_read,
    require_team_write,
)
from app.services.serializers.services import (
    serialize_maintenance_window,
    serialize_utc_datetime,
)
from app.services.validation import (
    make_error_response,
    safe_exception_response,
    validate_body,
)


maintenance_bp = Blueprint("maintenance_api", __name__)


def _request_user():
    return getattr(request, "current_user", None) or current_user()


def _current_user_id():
    user = _request_user()

    if not user:
        raise PermissionError("authentication required")

    return user.id


def _maintenance_audit_data(window, payload=None):
    data = {
        "name": window.name,
        "status": window.status,
        "behavior": window.behavior,
        "timezone": window.timezone,
        "starts_at": serialize_utc_datetime(window.starts_at),
        "ends_at": serialize_utc_datetime(window.ends_at),
        "enabled": window.enabled,
        "apply_to_existing": bool(window.apply_to_existing),
        "reactivate_on_end": bool(window.reactivate_on_end),
        "deleted": window.deleted,
    }

    if getattr(window, "rrule", None):
        data["rrule"] = window.rrule

    if payload:
        data["payload"] = payload

    return data


def _write_maintenance_audit(action, window, payload=None):
    user = _request_user()

    write_audit(
        action,
        object_type="maintenance_window",
        object_id=window.id,
        group_id=window.group_id,
        team_id=window.team_id,
        user_id=user.id if user else None,
        data=_maintenance_audit_data(window, payload),
    )


def _check_window_read(window):
    for scope in window.scopes:
        if scope.team_id:
            error = require_team_read(scope.team_id)
            if error:
                return error

        if scope.service_id and scope.service:
            error = require_team_read(scope.service.team_id)
            if error:
                return error

        if scope.route_id and scope.route:
            error = require_team_read(scope.route.team_id)
            if error:
                return error

    return None


def _check_window_write(window):
    for scope in window.scopes:
        if scope.team_id:
            error = require_team_write(scope.team_id)
            if error:
                return error

        if scope.service_id and scope.service:
            error = require_team_write(scope.service.team_id)
            if error:
                return error

        if scope.route_id and scope.route:
            error = require_team_write(scope.route.team_id)
            if error:
                return error

    return None


def _format_payload_for_audit(payload):
    if not payload:
        return {}

    result = dict(payload)

    for field_name in ("starts_at", "ends_at"):
        value = result.get(field_name)

        if value and hasattr(value, "isoformat"):
            result[field_name] = value.isoformat()

    return result


@maintenance_bp.route("", methods=["GET"])
def list_maintenance_windows():
    team_id = request.args.get("team_id", type=int)
    service_id = request.args.get("service_id", type=int)
    route_id = request.args.get("route_id", type=int)
    group_id = request.args.get("group_id", type=int)

    if team_id:
        error = require_team_read(team_id)
        if error:
            return error

    windows = maintenance_repo.list_maintenance_windows(
        group_id=group_id,
        team_id=team_id,
        service_id=service_id,
        route_id=route_id,
        include_deleted=request.args.get("include_deleted") == "1",
        include_finished=request.args.get("include_finished", "1") == "1",
    )

    visible = []

    for window in windows:
        error = _check_window_read(window)
        if not error:
            visible.append(window)

    return jsonify([
        serialize_maintenance_window(window)
        for window in visible
    ])


@maintenance_bp.route("", methods=["POST"])
def create_window():
    payload_schema, error = validate_body(MaintenanceWindowCreateSchema)
    if error:
        return error

    payload = payload_schema.model_dump()

    try:
        window = create_maintenance_window(
            payload,
            user_id=_current_user_id(),
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="validation_error",
            message="Invalid maintenance window request.",
            status_code=400,
        )
    except PermissionError as exc:
        return safe_exception_response(
            exc,
            error="forbidden",
            message="Access denied.",
            status_code=403,
        )

    _write_maintenance_audit(
        "maintenance_window.create",
        window,
        _format_payload_for_audit(payload),
    )

    return jsonify(serialize_maintenance_window(window)), 201


@maintenance_bp.route("/<int:window_id>", methods=["GET"])
def get_window(window_id):
    window = maintenance_repo.get_maintenance_window(window_id)

    if not window:
        return make_error_response(
            error="not_found",
            message="Maintenance window not found.",
            status_code=404,
        )

    error = _check_window_read(window)
    if error:
        return error

    return jsonify(serialize_maintenance_window(window))


@maintenance_bp.route("/<int:window_id>", methods=["PUT"])
def update_window(window_id):
    payload_schema, error = validate_body(MaintenanceWindowUpdateSchema)
    if error:
        return error

    payload = payload_schema.model_dump(exclude_unset=True)

    try:
        window = update_maintenance_window(
            window_id,
            payload,
            user_id=_current_user_id(),
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="validation_error",
            message="Invalid maintenance window update request.",
            status_code=400,
        )
    except PermissionError as exc:
        return safe_exception_response(
            exc,
            error="forbidden",
            message="Access denied.",
            status_code=403,
        )
    except LookupError as exc:
        return safe_exception_response(
            exc,
            error="not_found",
            message="Maintenance window not found.",
            status_code=404,
        )

    _write_maintenance_audit(
        "maintenance_window.update",
        window,
        _format_payload_for_audit(payload),
    )

    return jsonify(serialize_maintenance_window(window))


@maintenance_bp.route("/<int:window_id>/cancel", methods=["POST"])
def cancel_window(window_id):
    payload_schema, error = validate_body(
        MaintenanceWindowCancelSchema,
        allow_empty=True,
    )
    if error:
        return error

    payload = payload_schema.model_dump(exclude_unset=True)

    try:
        window = cancel_maintenance_window(
            window_id,
            payload,
            user_id=_current_user_id(),
        )
    except ValueError as exc:
        return safe_exception_response(
            exc,
            error="validation_error",
            message="Invalid maintenance window cancellation request.",
            status_code=400,
        )
    except PermissionError as exc:
        return safe_exception_response(
            exc,
            error="forbidden",
            message="Access denied.",
            status_code=403,
        )
    except LookupError as exc:
        return safe_exception_response(
            exc,
            error="not_found",
            message="Maintenance window not found.",
            status_code=404,
        )

    _write_maintenance_audit(
        "maintenance_window.cancel",
        window,
        payload,
    )

    return jsonify(serialize_maintenance_window(window))


@maintenance_bp.route("/<int:window_id>", methods=["DELETE"])
def delete_window(window_id):
    try:
        window = delete_maintenance_window(
            window_id,
            user_id=_current_user_id(),
        )
    except PermissionError as exc:
        return safe_exception_response(
            exc,
            error="forbidden",
            message="Access denied.",
            status_code=403,
        )
    except LookupError as exc:
        return safe_exception_response(
            exc,
            error="not_found",
            message="Maintenance window not found.",
            status_code=404,
        )

    _write_maintenance_audit(
        "maintenance_window.delete",
        window,
        {
            "deleted": True,
        },
    )

    return jsonify({"deleted": True, "id": window.id})
