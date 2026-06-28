from flask import jsonify
from peewee import DoesNotExist

from app.views.services.blueprint import services_bp
from app.api.schemas.services import ServiceAnalyticsQuerySchema
from app.modules.db import services_repo
from app.services.rbac import require_team_read, get_allowed_team_ids
from app.services.service_catalog.analytics import build_service_analytics_v2
from app.services.validation import validate_query, make_error_response


@services_bp.route("/analytics", methods=["GET"])
def service_analytics():
    """Return Service Analytics v2 for readable services."""

    query, error = validate_query(ServiceAnalyticsQuerySchema)

    if error:
        return error

    if query.service_id:
        try:
            service = services_repo.get_service(query.service_id)
        except DoesNotExist:
            return make_error_response(
                "service_not_found",
                "Service was not found",
                404,
                service_id=query.service_id,
            )

        if getattr(service, "deleted", False):
            return make_error_response(
                "service_not_found",
                "Service was not found",
                404,
                service_id=query.service_id,
            )

        if not query.include_disabled and not service.enabled:
            return make_error_response(
                "service_not_found",
                "Service was not found",
                404,
                service_id=query.service_id,
            )

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

    payload = build_service_analytics_v2(
        query,
        team_ids=team_ids,
    )

    return jsonify(payload)
