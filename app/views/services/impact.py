from flask import jsonify

from app.views.services.blueprint import services_bp
from app.api.schemas.services import ServiceImpactQuerySchema, ServiceImpactServiceQuerySchema
from app.modules.db import services_repo
from app.services.rbac import require_team_read, get_allowed_team_ids
from app.services.service_catalog.impact import build_service_impact_v2, build_single_service_impact_v2
from app.services.validation import validate_query, make_error_response


@services_bp.route("/impact", methods=["GET"])
def list_service_impact():
    """Return Service Impact v2 for readable services."""

    query, error = validate_query(ServiceImpactQuerySchema)

    if error:
        return error

    if query.service_id:
        service = services_repo.get_service(query.service_id)

        error = require_team_read(service.team_id)

        if error:
            return error

        team_ids = [service.team_id]

    elif query.team_id:
        error = require_team_read(query.team_id)

        if error:
            return error

        team_ids = [query.team_id]

    else:
        team_ids = get_allowed_team_ids()

    payload = build_service_impact_v2(
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
