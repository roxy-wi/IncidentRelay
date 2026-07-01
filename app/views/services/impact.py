from flask import jsonify

from app.views.services.blueprint import services_bp
from app.api.schemas.services import (
    ServiceImpactHistoryQuerySchema,
    ServiceImpactQuerySchema,
    ServiceImpactServiceQuerySchema,
    ServiceImpactSnapshotListQuerySchema,
    ServiceImpactSnapshotQuerySchema,
)
from app.modules.db import services_repo
from app.services.rbac import require_team_read, get_allowed_team_ids
from app.services.service_catalog.impact import build_service_impact_v2, build_single_service_impact_v2
from app.services.service_catalog.impact_snapshots import (
    build_service_impact_history,
    capture_service_impact_snapshot,
    list_service_impact_snapshots,
)
from app.services.validation import validate_body, validate_query, make_error_response


def _resolve_impact_scope(query):
    """Return readable team ids for an impact query, or an RBAC error."""
    if query.service_id:
        service = services_repo.get_service(query.service_id)

        error = require_team_read(service.team_id)

        if error:
            return None, error

        return [service.team_id], None

    if query.team_id:
        error = require_team_read(query.team_id)

        if error:
            return None, error

        return [query.team_id], None

    return get_allowed_team_ids(), None


@services_bp.route("/impact", methods=["GET"])
def list_service_impact():
    """Return current Service Impact v2 for readable services."""

    query, error = validate_query(ServiceImpactQuerySchema)

    if error:
        return error

    team_ids, error = _resolve_impact_scope(query)

    if error:
        return error

    payload = build_service_impact_v2(
        query,
        team_ids=team_ids,
    )

    return jsonify(payload)


@services_bp.route("/impact/snapshots", methods=["GET"])
def list_service_impact_snapshot_history():
    """Return recent persisted Service Impact snapshots."""

    query, error = validate_query(ServiceImpactSnapshotListQuerySchema)

    if error:
        return error

    team_ids, error = _resolve_impact_scope(query)

    if error:
        return error

    payload = list_service_impact_snapshots(
        query,
        team_ids=team_ids,
    )

    return jsonify(payload)


@services_bp.route("/impact/snapshots", methods=["POST"])
def create_service_impact_snapshot():
    """Capture and persist a Service Impact snapshot for the requested scope."""

    payload, error = validate_body(ServiceImpactSnapshotQuerySchema)

    if error:
        return error

    team_ids, error = _resolve_impact_scope(payload)

    if error:
        return error

    snapshot = capture_service_impact_snapshot(
        payload,
        team_ids=team_ids,
        source="manual",
    )

    return jsonify(snapshot), 201


@services_bp.route("/impact/history", methods=["GET"])
def get_service_impact_history():
    """Return historical Service Impact analytics built from snapshots."""

    query, error = validate_query(ServiceImpactHistoryQuerySchema)

    if error:
        return error

    team_ids, error = _resolve_impact_scope(query)

    if error:
        return error

    payload = build_service_impact_history(
        query,
        team_ids=team_ids,
    )

    return jsonify(payload)


@services_bp.route("/<int:service_id>/impact", methods=["GET"])
def get_service_impact(service_id):
    """Return Service Impact v2 for one service."""

    service = services_repo.get_service(service_id)

    error = require_team_read(service.team_id)

    if error:
        return error

    query, error = validate_query(ServiceImpactServiceQuerySchema)

    if error:
        return error

    payload = build_single_service_impact_v2(
        service_id,
        query,
        team_ids=[service.team_id],
    )

    if not payload:
        return make_error_response(
            "service_not_found",
            "Service was not found",
            404,
            service_id=service_id,
        )

    return jsonify(payload)
